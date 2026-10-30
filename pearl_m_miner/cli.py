"""Portable command parser; native work only starts after explicit subcommands."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
from . import __version__

ROOT = Path(__file__).resolve().parents[1]
POOLS = {'luckypool': ('pearl-cpu-eu1.luckypool.io', 3370),
         'kryptex': ('prl-eu.kryptex.network', 7048)}


def bounded_int(low, high, step=1):
    def parse(value):
        result = int(value)
        if not low <= result <= high or result % step:
            raise argparse.ArgumentTypeError(f'must be {low}..{high}, a multiple of {step}')
        return result
    return parse


def build_parser():
    p = argparse.ArgumentParser(prog='pearl-m-miner', allow_abbrev=False,
        description='Experimental PRL miner for Apple Silicon / macOS 26+.')
    p.add_argument('--version', action='version', version=f'Pearl M Miner {__version__}')
    sub = p.add_subparsers(dest='command', required=True)
    info = sub.add_parser('info', help='offline capabilities and public developer payout; no mining')
    info.add_argument('--json', action='store_true', help='stable machine-readable public metadata')
    sub.add_parser('doctor', help='check platform and built artifacts; no mining')
    sub.add_parser('self-test', help='offline S preparation, transcript and official-proof gates')
    compare = sub.add_parser('compare', allow_abbrev=False,
        help='opt-in offline A/B test against pinned pearl-metal-miner; no upload')
    compare.add_argument('--against', choices=('pearl-metal-miner',), default='pearl-metal-miner')
    compare.add_argument('--seconds', type=bounded_int(60,600), default=60)
    compare.add_argument('--rounds', type=bounded_int(2,6), default=2)
    compare.add_argument('--cooldown', type=bounded_int(10,300), default=30)
    compare.add_argument('--m', type=bounded_int(64,16384,64), default=8192)
    compare.add_argument('--n', type=bounded_int(64,65536,64), default=16384)
    compare.add_argument('--cpu-threads', type=bounded_int(1,64), default=2)
    compare.add_argument('--region-rows', type=bounded_int(32,8192,32), default=512)
    compare.add_argument('--output', help='new report directory; must not already exist')
    compare.add_argument('--plan', action='store_true', help='print the plan without native work or file writes')
    compare.add_argument('--yes', action='store_true', help='explicitly accept the GPU test without an interactive prompt')
    share = sub.add_parser('share-report', allow_abbrev=False, help='review a comparison report; sharing is explicit')
    share.add_argument('report', help='path to report.json')
    action = share.add_mutually_exclusive_group()
    action.add_argument('--open', action='store_true', help='open an unsubmitted GitHub issue draft')
    action.add_argument('--submit', action='store_true', help='publish sanitized evidence using your authenticated GitHub CLI')
    for name in ('mine', 'benchmark'):
        q = sub.add_parser(name, allow_abbrev=False)
        q.add_argument('--profile', choices=('auto','conservative','max'), default='auto',
                       help='auto uses measured large shape only on M1 Max with 64 GiB RAM')
        q.add_argument('--m', type=bounded_int(64,16384,64))
        q.add_argument('--n', type=bounded_int(64,65536,64))
        q.add_argument('--cpu-threads', type=bounded_int(1,64), default=2)
        q.add_argument('--region-rows', type=bounded_int(32,8192,32), default=512)
        if name == 'benchmark':
            q.add_argument('--seconds', type=bounded_int(1,86400), default=60)
        else:
            q.add_argument('--pool', choices=tuple(POOLS), default='luckypool')
            q.add_argument('--address', required=True, help='native PRL address, or Kryptex krx mining ID')
            q.add_argument('--worker', default='pearl-m-miner')
            q.add_argument('--host', help='explicit pool hostname override')
            q.add_argument('--port', type=bounded_int(1,65535))
            q.add_argument('--intensity', type=bounded_int(1,100), default=100)
            q.add_argument('--on-battery', choices=('pause','low','full'), default='pause')
            q.add_argument('--keep-awake', action='store_true')
            q.add_argument('--time-limit', type=bounded_int(0,3150000000), default=0)
            q.add_argument('--dev-fee', type=int, choices=(0,1), default=1,
                           help='1%% of completed scan time by default; 0 disables')
    return p


def preflight():
    if platform.system() != 'Darwin' or platform.machine() != 'arm64':
        raise RuntimeError('native mining requires Apple Silicon macOS (arm64 Python; Rosetta unsupported)')
    version = platform.mac_ver()[0]
    if not version or int(version.split('.')[0]) < 26:
        raise RuntimeError('macOS 26+ / Metal 4 is required')
    artifacts = ('build/libpearlmetal.dylib', 'tools/prefix_s_miner/libprefix.dylib',
                 'tools/prefix_s_miner/prefix.metal',
                 'tools/merkle_overlay/build/libm1merkleprobe_c.dylib')
    missing = [item for item in artifacts if not (ROOT/item).is_file()]
    if missing:
        raise RuntimeError('run sh bootstrap.sh first; missing: ' + ', '.join(missing))
    chip = subprocess.check_output(['sysctl','-n','machdep.cpu.brand_string'],text=True).strip()
    memory = int(subprocess.check_output(['sysctl','-n','hw.memsize'],text=True).strip())
    if not chip.startswith('Apple ') or memory < 8*(1<<30):
        raise RuntimeError('an Apple Silicon Mac with at least 8 GiB RAM is required')
    return {'platform':'macOS '+version, 'machine':'arm64', 'version':__version__,
            'chip':chip, 'memory_bytes':memory,
            'backend':'prefix-s', 'hardware_validation':'M1 Max measured; other M chips experimental',
            'artifacts':list(artifacts), 'thermal':'public macOS thermal pressure; pauses at serious/critical'}


def apply_profile(args, details):
    large = args.profile == 'max' or (args.profile == 'auto' and
        details['chip'] == 'Apple M1 Max' and details['memory_bytes'] >= 64*(1<<30))
    defaults = (16384,65536) if large else (8192,16384)
    args.m = args.m if args.m is not None else defaults[0]
    args.n = args.n if args.n is not None else defaults[1]


def validate_identity(args):
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', args.worker):
        raise ValueError('worker must contain 1..64 ASCII letters, digits, _ or -')
    if args.host and (any(c.isspace() for c in args.host) or '/' in args.host):
        raise ValueError('host must be a hostname or IP without scheme/path/whitespace')
    if args.pool == 'kryptex' and re.fullmatch(r'krx[A-Za-z0-9]{4,64}', args.address):
        return
    from pearl_metal_miner.wallet import validate_payout_address
    args.address = validate_payout_address(args.address)


def build_worker_command(args, address, worker, role):
    if role not in ('user','dev'):
        raise ValueError('unknown payout role')
    pool = 'luckypool' if role == 'dev' else args.pool
    host, port = POOLS[pool]
    if role == 'user':
        host, port = args.host or host, args.port or port
    command = [sys.executable, '-u', '-m', 'pearl_m_miner.worker', '--pool',pool,
        '--host',host,'--port',str(port),'--address',address,'--worker',worker,
        '--m',str(args.m),'--n',str(args.n),'--cpu-threads',str(args.cpu_threads),
        '--region-rows',str(args.region_rows),'--intensity',str(args.intensity),
        '--on-battery',args.on_battery,'--no-notify','--no-dashboard']
    if args.keep_awake:
        command.append('--keep-awake')
    return command


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == 'compare':
            from .comparison import execute
            return execute(args, ROOT, preflight=preflight)
        if args.command == 'share-report':
            from .comparison_share import share
            return share(args.report, open_browser=args.open, submit=args.submit)
        if args.command == 'info':
            from .discovery import manifest
            value = manifest()
            if args.json:
                print(json.dumps(value, indent=2))
            else:
                fee = value['developer_contribution']
                print(f"Pearl M-Miner {value['version']} | PRL | Apple Silicon Metal GPU")
                print('Requires macOS 26+, native arm64 Python 3.12+, Metal 4 tools and Rust/Cargo.')
                print('M1 Max measured; other M-series devices are experimental.')
                print('Optional 1% of completed valid GPU scan time; disable with --dev-fee 0.')
                print('Developer public PRL address: ' + fee['public_address'])
                print(f"Developer route: {fee['pool']} {fee['host']}:{fee['port']}")
                print('Your mining payout uses your separate --address identity. No secrets are needed.')
                print('This command is offline and does not start mining. Use info --json for metadata.')
            return 0
        if args.command == 'mine':
            validate_identity(args)
        details = preflight()
        if args.command == 'doctor':
            print(json.dumps(details,indent=2));return 0
        if args.command in ('mine','benchmark'):
            apply_profile(args,details)
        # Source-only release: bootstrap installs editable, not a relocatable wheel.
        os.chdir(ROOT)
        from .validation import require_validated, run_gate
        if args.command == 'self-test':
            return run_gate(ROOT,details)
        require_validated(ROOT,details)
        if args.command == 'benchmark':
            from .worker import main as run_worker
            return run_worker(['--benchmark','--benchmark-seconds',str(args.seconds),
                '--m',str(args.m),'--n',str(args.n),'--cpu-threads',str(args.cpu_threads),
                '--region-rows',str(args.region_rows),'--no-notify','--no-dashboard'])
        from .devfee import run_with_devfee
        os.environ['PEARL_M_ACTIVITY']='1'
        return run_with_devfee(lambda address,worker,role:build_worker_command(args,address,worker,role),
            coin='PRL',user_address=args.address,user_worker=args.worker,
            fee_percent=float(args.dev_fee),time_limit=args.time_limit or None)
    except (RuntimeError, ValueError, OSError) as error:
        print('pearl-m-miner: '+str(error),file=sys.stderr);return 1
    except KeyboardInterrupt:
        return 130


if __name__ == '__main__':
    raise SystemExit(main())
