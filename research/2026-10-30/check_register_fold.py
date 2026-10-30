#!/usr/bin/env python3
"""Offline gate for the exact same guarded prefix-pair production pipeline.

No pool, wallet, mining connection or GPU work in --cpu-only mode.
GPU mode checks natural, forced fallback, and injected coordinate mismatch.
"""
from __future__ import annotations
import argparse
import ctypes as C
import hashlib
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent

def require(condition, message):
    if not condition:
        raise AssertionError(message)

def coord(sg, lane, slot):
    col = (sg & 1)*8+(lane & 1)*2+((lane >> 3) & 1)*4+(slot & 1)+((slot >> 1) & 3)*16
    row = (sg >> 1)*8+((lane >> 1) & 3)+((lane >> 4) & 1)*4+(slot >> 3)*16
    return row, col

def cpu_mapping_gate(np):
    all_coords = [coord(sg,lane,slot) for sg in range(4) for lane in range(32) for slot in range(32)]
    require(len(set(all_coords)) == 4096, 'coordinate map must cover every matrix cell once')
    rng = np.random.default_rng(0xF01D)
    for _ in range(12):
        matrix = rng.integers(0,2**32,(64,64),dtype=np.uint32)
        partials = {}; seen = set()
        for sg in range(4):
            fs = [[],[]]
            for lane in range(32):
                for which in range(2):
                    acc = 0
                    for i in range(8):
                        acc ^= int(matrix[coord(sg,lane,i+which*8)])
                        acc ^= int(matrix[coord(sg,lane,i+which*8+16)])
                    fs[which].append(acc)
            for lane in range(32):
                if lane & 9: continue
                for which in range(2):
                    row = (sg >> 1)*8+((lane >> 1)&3)+((lane >> 4)&1)*4+which*16
                    key = ((sg&1),row)
                    require(key not in seen, 'partial output has duplicate writers')
                    seen.add(key)
                    partials[key] = fs[which][lane]^fs[which][lane^8]^fs[which][lane^1]^fs[which][lane^9]
        require(len(seen)==64,'partial output coverage')
        wanted = np.bitwise_xor.reduce(matrix[:32]^matrix[32:],axis=1)
        actual = np.array([partials[(0,row)]^partials[(1,row)] for row in range(32)],dtype=np.uint32)
        require(np.array_equal(actual,wanted),'register fold mapping oracle')
    return {'full_coordinate_coverage':4096,'random_u32_matrices':12,'unique_partial_writers':64}

def main():
    parser=argparse.ArgumentParser(description=__doc__,allow_abbrev=False)
    parser.add_argument('--cpu-only',action='store_true')
    parser.add_argument('--library',type=Path,default=HERE/'libprefix.dylib')
    parser.add_argument('--shader',type=Path,default=HERE/'prefix.metal')
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    import numpy as np
    receipt={'schema':'prefix-register-fold-gate-v1','cpu_mapping':cpu_mapping_gate(np),
             'gpu_executed':False,'shader_sha256':hashlib.sha256(args.shader.read_bytes()).hexdigest()}
    if not args.cpu_only:
        import blake3
        from prefix_adapter import Native,Prepared
        native=Native(args.library,args.shader)
        native.lib.pfx_fold_control.argtypes=[C.c_uint64,C.c_uint32,C.c_char_p,C.c_size_t]
        native.lib.pfx_fold_control.restype=C.c_int
        native.lib.pfx_fold_counts.argtypes=[C.c_uint64,C.c_uint64,C.POINTER(C.c_uint32),C.c_char_p,C.c_size_t]
        native.lib.pfx_fold_counts.restype=C.c_int
        receipt.update(gpu_executed=True,device=native.device_name,runs=[],
                       library_sha256=hashlib.sha256(args.library.read_bytes()).hexdigest())
        rng=np.random.default_rng(0xF01D)
        seed=bytes(range(32));m=n=128
        try:
            for fixture in ('random','zero','half_limit'):
                x=rng.integers(-127,128,(32,m,128),dtype=np.int32)
                if fixture=='zero':x.fill(0)
                if fixture=='half_limit':
                    x.fill(0);x[:,:,0]=65504;x[:,:,1]=-65504
                v=rng.integers(-32,32,(n,128),dtype=np.int8)
                product=x.astype(np.int64)@v.astype(np.int64).T
                require(np.abs(product).max()<=2**24,'oracle exactness magnitude')
                rows=np.array([r//32*64+r%32 for r in range(64)])
                words=product.astype(np.int32).view(np.uint32)
                folded=np.bitwise_xor.reduce((words[:,rows]^words[:,rows+32]).reshape(32,64,2,64),axis=3)
                expected=((folded[:16]<<np.uint32(13))|(folded[:16]>>np.uint32(19)))^folded[16:]
                expected=expected.transpose(1,2,0).copy()
                expected_digests=np.empty((64,2,32),np.uint8)
                for r in range(64):
                    for c in range(2):
                        expected_digests[r,c]=np.frombuffer(blake3.blake3(expected[r,c].astype('<u4').tobytes(),key=seed).digest(),np.uint8)
                want_hits={(int(r),c*64) for r in rows for c in range(2)}
                for name,flags,want_counts in (('natural',1,(64,0,0)),('forced_fallback',3,(0,64,0)),('injected_mismatch',5,(0,64,64))):
                    native.check(native.lib.pfx_fold_control(native.context,flags,native.err,len(native.err)))
                    p=Prepared(native,x,v,seed)
                    try:
                        hits,tr,dg,result=p.scan(0,2,b'\xff'*32,exports=True)
                        counts=(C.c_uint32*3)()
                        native.check(native.lib.pfx_fold_counts(p.handle,p.generation,counts,native.err,len(native.err)))
                        require(tuple(counts)==want_counts,'layout branch gate '+name+': '+str(tuple(counts)))
                        require(np.array_equal(tr,expected),'every transcript '+fixture+'/'+name)
                        require(np.array_equal(dg,expected_digests),'every digest '+fixture+'/'+name)
                        require(len(hits)==128 and set(hits)==want_hits,'all hits '+fixture+'/'+name)
                        require(result.total_hits==result.stored_hits==result.tiles==128,'tile/count gate')
                        receipt['runs'].append({'fixture':fixture,'mode':name,'layout_counts':list(counts),
                                                'transcripts_checked':128,'digests_checked':128,'hits_checked':128})
                        print('PASS',fixture,name,list(counts),flush=True)
                    finally:p.close()
        finally:native.close()
    receipt['pass']=True
    if args.output:
        args.output.write_text(json.dumps(receipt,indent=2)+'\n')
        require(json.loads(args.output.read_text())==receipt,'receipt readback')
    print(json.dumps(receipt,sort_keys=True))

if __name__=='__main__':main()
