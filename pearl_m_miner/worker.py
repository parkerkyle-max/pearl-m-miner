"""One payout identity per process; never launch this module on import."""
import json
import os
from pathlib import Path
import signal
import sys

ROOT = Path(__file__).resolve().parents[1]


def main(argv=None):
    rest = list(sys.argv[1:] if argv is None else argv)
    # Never inherit a private wallet/config or experimental selector accidentally.
    for name in list(os.environ):
        if name.startswith('FUSION_') or name in ('PRL_CONFIG', 'PRL_WALLET'):
            os.environ.pop(name, None)
    os.environ.update({
        'PRL_CONFIG': os.devnull,
        'FUSION_METAL_ZERO_B': '1',
        'FUSION_PREFIX_GPU_PREPARE': '1',
        'FUSION_PREFIX_PREPARE_METHOD': 's',
        'FUSION_PREFIX_WORKERS': '2',
        'FUSION_PREFIX_LIBRARY': str(ROOT/'tools/prefix_s_miner/libprefix.dylib'),
        'FUSION_PREFIX_SHADER': str(ROOT/'tools/prefix_s_miner/prefix.metal'),
        'FUSION_OVERLAY_ROOT': str(ROOT/'tools/merkle_overlay'),
        'FUSION_MERKLE_LIBRARY': str(ROOT/'tools/merkle_overlay/build/libm1merkleprobe_c.dylib'),
    })
    sys.path[:0] = [str(ROOT), str(ROOT/'tools/prefix_s_miner'), str(ROOT/'tools/prefix_sparse_host')]
    # The upstream module sets Rayon before importing its official extension.
    sys.argv = [sys.argv[0], *rest]
    from pearl_metal_miner import miner
    from prefix_adapter import close_prefix_engines, install_prefix_engine
    from zero_b_factory import close_factories, install_zero_b
    def interrupt(signum, frame):
        raise KeyboardInterrupt
    for signum in (signal.SIGTERM, getattr(signal,'SIGHUP',signal.SIGTERM)):
        signal.signal(signum,interrupt)
    install_zero_b(miner)
    install_prefix_engine(miner)
    try:
        return miner.run(rest)
    finally:
        try:
            print('PREFIX_FACTORY_STATS ' + json.dumps(close_factories()), flush=True)
        finally:
            close_prefix_engines()


if __name__ == '__main__':
    raise SystemExit(main())
