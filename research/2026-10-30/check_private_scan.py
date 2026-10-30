"""Compare non-export production scans with every independently checked tile."""
import argparse
import os
from pathlib import Path
import sys

p=argparse.ArgumentParser()
p.add_argument('--source',type=Path,required=True)
p.add_argument('--library',type=Path,required=True)
p.add_argument('--shader',type=Path,required=True)
a=p.parse_args()
root=a.source.resolve()
os.environ['FUSION_OVERLAY_ROOT']=str(root/'tools/merkle_overlay')
os.environ['FUSION_MERKLE_LIBRARY']=str(root/'tools/merkle_overlay/build/libm1merkleprobe_c.dylib')
sys.path[:0]=[str(root),str(root/'tools/prefix_s_miner'),str(root/'tools/prefix_sparse_host')]
import blake3
import numpy as np
from pearl_metal_miner import reference as ref
from pearl_metal_miner.metal_capi import JobShape
from prefix_adapter import Native,PreparedSparse
from zero_b_factory import ZeroBFactory
shape=JobShape(4096,128,ref.Pattern.from_list([0,32]),ref.Pattern.from_list(list(range(64))))
header=ref.header_to_bytes(0x20000000,bytes(range(32)),bytes(range(32,64)),0x66661030,0x207fffff)
factory=ZeroBFactory(noise_backend='metal')
native=Native(a.library,a.shader)
snapshots=[]
try:
    grid=factory.prepare(shape,256,256,header,cert_version=3,job_identity=(1,'private-scan-gate'))
    u,pa,vbytes,qb=factory._noise.get(grid.a_seed,grid.b_seed)
    v=np.frombuffer(vbytes,np.int8).reshape(256,128).copy()
    src=(u.copy(),pa.copy(),qb.copy(),grid.tree_a.overlay.leaf,grid.tree_a.overlay.nonce_index,v,bytes(grid.a_seed))
    target=(1<<255)-1
    bound=target.to_bytes(32,'little')
    def prepared():
        value=PreparedSparse(native,*src,debug=False,method='s')
        snapshots.append(value)
        return value
    plain,export=prepared(),prepared()
    x=grid.prefix_x.astype(np.int64)
    for band in range(4):
        # Switch export modes on a retained prepared generation, exercising
        # allocation storage-mode changes with equal buffer capacity.
        exported=band%2==0
        hits,tr,dg,result=plain.scan(band,1,bound,exports=exported)
        expected,tr2,dg2,result2=export.scan(band,1,bound,exports=True)
        assert set(hits)==set(expected) and len(hits)==len(expected)
        assert result.tiles==result2.tiles==128
        assert result.total_hits==result.stored_hits==len(expected)
        for ri in range(32):
            r=band*64+ri
            for ci in range(4):
                values=x[:,[r,r+32]]@v[ci*64:(ci+1)*64].astype(np.int64).T
                words=values.astype(np.int32).view(np.uint32)
                folded=np.bitwise_xor.reduce(words[:,0]^words[:,1],axis=1)
                transcript=((folded[:16]<<np.uint32(13))|(folded[:16]>>np.uint32(19)))^folded[16:]
                digest=blake3.blake3(transcript.astype('<u4').tobytes(),key=grid.a_seed).digest()
                assert np.array_equal(tr2[ri,ci],transcript)
                assert dg2[ri,ci].tobytes()==digest
                assert ((r,ci*64) in set(hits))==(int.from_bytes(digest,'little')<=target)
        if exported:
            assert np.array_equal(tr,tr2) and np.array_equal(dg,dg2)
        else:
            assert tr is None and dg is None
    print('PRIVATE_SCAN_GATE_PASSED: 512 independent transcript/digest/target checks; alternating export modes',flush=True)
finally:
    for value in snapshots:value.close()
    native.close()
    factory.close()
