"""Bind the offline official-proof gate to this source build and Mac model."""
import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

KEY_FILES = ('build/libpearlmetal.dylib','tools/prefix_s_miner/libprefix.dylib',
    'tools/prefix_s_miner/prefix_native.mm','tools/prefix_s_miner/prefix.metal',
    'tools/prefix_s_miner/prefix_adapter.py','tools/prefix_sparse_host/zero_b_factory.py',
    'tools/prefix_sparse_host/build/libprefixsparse.dylib',
    'tools/merkle_overlay/overlay_probe.py','tools/merkle_overlay/build/libm1merkleprobe_c.dylib',
    'pearl_metal_miner/host.py','pearl_metal_miner/reference.py','pearl_metal_miner/metal_capi.py',
    'tools/prefix_s_miner/check_sparse_native.py','PINNED_PEARL_COMMIT.txt')


def identity(root, details):
    return {'platform':details['platform'],'chip':details['chip'],'machine':details['machine'],
        'sha256':{name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in KEY_FILES}}


def require_validated(root, details):
    path=root/'build/self-test.json'
    try:receipt=json.loads(path.read_text())
    except (OSError, ValueError) as error:
        raise RuntimeError('run pearl-m-miner self-test before mining/benchmarking this build') from error
    if (receipt.get('schema')!='pearl-m-offline-gate-v1' or receipt.get('official_proof_checks',0)<=0
            or receipt.get('identity')!=identity(root,details)):
        raise RuntimeError('build or device changed: rerun pearl-m-miner self-test')


def run_gate(root, details):
    before=identity(root,details)
    command=[sys.executable,'-u',str(root/'tools/prefix_s_miner/check_sparse_native.py'),
             '--miner-root',str(root),'--factory-root',str(root/'tools/prefix_sparse_host'),'--method','s']
    env={k:v for k,v in os.environ.items() if not k.startswith('FUSION_')}
    env['PRL_CONFIG']=os.devnull
    proof_checks=0
    child=subprocess.Popen(command,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
    try:
        for line in child.stdout:
            print(line,end='',flush=True)
            if line.startswith('SPARSE_NATIVE_GATES_PASSED '):
                record=json.loads(line.split(' ',1)[1])
                if record.get('method')=='s':proof_checks=int(record.get('official_proof_checks',0))
        code=child.wait()
    finally:
        if child.poll() is None:
            child.terminate()
            try:child.wait(timeout=30)
            except subprocess.TimeoutExpired:child.kill();child.wait()
    if code or not proof_checks or identity(root,details)!=before:
        raise RuntimeError('offline gate failed or source changed; mining remains disabled')
    receipt={'schema':'pearl-m-offline-gate-v1','identity':before,'official_proof_checks':proof_checks,
             'completed_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
             'scope':'offline arithmetic/proof correctness; not pool acceptance or income'}
    path=root/'build/self-test.json';temp=path.with_suffix('.tmp')
    temp.write_text(json.dumps(receipt,indent=2)+'\n');temp.replace(path)
    require_validated(root,details)
    print('SELF_TEST_VERIFIED: official proof gate saved for this build and Mac model',flush=True)
    return 0
