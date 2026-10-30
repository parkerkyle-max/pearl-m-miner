"""CPU-only count/bound/fixture audit. This does not qualify Metal execution."""
import json
from pathlib import Path
import numpy as np

cases=[]
for k,rows,sets,chains in ((8,8,4096,4),(128,64,64,1)):
    per_iteration=sets*chains*rows*rows*k
    assert per_iteration==(4096*4*512 if k==8 else 64*524288)
    assert per_iteration*2==(16777216 if k==8 else 67108864)
    for value,label in ((63,'product3969'),(127,'product16129'),(64,'2pow24')):
        iterations=3 if value==63 else (1<<24)//(k*value*value)
        expected=k*value*value*iterations
        assert expected<=1<<24
        accumulator=np.float32(0)
        # Independent scalar recurrence with float32 multiply/accumulation.
        for _ in range(k*iterations):
            accumulator=np.float32(accumulator+np.float32(value)*np.float32(value))
        assert float(accumulator)==expected
        cases.append({'k':k,'input':value,'iterations':iterations,'label':label,'expected':expected,'exact_cpu_float32':True})
    assert 4*k*32768<=1<<24
assert float(np.float16(63)*np.float16(63))!=3969
assert float(np.float32(np.float16(63))*np.float32(np.float16(63)))==3969
assert float(np.float16(127)*np.float16(127))!=16129
assert float(np.float32(np.float16(127))*np.float32(np.float16(127)))==16129
source=(Path(__file__).parent/'peak.metal').read_text()
assert 'iteration<params.x' in source
assert 'simdgroup_store(c[q]' in source
assert 'operation.run(a,b,accumulator)' in source
print(json.dumps({'schema':'m1-peak-cpu-count-audit-v1','cases':cases,'mac_count_checks':True,
                  'half_product_counterexamples_checked':True,'gpu_executed':False},indent=2))
