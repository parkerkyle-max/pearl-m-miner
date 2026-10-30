"""Independent CPU layout, varying-input and logical operation-count checks."""
import json
from pathlib import Path
import numpy as np

def small(x):
    x&=0xffffffff
    x^=x>>16;x=(x*0x7feb352d)&0xffffffff
    x^=x>>15;x=(x*0x846ca68b)&0xffffffff;x^=x>>16
    return (-2,-1,1,2)[x&3]

reports=[]
for rows,k,sets,chains,iterations in ((8,8,2,4,7),(64,128,2,1,3)):
    a=np.empty((sets,iterations,rows,k),np.int64)
    b=np.empty((sets,iterations,chains,rows,k),np.int64)
    for s in range(sets):
        for it in range(iterations):
            for r in range(rows):
                for q in range(k):
                    a[s,it,r,q]=small(r*65537+q*257+s*17+it*100003+0xa531)
            for chain in range(chains):
                for r in range(rows):
                    for q in range(k):
                        b[s,it,chain,r,q]=small(r*4099+q*65537+s*31+chain*4093+it*104729+0x3719)
    for s in range(sets):
        assert len({a[s,it].tobytes()+b[s,it].tobytes() for it in range(iterations)})==iterations
    wanted=np.zeros((sets,chains,rows,rows),np.int64)
    actual=np.zeros(wanted.shape,np.float32)
    for it in range(iterations):
        for s in range(sets):
            for chain in range(chains):
                wanted[s,chain]+=a[s,it]@b[s,it,chain].T
                actual[s,chain]+=a[s,it].astype(np.float32)@b[s,it,chain].astype(np.float32).T
    assert np.array_equal(actual.astype(np.int64),wanted)
    wrong=np.stack([[a[s,0]@b[s,0,chain].T*iterations for chain in range(chains)] for s in range(sets)])
    assert not np.array_equal(wrong,wanted), 'single-product hoist must fail these fixtures'
    assert 4*k*iterations<=1<<24
    # Flat indexing in host/shader names the same unique ranges.
    aa=a.reshape(-1);bb=b.reshape(-1)
    for s in range(sets):
        for it in range(iterations):
            for r,q in ((0,0),(rows-1,k-1)):
                assert aa[((s*iterations+it)*rows+r)*k+q]==a[s,it,r,q]
                for chain in range(chains):
                    assert bb[(((s*iterations+it)*chains+chain)*rows+r)*k+q]==b[s,it,chain,r,q]
    reports.append({'m':rows,'n':rows,'k':k,'sets':sets,'chains':chains,'iterations':iterations,
        'macs_per_dispatch':sets*chains*rows*rows*k*iterations,'flops_per_dispatch':2*sets*chains*rows*rows*k*iterations,
        'all_cpu_outputs_exact':True,'single_product_times_iterations_is_wrong':True,'unique_sequence_ranges':True})
source=(Path(__file__).parent/'peak_stream.metal').read_text()
assert source.count('sequence=ulong(')==2
assert 'iteration<params.x' in source
assert 'params.z+iteration' in source
assert '%params' not in source
print(json.dumps({'schema':'m1-stream-cpu-control-v1','reports':reports,'gpu_executed':False},indent=2))
