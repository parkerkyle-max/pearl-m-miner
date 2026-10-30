"""Opt-in, offline, sequential comparison with an explicitly pinned control.

Only this command starts the comparison. Imports and --plan do not touch native
code, wallets, the network, or the filesystem. Reports contain allowlisted data.
"""
from __future__ import annotations

import ctypes
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import re
import statistics
import subprocess
import sys
import time
import uuid

from . import __version__

SCHEMA = 'pearl-m-compare-v1'
UPSTREAM_COMMIT = '3d4cc7dadbd1de98ba20e9beb162806a0e70266b'
UPSTREAM_REPO = 'https://github.com/Breakwater-ecosystem/pearl-metal-miner'
WORK_PER_TILE = 524288
FAILURES = {
    'unsupported_or_unbuilt': 'Build the current source on Apple Silicon with sh bootstrap.sh, then retry.',
    'output_exists': 'Choose a new report directory; existing results are never overwritten.',
    'control_build_failed': 'The pinned reference build failed. Check the installed macOS command-line tools.',
    'power_unknown': 'AC power could not be confirmed. Resolve the power query before comparing.',
    'battery': 'The comparison requires AC power throughout. Reconnect and start a new comparison.',
    'thermal_unknown': 'The macOS thermal-pressure signal could not be read.',
    'thermal_pressure': 'Thermal pressure interrupted the comparison. Let the Mac cool before retrying.',
    'worker_timeout': 'A test exceeded its wall-time limit; no comparison is accepted.',
    'worker_failed': 'A calculation or proof check failed; no comparison is accepted.',
    'invalid_record': 'The worker returned missing, duplicate, inconsistent or invalid evidence.',
    'source_changed': 'Source or native files changed during the comparison.',
    'interrupted': 'The comparison was interrupted; incomplete results are not a speed claim.',
    'internal_error': 'The comparison could not complete. See the local console for diagnostics.',
}


class ComparisonError(RuntimeError):
    def __init__(self, code):
        self.code = code
        super().__init__(FAILURES.get(code, code))


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def trial_order(rounds):
    return [backend for pair in range(rounds)
            for backend in (('upstream', 'candidate') if pair % 2 == 0 else ('candidate', 'upstream'))]


def configuration(args):
    return {'m': args.m, 'n': args.n, 'k': 4096, 'rank': 128,
            'cert_version': 3, 'cpu_threads': args.cpu_threads,
            'region_rows': args.region_rows, 'seconds': args.seconds,
            'rounds': args.rounds, 'cooldown_seconds': args.cooldown,
            'intensity': 100, 'work_per_tile': WORK_PER_TILE,
            'order': trial_order(args.rounds)}


def plan(args):
    config = configuration(args)
    return {'schema': SCHEMA, 'mode': 'plan', 'configuration': config,
            'control': 'pearl-metal-miner 0.2.4 + disclosed cert3 compatibility',
            'upstream_commit': UPSTREAM_COMMIT,
            'timed_scan_seconds': args.seconds * args.rounds * 2,
            'additional_time': 'native control build, before/after correctness gates, warmup and cooldown',
            'starts_work': False, 'network_access': False, 'uploads': False,
            'scope': 'Fresh-work offline preparation and scan; excludes pool/network, hit-triggered proofs and income.'}


def reserve_output(path=None):
    target = Path(path).expanduser() if path else Path.cwd() / ('pearl-comparison-' + datetime.now().strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:8])
    # Refuse symlink parents as well as existing targets; never follow a report
    # path into a different directory or overwrite a previous participant result.
    absolute = target.absolute()
    if any(p.is_symlink() for p in (absolute, *absolute.parents)):
        raise ComparisonError('output_exists')
    try:
        absolute.mkdir(mode=0o700, parents=False, exist_ok=False)
    except FileExistsError as error:
        raise ComparisonError('output_exists') from error
    return absolute


def exclusive_write(path, text):
    with Path(path).open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(text)
        stream.flush()
        os.fsync(stream.fileno())


def numeric(value, *, positive=True):
    return type(value) in (int, float) and math.isfinite(value) and (value > 0 if positive else value >= 0)


def parse_benchmark(record, config):
    names = ('measured_seconds', 'measured_tiles', 'tiles_per_second',
             'difficulty_factor', 'equivalent_hashes_per_second', 'warmup_seconds_requested')
    if not isinstance(record, dict) or any(not numeric(record.get(k)) for k in names):
        raise ComparisonError('invalid_record')
    elapsed, tiles = record['measured_seconds'], record['measured_tiles']
    if type(tiles) is not int or record['difficulty_factor'] != WORK_PER_TILE:
        raise ComparisonError('invalid_record')
    # A worker may finish a region after its deadline. Large stalls invalidate
    # the requested comparable window rather than disappearing from the report.
    if not config['seconds'] <= elapsed <= config['seconds'] + max(10, config['seconds'] * .25):
        raise ComparisonError('invalid_record')
    rate = tiles / elapsed
    if not math.isclose(rate, record['tiles_per_second'], rel_tol=1e-6):
        raise ComparisonError('invalid_record')
    if not math.isclose(rate * WORK_PER_TILE, record['equivalent_hashes_per_second'], rel_tol=1e-6):
        raise ComparisonError('invalid_record')
    warmup = min(10.0, max(2.0, config['seconds'] / 5))
    if not math.isclose(record['warmup_seconds_requested'], warmup):
        raise ComparisonError('invalid_record')
    return {k: record[k] for k in names} | {'local_prl_ths': rate * WORK_PER_TILE / 1e12}


def validate_context(context, phase, config, expected_backend=None):
    if not isinstance(context, dict) or context.get('backend') not in ('upstream', 'candidate') or context.get('phase') != phase:
        raise ComparisonError('invalid_record')
    if expected_backend is not None and context['backend'] != expected_backend:
        raise ComparisonError('invalid_record')
    expected = {k: config[k] for k in ('m', 'n', 'k', 'rank', 'cpu_threads', 'region_rows', 'intensity')}
    expected.update(certificate_version=config['cert_version'], requested_seconds=config['seconds'])
    if any(type(context.get(k)) is not int or context[k] != value for k, value in expected.items()):
        raise ComparisonError('invalid_record')
    warmup = min(10.0, max(2.0, config['seconds'] / 5))
    header = hashlib.sha256(bytes(range(76))).hexdigest()
    if (context.get('warmup_seconds') != warmup or context.get('synthetic_header_sha256') != header
            or context.get('shared_matrix_values') is not False or context.get('network') != 'disabled'
            or context.get('wallet_access') != 'disabled'):
        raise ComparisonError('invalid_record')
    hashes = context.get('proof_extension_sha256')
    if (not isinstance(hashes, dict) or not hashes or len(hashes) > 10
            or any(not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,100}\.(?:so|pyd)', name)
                   or not re.fullmatch('[0-9a-f]{64}', str(digest)) for name, digest in hashes.items())):
        raise ComparisonError('invalid_record')
    return {'backend': context['backend'], 'phase': phase, **expected,
            'warmup_seconds': warmup, 'synthetic_header_sha256': header,
            'shared_matrix_values': False, 'proof_extension_sha256': dict(sorted(hashes.items())),
            'network': 'disabled', 'wallet_access': 'disabled'}


class Conditions:
    """The same independent parent-process checks apply to both backends."""
    def __init__(self, root):
        lib = ctypes.CDLL(str(root / 'tools/prefix_s_miner/libprefix.dylib'))
        lib.pfx_thermal_state.argtypes = []
        lib.pfx_thermal_state.restype = ctypes.c_int
        self._thermal = lib.pfx_thermal_state

    def __call__(self):
        try:
            result = subprocess.run(['pmset', '-g', 'batt'], capture_output=True, text=True, timeout=3)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise ComparisonError('power_unknown') from error
        if result.returncode:
            raise ComparisonError('power_unknown')
        if 'Battery Power' in result.stdout:
            raise ComparisonError('battery')
        if 'AC Power' not in result.stdout:
            raise ComparisonError('power_unknown')
        try:
            pressure = self._thermal()
        except (OSError, ValueError) as error:
            raise ComparisonError('thermal_unknown') from error
        if type(pressure) is not int or pressure not in (0, 1, 2, 3):
            raise ComparisonError('thermal_unknown')
        if pressure >= 2:
            raise ComparisonError('thermal_pressure')
        return {'power': 'ac', 'thermal_pressure': pressure}


def checked_condition(read_conditions):
    condition = read_conditions()
    if not isinstance(condition, dict) or condition.get('power') != 'ac':
        raise ComparisonError('power_unknown')
    if type(condition.get('thermal_pressure')) is not int or condition['thermal_pressure'] not in (0, 1):
        raise ComparisonError('thermal_pressure')
    return condition


def run_phase(command, *, phase, config, read_conditions, timeout,
              worker_factory=None, clock=time.monotonic, expected_backend=None):
    from .devfee import Worker
    worker_factory = worker_factory or Worker
    observations = [checked_condition(read_conditions)]
    records, gates, contexts = [], [], []
    invalid_signal = False
    def on_line(line):
        nonlocal invalid_signal
        if line.startswith('BENCHMARK_JSON '):
            if records:
                raise ComparisonError('invalid_record')
            records.append(json.loads(line.split(' ', 1)[1]))
        elif line.startswith('COMPARE_EVENT '):
            if gates:
                raise ComparisonError('invalid_record')
            gates.append(json.loads(line.split(' ', 1)[1]))
        elif line.startswith('COMPARE_CONTEXT '):
            if contexts:
                raise ComparisonError('invalid_record')
            contexts.append(json.loads(line.split(' ', 1)[1]))
        elif ('paused' in line.lower() or 'PMM_STATE' in line and 'thermal' in line.lower()):
            invalid_signal = True
        elif phase == 'build':
            print(line, flush=True)
    child = worker_factory(command, uuid.uuid4().hex)
    start, next_poll = clock(), clock()
    cleanup_error = None
    try:
        while True:
            now = clock()
            if now - start > timeout:
                raise ComparisonError('worker_timeout')
            if now >= next_poll:
                observations.append(checked_condition(read_conditions))
                next_poll = now + 2
            line = child.read(.1)
            if line is not None:
                on_line(line)
            if invalid_signal:
                raise ComparisonError('thermal_pressure')
            if child.poll() is not None and child.eof.is_set() and child.lines.empty():
                break
    except (json.JSONDecodeError, TypeError) as error:
        raise ComparisonError('invalid_record') from error
    finally:
        try:
            code = child.stop(on_line)
        except BaseException as error:
            cleanup_error = error
        if cleanup_error is not None:
            raise ComparisonError('worker_failed') from cleanup_error
    observations.append(checked_condition(read_conditions))
    if child.drain_error is not None or invalid_signal or code != 0:
        raise ComparisonError('worker_failed')
    context = None
    if phase != 'build':
        if len(contexts) != 1:
            raise ComparisonError('invalid_record')
        context = validate_context(contexts[0], phase, config, expected_backend)
    if phase == 'gate':
        if (len(gates) != 1 or not isinstance(gates[0], dict)
                or gates[0].get('phase') != 'gate' or gates[0].get('status') != 'passed'
                or gates[0].get('backend') != context['backend']
                or type(gates[0].get('official_proof_checks')) is not int
                or gates[0]['official_proof_checks'] <= 0 or records):
            raise ComparisonError('invalid_record')
        result = {'status': 'passed', 'official_proof_checks': gates[0]['official_proof_checks']}
    elif phase == 'build':
        if gates or records or contexts:
            raise ComparisonError('invalid_record')
        result = {'status': 'built'}
    else:
        if len(records) != 1 or gates:
            raise ComparisonError('invalid_record')
        result = parse_benchmark(records[0], config)
    return result | {'condition_samples': len(observations), 'max_thermal_pressure': max(o['thermal_pressure'] for o in observations),
                     'owned_process_reaped': True, **({'context': context} if context else {})}


def cooldown(seconds, read_conditions, *, sleep=time.sleep, clock=time.monotonic):
    deadline = clock() + seconds
    while clock() < deadline:
        checked_condition(read_conditions)
        sleep(min(2, max(0, deadline - clock())))
    checked_condition(read_conditions)


def source_identity(root):
    paths = set()
    for prefix in ('pearl_m_miner', 'pearl_metal_miner', 'tools/prefix_s_miner',
                   'tools/prefix_sparse_host', 'tools/merkle_overlay', 'csrc/metal',
                   'comparators/pearl-metal-miner'):
        for path in (root / prefix).rglob('*'):
            if (path.is_file() and '__pycache__' not in path.parts
                    and (path.suffix in ('.py', '.metal', '.mm', '.h', '.dylib', '.so')
                         or path.name in ('source-manifest.json', 'build-manifest.json'))):
                paths.add(path)
    for relative in ('PINNED_PEARL_COMMIT.txt', 'build/libpearlmetal.dylib', 'packaging/build_compare_control.py'):
        path = root / relative
        if path.is_file():
            paths.add(path)
    return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(paths)}


def git_identity(root):
    try:
        sha = subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'], stderr=subprocess.DEVNULL, text=True, timeout=5).strip()
        dirty = bool(subprocess.check_output(['git', '-C', str(root), 'status', '--porcelain', '--untracked-files=no'], stderr=subprocess.DEVNULL, text=True, timeout=5).strip())
        return (sha if re.fullmatch('[0-9a-f]{40}', sha) else None), dirty
    except (OSError, subprocess.SubprocessError):
        return None, None


def hardware(details):
    cores = None
    try:
        raw = subprocess.check_output(['system_profiler', 'SPDisplaysDataType', '-json'], timeout=10, stderr=subprocess.DEVNULL, text=True)
        for gpu in json.loads(raw).get('SPDisplaysDataType', []):
            if str(gpu.get('sppci_model', '')).startswith('Apple'):
                value = str(gpu.get('sppci_cores', gpu.get('spdisplays_cores', '')))
                if value.isdigit() and 1 <= int(value) <= 512:
                    cores = int(value)
    except (OSError, subprocess.SubprocessError, ValueError, TypeError):
        pass
    return {'chip': details['chip'], 'gpu_cores': cores,
            'memory_gib': details['memory_bytes'] / (1 << 30),
            'os': details['platform'], 'architecture': details['machine'],
            'python': platform.python_version()}


def aggregate(trials, config):
    if len(trials) != len(config['order']) or [t['backend'] for t in trials] != config['order']:
        raise ComparisonError('invalid_record')
    rates = {b: [t['local_prl_ths'] for t in trials if t['backend'] == b] for b in ('upstream', 'candidate')}
    if any(len(v) != config['rounds'] or any(not numeric(x) for x in v) for v in rates.values()):
        raise ComparisonError('invalid_record')
    medians = {b: statistics.median(v) for b, v in rates.items()}
    ratio = medians['candidate'] / medians['upstream']
    return {'aggregation': 'median of every completed run per backend; no best-run selection',
            'upstream_median_ths': medians['upstream'], 'candidate_median_ths': medians['candidate'],
            'ratio': ratio, 'improvement_percent': (ratio - 1) * 100,
            'repeat_range_percent': {b: (max(v) / min(v) - 1) * 100 for b, v in rates.items()},
            'review_status': 'self-reported; not independently hardware-verified'}


def build_control(root):
    try:
        run_phase([sys.executable, str(root / 'packaging/build_compare_control.py')],
                  phase='build', config={}, read_conditions=Conditions(root), timeout=240)
    except ComparisonError as error:
        if error.code in ('worker_failed', 'worker_timeout', 'invalid_record'):
            raise ComparisonError('control_build_failed') from error
        raise


def execute(args, root, *, preflight, phase_runner=run_phase, build=build_control,
            condition_factory=Conditions, identity=source_identity, cool=cooldown):
    if args.plan:
        print(json.dumps(plan(args), indent=2))
        return 0
    if not args.yes:
        if not sys.stdin.isatty():
            print('Run compare --plan to inspect the test, then use --yes for an unattended run.', file=sys.stderr)
            return 2
        print('This offline test builds the pinned reference and uses the GPU sequentially. '
              f'Timed scans: {2*args.rounds*args.seconds} seconds, plus proof checks, warmup and cooldown. '
              'Keep AC power connected and stop other GPU work. No wallet, pool, fee or upload is used.')
        if input('Run this comparison? [y/N] ').strip().lower() not in ('y', 'yes'):
            return 0
    output = reserve_output(args.output)
    config = configuration(args)
    report = {'schema': SCHEMA, 'report_id': uuid.uuid4().hex, 'created_utc': utc_now(),
              'status': 'running', 'review_status': 'community result; pending independent review',
              'configuration': config, 'hardware': None, 'software': None,
              'gates': [], 'trials': [], 'comparison': None, 'failure_code': None,
              'scope': 'Offline fresh preparation + completed scans. No pool/network or hit-triggered proof cost. No income or outlet-power claim.',
              'uploaded': False}
    result_code = 1
    try:
        try:
            details = preflight()
        except (RuntimeError, ValueError, OSError) as error:
            raise ComparisonError('unsupported_or_unbuilt') from error
        report['hardware'] = hardware(details)
        conditions = condition_factory(root)
        checked_condition(conditions)
        build(root)
        before = identity(root)
        sha, dirty = git_identity(root)
        report['software'] = {'version': __version__, 'commit': sha, 'tracked_changes': dirty,
            'upstream_repository': UPSTREAM_REPO, 'upstream_commit': UPSTREAM_COMMIT,
            'baseline': 'pearl-metal-miner 0.2.4 + cert3 compatibility; original pinned GPU kernels',
            'source_and_build_sha256': before}
        proof_identity = None
        def bind_result(value, backend, phase):
            nonlocal proof_identity
            context = validate_context(value.get('context'), phase, config, backend)
            if proof_identity is None:
                proof_identity = context['proof_extension_sha256']
            elif context['proof_extension_sha256'] != proof_identity:
                raise ComparisonError('source_changed')
            value['context'] = context
            return value
        def command(backend, phase):
            return [sys.executable, '-u', '-m', 'pearl_m_miner.compare_worker',
                    '--backend', backend, '--phase', phase, '--seconds', str(args.seconds),
                    '--m', str(args.m), '--n', str(args.n), '--cpu-threads', str(args.cpu_threads),
                    '--region-rows', str(args.region_rows)]
        for moment in ('before', 'after'):
            for backend in ('upstream', 'candidate'):
                print(f'Correctness gate: {backend} ({moment})', flush=True)
                gate = phase_runner(command(backend, 'gate'), phase='gate', config=config,
                                    read_conditions=conditions, timeout=900, expected_backend=backend)
                gate = bind_result(gate, backend, 'gate')
                report['gates'].append({'backend': backend, 'moment': moment, **gate})
            if moment == 'before':
                for index, backend in enumerate(config['order']):
                    print(f'Test {index+1}/{len(config["order"])}: {backend}, {args.seconds} measured seconds', flush=True)
                    cool(args.cooldown, conditions)
                    trial = phase_runner(command(backend, 'benchmark'), phase='benchmark', config=config,
                                         read_conditions=conditions, timeout=args.seconds + 180, expected_backend=backend)
                    trial = bind_result(trial, backend, 'benchmark')
                    report['trials'].append({'index': index + 1, 'backend': backend, **trial})
        if before != identity(root):
            raise ComparisonError('source_changed')
        report['comparison'] = aggregate(report['trials'], config)
        report['status'] = 'complete'
        result_code = 0
    except KeyboardInterrupt:
        report['status'], report['failure_code'] = 'interrupted', 'interrupted'
        result_code = 130
    except ComparisonError as error:
        report['status'], report['failure_code'] = 'failed', error.code
    except Exception as error:
        print('Comparison stopped locally: ' + type(error).__name__, file=sys.stderr)
        report['status'], report['failure_code'] = 'failed', 'internal_error'
    finally:
        report['completed_utc'] = utc_now()
        if report['status'] != 'complete':
            report['comparison'] = None
        from .comparison_share import render_report
        exclusive_write(output / 'report.json', json.dumps(report, indent=2, allow_nan=False) + '\n')
        exclusive_write(output / 'summary.md', render_report(report))
        # Persisted data must round-trip before advertising a ready report.
        if json.loads((output / 'report.json').read_text(encoding='utf-8')) != report:
            raise RuntimeError('Report readback mismatch')
        print(f'Report saved: {output / "report.json"}')
        if report['failure_code']:
            print(FAILURES.get(report['failure_code'], 'Comparison failed.'), file=sys.stderr)
        print('Nothing was uploaded. Review the report, then use pearl-m-miner share-report <report.json> --open.')
    return result_code
