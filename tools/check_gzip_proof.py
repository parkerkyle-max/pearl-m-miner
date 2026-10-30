#!/usr/bin/env python3
"""Offline gzip check using real official proofs at production dimensions.

Uses an explicitly easy synthetic header; never connects to a pool or submits
work. A pass proves byte-exact transport and official verification, not a share
accepted by Kryptex. Requires bootstrap and self-test on an Apple Silicon Mac.
"""
import base64
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'tools/prefix_sparse_host')]


def main():
    from pearl_m_miner.cli import preflight
    from pearl_m_miner.validation import require_validated
    require_validated(ROOT, preflight())
    os.chdir(ROOT)
    for name in list(os.environ):
        if name.startswith('FUSION_'):
            del os.environ[name]
    os.environ.update(FUSION_PREFIX_GPU_PREPARE='1', FUSION_PREFIX_WORKERS='2',
        FUSION_OVERLAY_ROOT=str(ROOT/'tools/merkle_overlay'),
        FUSION_MERKLE_LIBRARY=str(ROOT/'tools/merkle_overlay/build/libm1merkleprobe_c.dylib'))
    import pearl_mining as pm
    from pearl_metal_miner import reference as ref
    from pearl_metal_miner.metal_capi import JobShape
    from pearl_metal_miner.stratum.kryptex import KryptexDialect
    from zero_b_factory import ZeroBFactory
    shape = JobShape(4096, 128, ref.Pattern.from_list([0, 32]), ref.Pattern.from_list(list(range(64))))
    header_bytes = ref.header_to_bytes(0x20000000, bytes(range(32)), bytes(range(32, 64)), 0x66661030, 0x207fffff)
    header = pm.IncompleteBlockHeader.from_bytes(header_bytes)
    factory = ZeroBFactory(noise_backend='metal')
    results = []
    try:
        grid = factory.prepare(shape, 16384, 65536, header_bytes, cert_version=3,
                               job_identity=(1, 'offline-gzip-proof'))
        dialect = KryptexDialect()
        dialect.handshake_lines('offline-public-test', 'offline')
        reply = dialect.parse(json.dumps({'id':3,'result':True,'error':None,'type':'v2'}))
        if not reply.accepted:
            raise AssertionError('v2 negotiation fixture refused')
        for index, (row, col) in enumerate(((0, 0), (31, 65472), (16320, 65472)), 11):
            proof = grid.craft_proof(row, col)
            ok, why = pm.verify_plain_proof_for_cert_version(3, header, proof, nbits_override=0x207fffff)
            if not ok:
                raise AssertionError('official original-proof verification failed: '+str(why))
            encoded = proof.to_base64()
            raw = base64.b64decode(encoded, validate=True)
            before = hashlib.sha256(raw).hexdigest()
            started = time.perf_counter()
            frame = dialect.submit_line(index, 'offline-public-test', 'offline', 'offline-gzip-proof', encoded)
            milliseconds = (time.perf_counter()-started)*1000
            packed_b64 = frame['params']['plain_proof']
            packed = base64.b64decode(packed_b64, validate=True)
            decoder = zlib.decompressobj(wbits=31)
            restored = decoder.decompress(packed) + decoder.flush()
            if not decoder.eof or decoder.unused_data or decoder.unconsumed_tail or restored != raw:
                raise AssertionError('gzip did not restore exactly one complete original proof')
            recovered = pm.PlainProof.from_base64(base64.b64encode(restored).decode('ascii'))
            ok, why = pm.verify_plain_proof_for_cert_version(3, header, recovered, nbits_override=0x207fffff)
            if not ok:
                raise AssertionError('official recovered-proof verification failed: '+str(why))
            results.append({'row':row,'column':col,'raw_bytes':len(raw),'gzip_bytes':len(packed),
                'raw_base64_bytes':len(encoded),'gzip_base64_bytes':len(packed_b64),
                'compression_ratio':len(raw)/len(packed),'encoding_ms':milliseconds,
                'original_sha256':before,'restored_sha256':hashlib.sha256(restored).hexdigest(),
                'original_official_verified':True,'recovered_official_verified':True})
    finally:
        factory.close()
    print('GZIP_OFFICIAL_PROOF_CHECK '+json.dumps({'passed':True,'m':16384,'n':65536,'k':4096,
        'rank':128,'cert_version':3,'results':results,'pool_submissions':0,
        'scope':'offline synthetic easy header; real production-dimension proof bytes; no pool acceptance claim'}),flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
