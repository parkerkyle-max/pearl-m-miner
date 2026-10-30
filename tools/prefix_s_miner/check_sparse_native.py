#!/usr/bin/env python3
"""Persistent sparse-prepare ABI, private-generation and actual export gates.

Uses the already verified CPU-transform factory as oracle. No pool connection.
Default128x128 compares every transcript/digest. Large mode compares every X
int32/half element, then a bounded scan's selected tiles and every returned hit.
"""
import argparse
import ctypes as C
from concurrent.futures import ThreadPoolExecutor
import gc
import json
import os
from pathlib import Path
import sys

HERE=Path(__file__).resolve().parent

def require(ok,why):
    if not ok:raise AssertionError(why)

def main():
    parser=argparse.ArgumentParser(description=__doc__,allow_abbrev=False)
    parser.add_argument('--miner-root',type=Path,required=True)
    parser.add_argument('--factory-root',type=Path,default=HERE.parent/'m1-prefix-integration')
    parser.add_argument('--library',type=Path,default=HERE/'libprefix.dylib')
    parser.add_argument('--shader',type=Path,default=HERE/'prefix.metal')
    parser.add_argument('--m',type=int,default=128);parser.add_argument('--n',type=int,default=128)
    parser.add_argument('--full-export-only',action='store_true')
    parser.add_argument('--method',choices=('csr','s'),default='csr')
    args=parser.parse_args()
    sys.path[:0]=[str(args.miner_root.resolve()),str(args.factory_root.resolve())]
    import blake3,numpy as np,pearl_mining as pm
    from pearl_metal_miner import reference as ref
    from pearl_metal_miner.metal_capi import JobShape
    from zero_b_factory import ZeroBFactory
    from compact_targets import proof_target_bracket
    from prefix_adapter import Native,Prepared,PreparedSparse,PrefixError,PrepStats
    shape=JobShape(4096,128,ref.Pattern.from_list([0,32]),ref.Pattern.from_list(list(range(64))))
    header=ref.header_to_bytes(0x20000000,bytes(range(32)),bytes(range(32,64)),0x66661030,0x207fffff)
    os.environ['FUSION_METAL_NONCE_LEAF']='0'
    factory=ZeroBFactory(noise_backend='metal');native=Native(args.library,args.shader)
    live=[];records=[];proof_checks=0
    require(native.sparse_supported and native.lib.pfx_abi_version()==native.lib.pfx_sparse_abi_version()==1,'ABI gates')
    def inputs(grid):
        u,pa,vbytes,qb=factory._noise.get(grid.a_seed,grid.b_seed)
        return [u.copy(),pa.copy(),qb.copy(),grid.tree_a.overlay.leaf,0,
                np.frombuffer(vbytes,np.int8).reshape(grid.n_dim,128).copy(),bytes(grid.a_seed)]
    def create(source,debug=True):
        p=PreparedSparse(native,*source,debug=debug,method=args.method);live.append(p)
        require(p.kind==(2 if args.method=='s' else 1),'explicit algorithm path gate');return p
    def check_export(p,want,label):
        raw,half=p.export_x()
        require(np.array_equal(raw,want),label+' actual GPU int32 export differs')
        require(np.array_equal(half.astype(np.int32),want),label+' actual GPU half export differs')
        records.append({'label':label,'all_x_elements':int(raw.size),'prepare':p.stats.record(),
                        'method':p.method,'native_kind':p.kind,'s_extension':p.s_detail})
        print('PASS full X/half '+label+' elements='+str(raw.size),flush=True)
    def tile(x,v,ri,ci,seed):
        row=(ri//32)*64+ri%32
        values=x[:,[row,row+32]].astype(np.int64)@v[ci*64:(ci+1)*64].astype(np.int64).T
        require(np.abs(values).max()<=1<<24,'int64 tile bound')
        words=values.astype(np.int32).view(np.uint32)
        f=np.bitwise_xor.reduce(words[:,0]^words[:,1],axis=1)
        t=((f[:16]<<np.uint32(13))|(f[:16]>>np.uint32(19)))^f[16:]
        return t,blake3.blake3(t.astype('<u4').tobytes(),key=seed).digest()
    def scan(p,x,v,label,grid=None):
        nonlocal proof_checks
        bands=min(2,p.m//64);rows=bands*32;ncols=p.n//64
        small=rows*ncols<=4096
        bound=b'\xff'*32 if small else ((1<<248)-1).to_bytes(32,'little')
        hits,tr,dg,result=p.scan(0,bands,bound,exports=True)
        require(result.tiles==rows*ncols,'scan tiles')
        target=int.from_bytes(bound,'little')
        wanted={(ri//32*64+ri%32,ci*64) for ri in range(rows) for ci in range(ncols)
                if int.from_bytes(dg[ri,ci].tobytes(),'little')<=target}
        require(result.total_hits==result.stored_hits==len(wanted)<4097,'scan hit count/overflow')
        require(set(hits)==wanted and len(hits)==len(wanted),'scan target coordinates')
        points={(ri,ci) for ri in range(rows) for ci in range(ncols)} if small else {
            (ri,ci) for ri in (0,31,rows-1) for ci in (0,ncols//2,ncols-1)}
        points.update(((r//64)*32+r%64,c//64) for r,c in hits)
        for ri,ci in sorted(points):
            t,d=tile(x,v,ri,ci,p.seed)
            require(np.array_equal(tr[ri,ci],t) and dg[ri,ci].tobytes()==d,label+' exact transcript/digest')
        if grid is not None:
            official_header=pm.IncompleteBlockHeader.from_bytes(header)
            factor=ref.difficulty_factor(shape.h,shape.w,shape.k,shape.r)
            for row,col in ((0,0),(31,p.n-64)):
                value=int.from_bytes(dg[row,col//64].tobytes(),'little')
                low,high=proof_target_bracket(value,factor,ref.target_to_nbits,ref.nbits_to_target)
                proof=grid.craft_proof(row,col)
                for compact,wanted in ((low,False),(high,True)):
                    ok,why=pm.verify_plain_proof_for_cert_version(grid.cert_version,official_header,proof,nbits_override=compact)
                    require(bool(ok)==wanted,label+' official proof bracket: '+str(why));proof_checks+=1
        print('PASS scan '+label+' '+json.dumps({'tiles':int(result.tiles),'independent_oracle_tiles':len(points),'all_transcript_oracle':small}),flush=True)
    def refused(fn,label,reason=None):
        try:fn()
        except (PrefixError,ValueError) as error:
            if reason:require(reason in str(error),'wrong rejection '+label+': '+str(error))
            print('PASS refused '+label+': '+str(error),flush=True);return
        raise AssertionError('accepted invalid '+label)
    try:
        g1=factory.prepare(shape,args.m,args.n,header,cert_version=3,job_identity=(1,'sparse-native'))
        source1=inputs(g1);p1=create(source1);check_export(p1,g1.prefix_x,'generation1')
        if args.full_export_only:
            scan(p1,g1.prefix_x,g1.prefix_v,'large-export-gate',g1)
            print('SPARSE_FULL_EXPORT_PASS '+json.dumps({'records':records,'official_proof_checks':proof_checks}),flush=True);return
        require(args.m==args.n==128,'full adversarial/lifetime gate is bounded to128x128')
        # Same QB cache hit with different A/PA/U must not share destination buffers.
        g2=factory.prepare(shape,128,128,header,cert_version=3,job_identity=(1,'sparse-native'))
        source2=inputs(g2);p2=create(source2);check_export(p2,g2.prefix_x,'generation2-cache-hit')
        require(g1.a_seed!=g2.a_seed,'test must use two genuinely different committed roots')
        for i in (0,1,2,5):source1[i].fill(0)
        del source1;gc.collect()
        check_export(p1,g1.prefix_x,'generation1-after-source-mutation-and-generation2')
        # Changing actual QB replaces the immutable CSR cache, never prior data.
        alt=list(source2);alt[2]=source2[2][:,::-1].copy();p3=create(alt)
        check_export(p3,-g2.prefix_x,'opposite-QB-cache-replacement')
        check_export(p2,g2.prefix_x,'generation2-after-CSR-replacement')
        scan(p1,g1.prefix_x,g1.prefix_v,'generation1',g1)
        scan(p2,g2.prefix_x,g2.prefix_v,'generation2',g2)
        scan(p3,-g2.prefix_x,g2.prefix_v,'opposite-QB')
        # A production snapshot retains no int32 debug buffer.
        prod=create(source2,debug=False)
        if args.method=='s':
            second_prod=create(source2,debug=False)
            require(second_prod.s_detail['scratch_reused']==1,'S production float scratch was not reused')
            # Hold the earlier production generation across scratch reuse, and
            # retain the debug generation across a production overwrite too.
            check_export(p2,g2.prefix_x,'debug-generation-after-production-scratch-reuse')
            scan(prod,g2.prefix_x,g2.prefix_v,'retained-production-before-scratch-reuse',g2)
            scan(second_prod,g2.prefix_x,g2.prefix_v,'new-production-after-scratch-reuse',g2)
        raw=np.empty_like(g2.prefix_x);half=np.empty(raw.shape,np.float16)
        rc=native.lib.pfx_export_sparse(prod.handle,prod.generation,prod.epoch,raw.ctypes.data,raw.nbytes,
            half.ctypes.data,half.nbytes,native.err,len(native.err))
        require(rc!=0 and b'debug snapshot unavailable' in native.err.value,'flags0 must not retain debug X')
        # Old prepare is still callable in this library and reports old path.
        legacy=Prepared(native,g2.prefix_x,g2.prefix_v,g2.a_seed);live.append(legacy)
        kind=C.c_uint32(99);native.check(native.lib.pfx_prepared_kind(legacy.handle,legacy.generation,legacy.epoch,C.byref(kind),native.err,len(native.err)))
        require(kind.value==0,'legacy path gate');scan(legacy,g2.prefix_x,g2.prefix_v,'legacy regression',g2)
        # All1024 leaf bytes contribute, including a nonzero last byte in last leaf.
        rng=np.random.default_rng(10731);tail=rng.integers(-1,2,1024,dtype=np.int8);tail[-1]=1
        general=list(source2);general[3]=tail.tobytes();general[4]=511
        u,pa,qb,leaf,leafidx,v,seed=general
        signal=np.zeros((128,4096),np.int8);signal.reshape(-1)[leafidx*1024:(leafidx+1)*1024]=tail
        an=signal.astype(np.int64)+u[:,pa[:,0]].astype(np.int64)-u[:,pa[:,1]].astype(np.int64)
        expected=np.empty((32,128,128),np.int32);acc=np.zeros((128,128),np.int64)
        for k in range(4096):
            acc[:,int(qb[k,0])]+=an[:,k];acc[:,int(qb[k,1])]-=an[:,k]
            if (k+1)%128==0:expected[(k+1)//128-1]=acc
        pg=create(general);check_export(pg,expected,'full-leaf-tail-last-index');scan(pg,expected,v,'full-leaf-tail')
        for name,index,change,reason in (
            ('U range',0,lambda a:a.__setitem__((127,127),-33),'U range'),
            ('PA range',1,lambda a:a.__setitem__((4095,1),128),'PA indices'),
            ('QB duplicate',2,lambda a:a.__setitem__((4095,1),a[4095,0]),'QB indices'),
            ('V last range',5,lambda a:a.__setitem__((127,127),32),'GPU guard rejected')):
            bad=list(source2);bad[index]=bad[index].copy();change(bad[index]);refused(lambda:create(bad),name,reason)
        bad=list(source2);bad[3]=bad[3][:-1]+bytes([2]);refused(lambda:create(bad),'leaf tail range','nonce signal range')
        bad=list(source2);bad[4]=512;refused(lambda:create(bad),'leaf index')
        bad=list(source2);bad[0]=np.zeros_like(bad[0]);bad[0][:,0]=31;bad[0][:,1]=-32
        repeated=np.tile(np.array([[0,1]],np.uint32),(4096,1));bad[1]=repeated;bad[2]=repeated.copy()
        refused(lambda:create(bad),'unsafe generated X','GPU guard rejected')
        if args.method=='s':
            bad=list(source2);bad[0]=np.zeros_like(bad[0]);bad[1]=repeated.copy();bad[2]=repeated.copy()
            bad[2][-1]=[2,3];bad[3]=bytes(1024)
            refused(lambda:create(bad),'S=4095 half-inexact despite zero final X','GPU guard rejected')
            refused(lambda:create(bad,debug=False),'locked production S guard failure','GPU guard rejected')
            # Two real synchronous ctypes calls release the GIL. Their shared
            # float scratch must serialize, while each returned half remains
            # independently correct and usable after the next preparation.
            opposite=list(source2);opposite[2]=source2[2][:,::-1].copy()
            with ThreadPoolExecutor(max_workers=2) as executor:
                f1=executor.submit(create,source2,False)
                f2=executor.submit(create,opposite,False)
                positive,negative=f1.result(),f2.result()
            require(positive.s_detail['scratch_reused']==negative.s_detail['scratch_reused']==1,'concurrent S did not use locked scratch')
            scan(positive,g2.prefix_x,g2.prefix_v,'concurrent-S-positive-after-failed-prepare',g2)
            scan(negative,-g2.prefix_x,g2.prefix_v,'concurrent-S-negative-after-failed-prepare')
        refused(lambda:PreparedSparse(native,*source2,method='unknown'),'unknown method','must be csr or s')
        safe=create(source2);check_export(safe,g2.prefix_x,'safe-after-rejections')
        # Wrong generation/epoch and aliased readback must refuse before copies.
        old=safe.generation;safe.generation+=1;refused(safe.export_x,'debug wrong generation');safe.generation=old
        old=safe.epoch;safe.epoch+=1;refused(safe.export_x,'debug wrong epoch');safe.epoch=old
        rc=native.lib.pfx_export_sparse(safe.handle,safe.generation,safe.epoch,raw.ctypes.data,raw.nbytes,
            raw.ctypes.data,half.nbytes,native.err,len(native.err))
        require(rc!=0 and b'aliased debug' in native.err.value,'debug output alias')
        # Context destroys its cache ownership, but prepared GPU snapshots persist.
        native.close();check_export(safe,g2.prefix_x,'after-context-close');scan(safe,g2.prefix_x,g2.prefix_v,'after-context-close',g2)
        print('SPARSE_NATIVE_GATES_PASSED '+json.dumps({'records':records,'method':args.method,'production_debug_refused':True,
            'legacy_path_preserved':True,'source_snapshot_and_CSR_cache_lifetime':True,
            'official_proof_checks':proof_checks,'pool_claim':False}),flush=True)
    finally:
        for p in reversed(live):p.close()
        native.close();factory.close()

if __name__=='__main__':main()
