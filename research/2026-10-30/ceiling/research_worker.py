"""Bounded offline experiments only; no pool or payout configuration."""
import argparse
import json
import os
from pathlib import Path
import sys

p = argparse.ArgumentParser()
p.add_argument('--source', type=Path, required=True)
p.add_argument('--library', type=Path, required=True)
p.add_argument('--shader', type=Path, required=True)
p.add_argument('--seconds', type=int, default=45)
p.add_argument('--region-rows', type=int, default=512)
a = p.parse_args()
root = a.source.resolve()
for name in list(os.environ):
    if name.startswith(('FUSION_', 'PEARL_M_')) or name in ('PRL_CONFIG','PRL_WALLET'):
        os.environ.pop(name, None)
os.environ.update(PRL_CONFIG=os.devnull, FUSION_METAL_ZERO_B='1',
    FUSION_PREFIX_GPU_PREPARE='1', FUSION_PREFIX_PREPARE_METHOD='s',
    FUSION_PREFIX_WORKERS='2', RAYON_NUM_THREADS='2',
    FUSION_PREFIX_LIBRARY=str(a.library.resolve()),
    FUSION_PREFIX_SHADER=str(a.shader.resolve()),
    FUSION_OVERLAY_ROOT=str(root/'tools/merkle_overlay'),
    FUSION_MERKLE_LIBRARY=str(root/'tools/merkle_overlay/build/libm1merkleprobe_c.dylib'))
sys.path[:0] = [str(root),str(root/'tools/prefix_s_miner'),str(root/'tools/prefix_sparse_host')]
from pearl_metal_miner import miner
from prefix_adapter import install_prefix_engine, close_prefix_engines
from zero_b_factory import install_zero_b, close_factories
install_zero_b(miner)
install_prefix_engine(miner)
try:
    code = miner.run(['--benchmark','--benchmark-seconds',str(a.seconds),
        '--m','16384','--n','65536','--cpu-threads','2',
        '--region-rows',str(a.region_rows),'--no-notify','--no-dashboard'])
finally:
    try:
        print('PREFIX_FACTORY_STATS '+json.dumps(close_factories()),flush=True)
    finally:
        close_prefix_engines()
raise SystemExit(code)
