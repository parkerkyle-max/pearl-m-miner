"""Offline component diagnosis; repeated work is never credited as mining."""
from __future__ import annotations
import argparse
import ctypes as C
import hashlib
import json
import math
import os
from pathlib import Path
import statistics
import sys
import time

HERE=Path(__file__).resolve().parent
class Stage(C.Structure):
    _fields_=[(n,C.c_uint64) for n in ('version','mode','tiles_per_iteration','iterations','observed_hits')]+[
        ('gpu_seconds',C.c_double),('wall_seconds',C.c_double)]

def main():
    p=argparse.ArgumentParser(description=__doc__,allow_abbrev=False)
    p.add_argument('--source',type=Path,required=True)
    p.add_argument('--library',type=Path,default=HERE/'libprefixprofile.dylib')
    p.add_argument('--shader',type=Path,default=HERE/'prefix_baseline.metal')
    p.add_argument('--m',type=int,default=16384);p.add_argument('--n',type=int,default=65536)
    p.add_argument('--region-rows',type=int,default=512)
    p.add_argument('--cycles',type=int,default=6);p.add_argument('--iterations',type=int,default=8)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    if a.output.exists():raise RuntimeError('fresh output path required')
    if not(1<=a.cycles<=128 and 1<=a.iterations<=128 and a.region_rows%32==0):raise ValueError('bounded profile parameters')
    root=a.source.resolve()
    os.environ.update(PRL_CONFIG=os.devnull,FUSION_PREFIX_GPU_PREPARE='1',FUSION_PREFIX_PREPARE_METHOD='s',
        FUSION_PREFIX_WORKERS='2',RAYON_NUM_THREADS='2',FUSION_METAL_NONCE_LEAF='0',
        FUSION_OVERLAY_ROOT=str(root/'tools/merkle_overlay'),
        FUSION_MERKLE_LIBRARY=str(root/'tools/merkle_overlay/build/libm1merkleprobe_c.dylib'))
    sys.path[:0]=[str(root),str(HERE),str(root/'tools/prefix_sparse_host')]
    from pearl_metal_miner import reference as ref
    from pearl_metal_miner.metal_capi import JobShape
    from zero_b_factory import ZeroBFactory
    from prefix_adapter import Native,PreparedSparse
    from pearl_m_miner.safety import wait_until_safe
    shape=JobShape(4096,128,ref.Pattern.from_list([0,32]),ref.Pattern.from_list(list(range(64))))
    header=ref.header_to_bytes(0x20000000,bytes(range(32)),bytes(range(32,64)),0x66661030,0x207fffff)
    factory=ZeroBFactory(noise_backend='metal');native=Native(a.library,a.shader)
    native.lib.pfx_stage_profile_size.argtypes=[];native.lib.pfx_stage_profile_size.restype=C.c_uint32
    assert native.lib.pfx_stage_profile_size()==C.sizeof(Stage)==56
    native.lib.pfx_profile_stages.argtypes=[C.c_uint64]*3+[C.c_uint32]*4+[C.POINTER(Stage),C.c_char_p,C.c_size_t]
    native.lib.pfx_profile_stages.restype=C.c_int
    record={'schema':'pearl-m-component-profile-v1','device':native.device_name,'m':a.m,'n':a.n,'region_rows':a.region_rows,
        'cycles':a.cycles,'iterations':a.iterations,'miner_hashrate':None,'income':None,'pool_submissions':0,
        'repeats_same_immutable_work':True,'independent_component_times_not_necessarily_additive':True,
        'source_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (a.library,a.shader,Path(__file__))},
        'preparations':[],'stages':[]}
    prepared=None;seeds=set()
    try:
        for i in range(5):
            wait_until_safe(native.lib.pfx_thermal_state)
            t=time.perf_counter();grid=factory.prepare(shape,a.m,a.n,header,cert_version=3,job_identity=(1,'component-profile'))
            factory_wall=time.perf_counter()-t
            assert grid.a_seed not in seeds;seeds.add(grid.a_seed)
            if prepared:prepared.close()
            t=time.perf_counter()
            prepared=PreparedSparse(native,grid.prefix_u,grid.prefix_pa,grid.prefix_qb,
                grid.prefix_nonce_leaf,grid.nonce_leaf_index,grid.prefix_v,grid.a_seed,method='s')
            record['preparations'].append({'cold':i==0,'factory_wall_s':factory_wall,
                'native_wrapper_wall_s':time.perf_counter()-t,'factory_detail':factory.last_profile,
                'native':prepared.stats.record(),'s_detail':prepared.s_detail})
        bands=min(a.region_rows//32,a.m//64)
        for cycle in range(a.cycles):
            lo=(cycle*bands)%(a.m//64)
            count=min(bands,a.m//64-lo)
            for mode in [(cycle+i)%3 for i in range(3)]:
                wait_until_safe(native.lib.pfx_thermal_state)
                stage=Stage()
                native.check(native.lib.pfx_profile_stages(prepared.handle,prepared.generation,prepared.epoch,
                    lo,count,mode,a.iterations,C.byref(stage),native.err,len(native.err)))
                row={name:getattr(stage,name) for name,_ in stage._fields_}
                assert row['version']==1 and row['mode']==mode and row['iterations']==a.iterations
                assert row['tiles_per_iteration']==count*32*(a.n//64)
                assert all(math.isfinite(row[n]) and row[n]>0 for n in ('gpu_seconds','wall_seconds'))
                row.update(cycle=cycle,band_lo=lo,mode_name=('combined','gemm_and_fold','hash_and_target')[mode])
                row['gpu_ms_per_iteration']=1000*row['gpu_seconds']/a.iterations
                # Diagnostic FLOPs, not PRL credit: a tile's scan is524288MAC.
                row['leading_matmul_tflops']=None if mode==2 else row['tiles_per_iteration']*a.iterations*1048576/row['gpu_seconds']/1e12
                record['stages'].append(row)
        record['summary']={name:{'median_gpu_ms':statistics.median(r['gpu_ms_per_iteration'] for r in record['stages'] if r['mode']==mode),
            'mean_gpu_ms':statistics.mean(r['gpu_ms_per_iteration'] for r in record['stages'] if r['mode']==mode)}
            for mode,name in enumerate(('combined','gemm_and_fold','hash_and_target'))}
        record['scope']='replayed, non-mining component diagnostic; cache/scheduling differ from fresh-grid production'
        a.output.write_text(json.dumps(record,indent=2)+'\n')
        assert json.loads(a.output.read_text())==record
        print('COMPONENT_PROFILE_NON_MINING '+json.dumps(record['summary']),flush=True)
    finally:
        if prepared:prepared.close()
        native.close();factory.close()

if __name__=='__main__':main()
