"""One isolated, offline phase of the explicitly requested comparison run."""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib.abc
import importlib.util
import json
import os
from pathlib import Path
import platform
import signal
import sys

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / 'comparators/pearl-metal-miner'
RUNTIME = VENDOR / 'build/runtime'
_GUARDS_INSTALLED = False
_GATE_BOOTSTRAP = (
    'import sys, runpy; from pathlib import Path; '
    'from pearl_m_miner.compare_worker import install_offline_guards; '
    'install_offline_guards(); '
    'sys.argv = sys.argv[1:]; '
    'sys.path.insert(0, str(Path(sys.argv[0]).resolve().parent)); '
    'runpy.run_path(sys.argv[0], run_name="__main__")'
)


def install_offline_guards() -> None:
    """Fail on socket operations and the known wallet-file paths, including imports."""
    global _GUARDS_INSTALLED
    if _GUARDS_INSTALLED:
        return

    def audit(event, args):
        # platform.uname() may ask for the local hostname; that query opens no
        # socket. All socket construction, DNS, bind and connection events fail.
        if event.startswith('socket.') and event != 'socket.gethostname':
            raise RuntimeError('network access is disabled in an offline comparison worker')
        if event == 'open' and args and isinstance(args[0], (str, bytes, os.PathLike)):
            name = os.path.basename(os.fsdecode(args[0])).lower()
            if name in ('wallet.json', 'burner_wallet.json', 'wallet.dat'):
                raise RuntimeError('wallet file access is disabled in an offline comparison worker')

    sys.addaudithook(audit)
    sys.dont_write_bytecode = True
    _GUARDS_INSTALLED = True


def clean_environment(cpu_threads: int) -> None:
    for name in list(os.environ):
        if (name.startswith('FUSION_') or name.startswith('PEARL_M_')
                or name in ('PRL_CONFIG', 'PRL_WALLET', 'PYTHONPATH', 'PYTHONHOME')):
            os.environ.pop(name, None)
    os.environ['PRL_CONFIG'] = os.devnull
    os.environ['RAYON_NUM_THREADS'] = str(cpu_threads)
    os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
    # Avoid an inherited numerical-library pool silently changing the host budget.
    for name in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS',
                 'VECLIB_MAXIMUM_THREADS', 'NUMEXPR_NUM_THREADS'):
        os.environ[name] = str(cpu_threads)


def _deny_wallet(*args, **kwargs):
    raise RuntimeError('wallet discovery and access are disabled during comparison')


def disable_wallet_functions() -> None:
    # Importing this pinned module only defines constants/functions. The wallet
    # filesystem calls are confined to functions we do not invoke and disable.
    from pearl_metal_miner import wallet
    for name in ('find_wallet_file', 'load_wallet', 'create_wallet', 'verify_wallet',
                 'default_wallet_path', 'resolve_payout', 'configured_payout'):
        if hasattr(wallet, name):
            setattr(wallet, name, _deny_wallet)


def load_builder():
    path = ROOT / 'packaging/build_compare_control.py'
    spec = importlib.util.spec_from_file_location('_pearl_comparison_build', path)
    if spec is None or spec.loader is None:
        raise RuntimeError('cannot load the comparison source verifier')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class VerifiedSourceLoader(importlib.abc.SourceLoader):
    """Compile the checked source bytes directly; never consult a .pyc cache."""
    def __init__(self, fullname: str, path: Path, expected_sha256: str):
        self.fullname = fullname
        self.path = Path(path)
        self.expected_sha256 = expected_sha256

    def get_filename(self, fullname):
        if fullname != self.fullname:
            raise ImportError('comparison source loader module identity differs')
        return str(self.path)

    def get_data(self, path):
        requested = Path(path)
        if requested != self.path or requested.is_symlink():
            raise ImportError('comparison source loader refuses non-source input')
        data = requested.read_bytes()
        if hashlib.sha256(data).hexdigest() != self.expected_sha256:
            raise ImportError('comparison source changed before import: ' + self.fullname)
        return data

    def get_code(self, fullname):
        filename = self.get_filename(fullname)
        return self.source_to_code(self.get_data(filename), filename)


class UpstreamSourceFinder(importlib.abc.MetaPathFinder):
    """Resolve only pinned Python files inside the control's package namespace."""
    def __init__(self, runtime: Path, expected_files: dict[str, str]):
        self.runtime = Path(runtime).resolve()
        self.expected_files = dict(expected_files)

    def find_spec(self, fullname, path=None, target=None):
        if fullname != 'pearl_metal_miner' and not fullname.startswith('pearl_metal_miner.'):
            return None
        base = fullname.replace('.', '/')
        candidates = [base + '.py', base + '/__init__.py']
        present = [name for name in candidates if name in self.expected_files]
        if len(present) != 1:
            raise ModuleNotFoundError('module is absent from the pinned comparison source: ' + fullname)
        name = present[0]
        filename = self.runtime / name
        if not filename.resolve().is_relative_to(self.runtime):
            raise ImportError('comparison module escaped the pinned runtime')
        loader = VerifiedSourceLoader(fullname, filename, self.expected_files[name])
        return importlib.util.spec_from_file_location(
            fullname, filename, loader=loader,
            submodule_search_locations=[str(filename.parent)]
            if name.endswith('/__init__.py') else None,
        )


def install_upstream_source_loader(runtime: Path, expected_files: dict[str, str]):
    finder = UpstreamSourceFinder(runtime, expected_files)
    sys.meta_path.insert(0, finder)
    return finder


def _check_runtime_imports(expected: Path, *, require_verified_source: bool = False) -> None:
    expected = expected.resolve()
    for name, module in tuple(sys.modules.items()):
        if name == 'pearl_metal_miner' or name.startswith('pearl_metal_miner.'):
            filename = getattr(module, '__file__', None)
            if not filename or not Path(filename).resolve().is_relative_to(expected):
                raise RuntimeError('comparison imported a miner from the wrong source tree: ' + name)
            if require_verified_source and not isinstance(
                    getattr(getattr(module, '__spec__', None), 'loader', None), VerifiedSourceLoader):
                raise RuntimeError('comparison module was not loaded from checked source: ' + name)


def proof_extension_identity() -> dict:
    """Record actual shared verifier bytes, without exposing installation paths."""
    import pearl_mining
    folder = Path(pearl_mining.__file__).resolve().parent
    libraries = sorted(folder.glob('*.so')) + sorted(folder.glob('*.pyd'))
    if not libraries:
        raise RuntimeError('the official native proof extension is missing')
    return {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in libraries}


def _require_platform() -> None:
    if platform.system() != 'Darwin' or platform.machine() != 'arm64':
        raise RuntimeError('offline GPU comparison requires native arm64 macOS')
    version = platform.mac_ver()[0]
    if not version or int(version.split('.')[0]) < 26:
        raise RuntimeError('offline GPU comparison requires macOS 26 or newer')


def _emit_gate(backend: str, checks: int, **values) -> None:
    if type(checks) is not int or checks <= 0:
        raise RuntimeError('no completed official proof checks to report')
    print('COMPARE_EVENT ' + json.dumps({
        'phase': 'gate', 'status': 'passed', 'backend': backend,
        'official_proof_checks': checks, **values,
    }, sort_keys=True), flush=True)


def run_upstream_gate() -> dict:
    """Run the pinned arithmetic/proof checks explicitly; never run test_wallet."""
    import numpy as np
    from pearl_metal_miner import selftest

    disable_wallet_functions()
    # Fail loudly if future dispatch accidentally tries to add the wallet stage.
    selftest.test_wallet = _deny_wallet
    selftest.CHECKS.clear()
    selftest.CHECKS.update({'pass': 0, 'fail': 0})
    original_check = selftest._check
    proof_labels = {
        'cert3 e2e: Metal-found win → PlainProof → upstream Rust verifier accepts at share-difficulty override',
        'cert3 e2e: explicit official V3 verifier agrees',
        'cert3 e2e: changed declared m with unchanged Merkle tree is rejected',
    }
    completed_proof_labels = set()

    def checked(name, ok, detail=''):
        original_check(name, ok, detail)
        if not ok:
            raise RuntimeError('upstream comparison correctness gate failed: ' + name)
        if name in proof_labels:
            completed_proof_labels.add(name)

    selftest._check = checked
    metal = None
    try:
        rng = np.random.default_rng(0)
        selftest.test_seed_derivation()
        metal = selftest.Metal()
        shape, _, _ = selftest._job(selftest.SHAPES[0])
        metal.compile(shape)
        selftest.test_blake3(metal, rng)
        selftest.test_noise(metal, shape, rows=128, rng=rng)
        for item in selftest.SHAPES:
            selftest.test_pow(metal, item, rng)
        selftest.test_pow_v2(metal, rng)
        selftest.test_end_to_end(metal, rng, cert_version=3)
        if (selftest.CHECKS['fail'] or not selftest.CHECKS['pass']
                or completed_proof_labels != proof_labels):
            raise RuntimeError('the complete upstream cert3 proof gate did not finish')
        return {'official_proof_checks': len(completed_proof_labels),
                'arithmetic_checks': selftest.CHECKS['pass'],
                'wallet_stage': 'excluded',
                'scope': 'Offline exact arithmetic, blocked GPU path and official cert3 accept/reject checks.'}
    finally:
        selftest._check = original_check
        if metal is not None and getattr(metal, '_ctx', None):
            metal._lib.pm_destroy(metal._ctx)
            metal._ctx = None


@contextlib.contextmanager
def guarded_candidate_gate_child(validation):
    """Carry the same offline guard into run_gate's owned native-check child."""
    original_popen = validation.subprocess.Popen
    expected_script = ROOT / 'tools/prefix_s_miner/check_sparse_native.py'

    def guarded_popen(command, *args, **kwargs):
        if (not isinstance(command, (list, tuple)) or len(command) < 3
                or Path(command[0]).resolve() != Path(sys.executable).resolve()
                or command[1] != '-u' or Path(command[2]).resolve() != expected_script.resolve()):
            raise RuntimeError('unexpected child command in comparison correctness gate')
        wrapped = [command[0], '-u', '-c', _GATE_BOOTSTRAP, *command[2:]]
        return original_popen(wrapped, *args, **kwargs)

    validation.subprocess.Popen = guarded_popen
    try:
        yield
    finally:
        validation.subprocess.Popen = original_popen


def run_candidate_gate() -> dict:
    from .cli import preflight
    from . import validation

    details = preflight()
    before = validation.identity(ROOT, details)
    with guarded_candidate_gate_child(validation):
        code = validation.run_gate(ROOT, details)
    if code:
        raise RuntimeError('candidate official-proof gate failed')
    validation.require_validated(ROOT, details)
    receipt = json.loads((ROOT / 'build/self-test.json').read_text())
    if receipt.get('identity') != before or validation.identity(ROOT, details) != before:
        raise RuntimeError('candidate build changed during the correctness gate')
    count = receipt.get('official_proof_checks')
    if type(count) is not int or count <= 0:
        raise RuntimeError('candidate gate did not record actual official proof checks')
    return {'official_proof_checks': count,
            'scope': receipt['scope'], 'wallet_stage': 'excluded'}


def _benchmark_args(args) -> list[str]:
    return ['--benchmark', '--benchmark-seconds', str(args.seconds),
            '--m', str(args.m), '--n', str(args.n),
            '--cpu-threads', str(args.cpu_threads),
            '--region-rows', str(args.region_rows), '--no-notify', '--no-dashboard']


def run_upstream_benchmark(args) -> int:
    from pearl_metal_miner import miner, benchmark
    disable_wallet_functions()
    # Parsing explicit arguments does not load user configuration. Calling the
    # offline function directly avoids wallet/config/live-mining dispatch.
    parser = miner.build_parser()
    parsed = parser.parse_args(_benchmark_args(args))
    shape = miner._shape_from_args(parsed, parser)
    if (shape.k, shape.r, shape.rows_pattern.to_list(), shape.cols_pattern.to_list()) != (
            4096, 128, [0, 32], list(range(64))):
        raise RuntimeError('upstream comparison job shape differs from the fixed protocol shape')
    if (benchmark._SyntheticJob.header_bytes != bytes(range(76))
            or benchmark._SyntheticJob.cert_version != 3):
        raise RuntimeError('upstream comparison fixture changed')
    return benchmark.run(parsed, shape)


def run_candidate_benchmark(args) -> int:
    from .worker import main as run_worker
    disable_wallet_functions()
    from pearl_metal_miner import benchmark
    if (benchmark._SyntheticJob.header_bytes != bytes(range(76))
            or benchmark._SyntheticJob.cert_version != 3):
        raise RuntimeError('candidate comparison fixture changed')
    return run_worker(_benchmark_args(args), prefix_workers=args.cpu_threads)


def _bounded_integer(low: int, high: int, multiple: int = 1):
    def parse(value):
        number = int(value)
        if not low <= number <= high or number % multiple:
            raise argparse.ArgumentTypeError(f'expected {low}..{high}, multiple of {multiple}')
        return number
    return parse


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--backend', choices=('upstream', 'candidate'), required=True)
    parser.add_argument('--phase', choices=('gate', 'benchmark'), required=True)
    parser.add_argument('--seconds', type=_bounded_integer(1, 86400), default=60)
    parser.add_argument('--m', type=_bounded_integer(64, 16384, 64), default=8192)
    parser.add_argument('--n', type=_bounded_integer(64, 65536, 64), default=16384)
    parser.add_argument('--cpu-threads', type=_bounded_integer(1, 64), default=2)
    parser.add_argument('--region-rows', type=_bounded_integer(32, 8192, 32), default=512)
    args = parser.parse_args(argv)
    try:
        clean_environment(args.cpu_threads)
        install_offline_guards()
        _require_platform()

        def interrupted(signum, frame):
            raise KeyboardInterrupt
        for signum in (signal.SIGTERM, getattr(signal, 'SIGHUP', signal.SIGTERM)):
            signal.signal(signum, interrupted)

        builder = load_builder()
        build_identity = None
        if args.backend == 'upstream':
            build_identity = builder.verify_build(ROOT)
            if build_identity.get('macos') != platform.mac_ver()[0]:
                raise RuntimeError('comparison control was built for another macOS version; rebuild it')
            _check_runtime_imports(RUNTIME, require_verified_source=True)
            install_upstream_source_loader(RUNTIME, build_identity['runtime_files_sha256'])
            sys.path.insert(0, str(RUNTIME))
            os.chdir(RUNTIME)
        else:
            _check_runtime_imports(ROOT / 'pearl_metal_miner')
            os.chdir(ROOT)
        before_proof = proof_extension_identity()
        print('COMPARE_CONTEXT ' + json.dumps({
            'backend': args.backend, 'phase': args.phase, 'certificate_version': 3,
            'm': args.m, 'n': args.n, 'k': 4096, 'rank': 128,
            'cpu_threads': args.cpu_threads, 'region_rows': args.region_rows,
            'intensity': 100, 'requested_seconds': args.seconds,
            'warmup_seconds': min(10.0, max(2.0, args.seconds / 5)),
            'synthetic_header_sha256': hashlib.sha256(bytes(range(76))).hexdigest(),
            'shared_matrix_values': False,
            'proof_extension_sha256': before_proof,
            'network': 'disabled', 'wallet_access': 'disabled',
            'conditions': 'Parent supervisor independently monitors AC and thermal pressure for both backends.',
            'scope': 'Fresh preparation and returned scans; excludes pool, network and hit-triggered proof construction.',
        }, sort_keys=True), flush=True)
        if args.phase == 'gate':
            result = run_upstream_gate() if args.backend == 'upstream' else run_candidate_gate()
            code = 0
        else:
            result = None
            code = run_upstream_benchmark(args) if args.backend == 'upstream' else run_candidate_benchmark(args)
        if code:
            raise RuntimeError('comparison phase did not complete successfully')
        _check_runtime_imports(
            RUNTIME if args.backend == 'upstream' else ROOT / 'pearl_metal_miner',
            require_verified_source=args.backend == 'upstream',
        )
        if proof_extension_identity() != before_proof:
            raise RuntimeError('official proof extension changed during comparison')
        if build_identity is not None and builder.verify_build(ROOT) != build_identity:
            raise RuntimeError('upstream source or native build changed during comparison')
        if result is not None:
            checks = result.pop('official_proof_checks')
            _emit_gate(args.backend, checks, proof_extension_sha256=before_proof, **result)
        return 0
    except KeyboardInterrupt:
        print('comparison worker interrupted; this phase is incomplete', file=sys.stderr)
        return 130
    except Exception as error:
        print('comparison worker failed: ' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
