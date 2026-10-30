"""Local build provenance; contains no wallet, credentials or machine hostname."""
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import subprocess

root=Path(__file__).resolve().parents[1]
paths=['build/libpearlmetal.dylib','tools/prefix_s_miner/libprefix.dylib',
       'tools/prefix_s_miner/prefix_native.mm','tools/prefix_s_miner/prefix.metal',
       'tools/prefix_s_miner/prefix_adapter.py','tools/prefix_sparse_host/zero_b_factory.py',
       'tools/merkle_overlay/overlay_probe.py','tools/merkle_overlay/build/libm1merkleprobe_c.dylib']
record={'schema':'pearl-m-source-build-v1','pearl_commit':(root/'PINNED_PEARL_COMMIT.txt').read_text().strip(),
        'python':platform.python_version(),'macos':platform.mac_ver()[0],
        'sdk':subprocess.check_output(['xcrun','--show-sdk-version'],text=True).strip(),
        'versions':{n:importlib.metadata.version(n) for n in ('numpy','blake3','maturin')},
        'sha256':{p:hashlib.sha256((root/p).read_bytes()).hexdigest() for p in paths}}
(root/'build/provenance.json').write_text(json.dumps(record,indent=2)+'\n')
print('Build provenance written to build/provenance.json')
