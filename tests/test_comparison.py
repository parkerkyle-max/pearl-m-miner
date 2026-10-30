"""CPU-only comparison acceptance, process cleanup, and explicit-sharing checks.

Synthetic records exercise the supervisor and report contract. These tests do
not claim that either native Metal backend builds, is correct, or is faster.
"""
import contextlib
import copy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import py_compile
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from pearl_m_miner import cli, comparison as c, comparison_share as sharing
from pearl_m_miner import compare_worker


def arguments(output=None):
    argv = ['compare', '--yes', '--seconds', '60', '--rounds', '2', '--cooldown', '10']
    if output is not None:
        argv += ['--output', str(output)]
    return cli.build_parser().parse_args(argv)


def sample_record(multiplier=1):
    tiles = 6_000_000 * multiplier
    rate = tiles / 60
    return {'measured_seconds': 60.0, 'measured_tiles': tiles,
            'tiles_per_second': rate, 'difficulty_factor': 524288,
            'equivalent_hashes_per_second': rate * 524288,
            'warmup_seconds_requested': 10.0}


def context_record(backend='candidate', phase='benchmark'):
    return {'backend': backend, 'phase': phase, 'certificate_version': 3,
            'm': 8192, 'n': 16384, 'k': 4096, 'rank': 128,
            'cpu_threads': 2, 'region_rows': 512, 'intensity': 100,
            'requested_seconds': 60, 'warmup_seconds': 10.0,
            'synthetic_header_sha256': hashlib.sha256(bytes(range(76))).hexdigest(),
            'shared_matrix_values': False,
            'proof_extension_sha256': {'_native.cpython-312-darwin.so': 'c' * 64},
            'network': 'disabled', 'wallet_access': 'disabled',
            'conditions': 'Parent supervisor independently monitors AC and thermal pressure for both backends.',
            'scope': 'Fresh preparation and returned scans; excludes pool, network and hit-triggered proof construction.'}


def finished_trial(multiplier=1, *, backend='candidate'):
    record = sample_record(multiplier)
    return record | {'local_prl_ths': record['equivalent_hashes_per_second'] / 1e12,
                     'condition_samples': 3, 'max_thermal_pressure': 0,
                     'owned_process_reaped': True, 'context': context_record(backend)}


def finished_gate(*, backend='candidate'):
    return {'status': 'passed', 'official_proof_checks': 4,
            'condition_samples': 3, 'max_thermal_pressure': 0,
            'owned_process_reaped': True, 'context': context_record(backend, 'gate')}


HARDWARE = {'chip': 'Apple M2', 'gpu_cores': 10, 'memory_gib': 24,
            'os': 'macOS 27.0', 'architecture': 'arm64', 'python': '3.12.8'}
DETAILS = {'chip': 'Apple M2', 'memory_bytes': 24 * (1 << 30),
           'platform': 'macOS 27.0', 'machine': 'arm64'}
FINGERPRINT = {'pearl_m_miner/cli.py': 'a' * 64}


def complete_report():
    config = c.configuration(arguments())
    trials = [finished_trial(multiplier, backend=backend) | {'index': index + 1, 'backend': backend}
              for index, (backend, multiplier) in enumerate(zip(
                  ['upstream', 'candidate', 'candidate', 'upstream'], [10, 30, 42, 14]))]
    upstream = (trials[0]['local_prl_ths'] + trials[3]['local_prl_ths']) / 2
    candidate = (trials[1]['local_prl_ths'] + trials[2]['local_prl_ths']) / 2
    ratio = candidate / upstream
    comparison = {'aggregation': 'median of every completed run per backend; no best-run selection',
                  'upstream_median_ths': upstream, 'candidate_median_ths': candidate,
                  'ratio': ratio, 'improvement_percent': (ratio - 1) * 100,
                  'repeat_range_percent': {
                      'upstream': (trials[3]['local_prl_ths'] / trials[0]['local_prl_ths'] - 1) * 100,
                      'candidate': (trials[2]['local_prl_ths'] / trials[1]['local_prl_ths'] - 1) * 100},
                  'review_status': 'self-reported; not independently hardware-verified'}
    return {'schema': c.SCHEMA, 'report_id': '1' * 32,
            'created_utc': '2026-10-30T20:00:00+00:00',
            'completed_utc': '2026-10-30T20:10:00+00:00',
            'status': 'complete', 'configuration': config,
            'hardware': copy.deepcopy(HARDWARE),
            'software': {'version': '0.1.0a3', 'commit': 'b' * 40, 'tracked_changes': False,
                         'upstream_repository': c.UPSTREAM_REPO, 'upstream_commit': c.UPSTREAM_COMMIT,
                         'source_and_build_sha256': copy.deepcopy(FINGERPRINT)},
            'gates': [finished_gate(backend=backend) | {'backend': backend, 'moment': moment}
                      for moment in ('before', 'after') for backend in ('upstream', 'candidate')],
            'trials': trials, 'comparison': comparison, 'failure_code': None, 'uploaded': False}


class RecordAcceptanceTests(unittest.TestCase):
    def test_rate_is_derived_from_work_and_time_and_extra_fields_do_not_escape(self):
        record = sample_record(2) | {'private_key': 'do-not-copy', 'local_path': '/Users/alice/private'}
        result = c.parse_benchmark(record, c.configuration(arguments()))
        self.assertAlmostEqual(result['local_prl_ths'], .1048576)
        self.assertNotIn('private_key', result)
        self.assertNotIn('local_path', result)

    def test_inconsistent_or_nonfinite_evidence_is_rejected(self):
        bad_values = [None, [], {},
                      sample_record() | {'measured_seconds': 59},
                      sample_record() | {'measured_seconds': 90},
                      sample_record() | {'measured_tiles': True},
                      sample_record() | {'measured_tiles': 6_000_000.0},
                      sample_record() | {'equivalent_hashes_per_second': float('nan')},
                      sample_record() | {'tiles_per_second': float('inf')},
                      sample_record() | {'difficulty_factor': 1},
                      sample_record() | {'tiles_per_second': 9},
                      sample_record() | {'warmup_seconds_requested': 2}]
        for record in bad_values:
            with self.subTest(record=record), self.assertRaises(c.ComparisonError) as error:
                c.parse_benchmark(record, c.configuration(arguments()))
            self.assertEqual(error.exception.code, 'invalid_record')

    def test_all_runs_affect_result_and_slowdown_is_retained(self):
        report = complete_report()
        for trial, multiplier in zip(report['trials'], [10, 3, 9, 14]):
            trial.update(finished_trial(multiplier))
        result = c.aggregate(report['trials'], report['configuration'])
        self.assertAlmostEqual(result['ratio'], .5)
        self.assertAlmostEqual(result['improvement_percent'], -50)
        for trials in (report['trials'][:-1], report['trials'][1:] + report['trials'][:1]):
            with self.assertRaises(c.ComparisonError):
                c.aggregate(trials, report['configuration'])

    def test_public_report_rejects_tampered_gain_incomplete_gates_and_failed_gain(self):
        changes = [lambda r: r['comparison'].update(ratio=999),
                   lambda r: r['gates'].pop(),
                   lambda r: r['gates'][0].update(official_proof_checks=0),
                   lambda r: r['gates'][0].update(owned_process_reaped=False),
                   lambda r: r['trials'][0].update(owned_process_reaped=False),
                   lambda r: r.update(status='failed', failure_code='worker_failed')]
        for change in changes:
            report = complete_report(); change(report)
            with self.subTest(change=change), self.assertRaises((ValueError, c.ComparisonError)):
                sharing.public_report(report)


class RealPhaseTests(unittest.TestCase):
    """Actual local Python child processes; no GPU, wallet, network or pool."""
    def run_child(self, source, *, phase='benchmark', conditions=None, timeout=4, contexts=None):
        from pearl_m_miner import devfee
        children = []
        def factory(command, session):
            child = devfee.Worker(command, session)
            children.append(child)
            return child
        contexts = [context_record(phase=phase)] if contexts is None else contexts
        source = '\n'.join('print(' + repr('COMPARE_CONTEXT ' + json.dumps(record)) + ',flush=True)'
                           for record in contexts) + '\n' + source
        try:
            with patch.object(devfee, 'STOP_GRACE_SECONDS', .15):
                return c.run_phase([sys.executable, '-u', '-c', source], phase=phase,
                    config=c.configuration(arguments()),
                    read_conditions=conditions or (lambda: {'power': 'ac', 'thermal_pressure': 0}),
                    timeout=timeout, worker_factory=factory, expected_backend='candidate')
        finally:
            for child in children:
                # Recover the test child even when an assertion detects a cleanup defect.
                try:
                    self.assertIsNotNone(child.poll(), 'supervisor left its process alive')
                    self.assertFalse(child.reader.is_alive(), 'output drain thread remained alive')
                finally:
                    if child.poll() is None:
                        with patch.object(devfee, 'STOP_GRACE_SECONDS', .1):
                            child.stop(lambda line: None)

    @staticmethod
    def print_record(record):
        return 'print(' + repr('BENCHMARK_JSON ' + json.dumps(record)) + ',flush=True)'

    def test_completed_process_with_one_valid_record(self):
        result = self.run_child(self.print_record(sample_record()))
        self.assertTrue(result['owned_process_reaped'])
        self.assertEqual(result['measured_tiles'], 6_000_000)

    def test_nan_duplicate_missing_and_nonzero_outputs_are_not_accepted(self):
        good = self.print_record(sample_record())
        cases = [(self.print_record(sample_record() | {'tiles_per_second': float('nan')}), 'invalid_record'),
                 (good + '\n' + good, 'invalid_record'),
                 ('print("no benchmark evidence",flush=True)', 'invalid_record'),
                 ('print("BENCHMARK_JSON {bad",flush=True)', 'invalid_record'),
                 (good + '\nraise SystemExit(7)', 'worker_failed')]
        for source, code in cases:
            with self.subTest(code=code, source=source), self.assertRaises(c.ComparisonError) as error:
                self.run_child(source)
            self.assertEqual(error.exception.code, code)

    def test_timeout_reaps_hanging_process(self):
        with self.assertRaises(c.ComparisonError) as error:
            self.run_child('import time; time.sleep(30)', timeout=.15)
        self.assertEqual(error.exception.code, 'worker_timeout')

    def test_keyboard_interrupt_during_monitoring_reaps_process(self):
        calls = []
        def conditions():
            calls.append(1)
            if len(calls) > 1:
                raise KeyboardInterrupt
            return {'power': 'ac', 'thermal_pressure': 0}
        with self.assertRaises(KeyboardInterrupt):
            self.run_child('import time; time.sleep(30)', conditions=conditions)

    def test_pause_signal_invalidates_and_stops_worker(self):
        with self.assertRaises(c.ComparisonError) as error:
            self.run_child('import time; print("benchmark paused on battery",flush=True); time.sleep(30)')
        self.assertEqual(error.exception.code, 'thermal_pressure')

    def test_condition_failure_after_launch_reaps_worker(self):
        calls = []
        def conditions():
            calls.append(1)
            if len(calls) > 1:
                raise c.ComparisonError('battery')
            return {'power': 'ac', 'thermal_pressure': 0}
        with self.assertRaises(c.ComparisonError) as error:
            self.run_child('import time; time.sleep(30)', conditions=conditions)
        self.assertEqual(error.exception.code, 'battery')

    def test_gate_requires_positive_integer_proof_count(self):
        valid = {'phase': 'gate', 'status': 'passed', 'backend': 'candidate', 'official_proof_checks': 2}
        result = self.run_child('print(' + repr('COMPARE_EVENT ' + json.dumps(valid)) + ')', phase='gate')
        self.assertEqual(result['official_proof_checks'], 2)
        for count in (None, 0, -1, True, 1.5):
            record = valid | {'official_proof_checks': count}
            with self.subTest(count=count), self.assertRaises(c.ComparisonError):
                self.run_child('print(' + repr('COMPARE_EVENT ' + json.dumps(record)) + ')', phase='gate')
        for record in (None, [], valid | {'backend': 'upstream'}):
            with self.subTest(record=record), self.assertRaises(c.ComparisonError) as error:
                self.run_child('print(' + repr('COMPARE_EVENT ' + json.dumps(record)) + ')', phase='gate')
            self.assertEqual(error.exception.code, 'invalid_record')

    def test_missing_duplicate_or_mismatched_context_cannot_be_accepted(self):
        source = self.print_record(sample_record())
        good = context_record()
        cases = [[], [good, good], [good | {'backend': 'upstream'}],
                 [good | {'phase': 'gate'}], [good | {'m': 16384}],
                 [good | {'cpu_threads': 4}], [good | {'requested_seconds': 300}],
                 [good | {'network': 'enabled'}], [good | {'wallet_access': 'enabled'}],
                 [good | {'proof_extension_sha256': {}}]]
        for records in cases:
            with self.subTest(contexts=records), self.assertRaises(c.ComparisonError) as error:
                self.run_child(source, contexts=records)
            self.assertEqual(error.exception.code, 'invalid_record')


class ConditionTests(unittest.TestCase):
    def test_power_and_thermal_queries_fail_closed(self):
        condition = c.Conditions.__new__(c.Conditions)
        condition._thermal = lambda: 0
        cases = [(0, "Now drawing from 'Battery Power'", 0, 'battery'),
                 (0, 'unrecognized power response', 0, 'power_unknown'),
                 (1, "Now drawing from 'AC Power'", 0, 'power_unknown'),
                 (0, "Now drawing from 'AC Power'", 2, 'thermal_pressure'),
                 (0, "Now drawing from 'AC Power'", -1, 'thermal_unknown')]
        for code, output, pressure, expected in cases:
            condition._thermal = lambda pressure=pressure: pressure
            response = subprocess.CompletedProcess(['pmset'], code, output, '')
            with self.subTest(expected=expected), patch.object(c.subprocess, 'run', return_value=response), \
                 self.assertRaises(c.ComparisonError) as error:
                condition()
            self.assertEqual(error.exception.code, expected)
        with patch.object(c.subprocess, 'run', side_effect=subprocess.TimeoutExpired('pmset', 3)), \
             self.assertRaises(c.ComparisonError) as error:
            condition()
        self.assertEqual(error.exception.code, 'power_unknown')


class SourceProvenanceTests(unittest.TestCase):
    def test_runtime_rejects_foreign_code_and_does_not_delete_it(self):
        builder = compare_worker.load_builder()
        source_name = 'pearl_metal_miner/__init__.py'
        extras = ('pearl_metal_miner/__pycache__/__init__.cpython-312.pyc',
                  'pearl_metal_miner/miner.so', 'pearl_metal_miner/miner.pyd',
                  'unrelated-file.txt')
        for extra in extras:
            with self.subTest(extra=extra), tempfile.TemporaryDirectory() as directory:
                runtime = Path(directory)
                source = runtime / source_name
                source.parent.mkdir()
                source.write_bytes(b'VALUE = 1\n')
                builder.validate_runtime_inventory(runtime, {source_name})
                foreign = runtime / extra
                foreign.parent.mkdir(parents=True, exist_ok=True)
                foreign.write_bytes(b'preserve foreign user file')
                with self.assertRaises(RuntimeError):
                    builder.validate_runtime_inventory(runtime, {source_name})
                self.assertEqual(foreign.read_bytes(), b'preserve foreign user file')

    def test_incomplete_runtime_is_only_allowed_during_preparation(self):
        builder = compare_worker.load_builder()
        with tempfile.TemporaryDirectory() as directory:
            runtime = Path(directory)
            builder.validate_runtime_inventory(runtime, {'pearl_metal_miner/__init__.py'},
                                               require_complete=False)
            with self.assertRaises(RuntimeError):
                builder.validate_runtime_inventory(runtime, {'pearl_metal_miner/__init__.py'})

    def test_checked_source_wins_over_timestamp_valid_bytecode_and_rejects_change(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = Path(directory)
            source = runtime / 'pearl_metal_miner/__init__.py'
            source.parent.mkdir()
            source.write_bytes(b'VALUE = "evil"\n')
            initial = source.stat()
            cache = Path(py_compile.compile(str(source), doraise=True,
                                            invalidation_mode=py_compile.PycInvalidationMode.TIMESTAMP))
            source.write_bytes(b'VALUE = "safe"\n')
            os.utime(source, ns=(initial.st_atime_ns, initial.st_mtime_ns))
            expected = {'pearl_metal_miner/__init__.py': hashlib.sha256(source.read_bytes()).hexdigest()}
            finder = compare_worker.UpstreamSourceFinder(runtime, expected)
            self.assertIsNone(finder.find_spec('unrelated_package'))
            with self.assertRaises(ModuleNotFoundError):
                finder.find_spec('pearl_metal_miner.unlisted')
            spec = finder.find_spec('pearl_metal_miner')
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            self.assertEqual(module.VALUE, 'safe')
            self.assertTrue(cache.exists())
            source.write_bytes(b'VALUE = "edit"\n')
            with self.assertRaises(ImportError):
                spec.loader.exec_module(importlib.util.module_from_spec(spec))


class ExecuteTests(unittest.TestCase):
    def exercise(self, root, output, *, fail_at=None, changed=False, interrupt=False, different_proof=False):
        calls = []
        multipliers = iter([10, 30, 42, 14])
        def runner(command, **kwargs):
            calls.append((list(command), copy.deepcopy(kwargs['config']), kwargs['phase']))
            if fail_at == len(calls):
                if interrupt:
                    raise KeyboardInterrupt
                raise c.ComparisonError('worker_failed')
            backend = command[command.index('--backend') + 1]
            record = (finished_gate(backend=backend) if kwargs['phase'] == 'gate'
                      else finished_trial(next(multipliers), backend=backend))
            if different_proof and len(calls) == 5:
                record['context']['proof_extension_sha256'] = {'_native.cpython-312-darwin.so': 'd' * 64}
            return record
        snapshots = iter([copy.deepcopy(FINGERPRINT),
                          {'pearl_m_miner/cli.py': 'f' * 64} if changed else copy.deepcopy(FINGERPRINT)])
        with patch.object(c, 'hardware', return_value=copy.deepcopy(HARDWARE)), \
             patch.object(c, 'git_identity', return_value=('b' * 40, False)), \
             contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            code = c.execute(arguments(output), root, preflight=lambda: DETAILS,
                             phase_runner=runner, build=lambda root: None,
                             condition_factory=lambda root: lambda: {'power': 'ac', 'thermal_pressure': 0},
                             identity=lambda root: next(snapshots), cool=lambda seconds, conditions: conditions())
        return code, json.loads((output / 'report.json').read_text(encoding='utf-8')), calls

    def test_plan_uses_no_native_or_filesystem_or_processes(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'must-not-exist'
            with patch.object(cli, 'preflight', side_effect=AssertionError('native work')), \
                 patch.object(c, 'reserve_output', side_effect=AssertionError('output reservation')), \
                 patch.object(c.ctypes, 'CDLL', side_effect=AssertionError('native load')), \
                 patch.object(c.subprocess, 'Popen', side_effect=AssertionError('process')), \
                 patch.object(Path, 'mkdir', side_effect=AssertionError('directory write')), \
                 contextlib.redirect_stdout(io.StringIO()) as stream:
                self.assertEqual(cli.main(['compare', '--plan', '--output', str(output)]), 0)
            self.assertFalse(output.exists())
            self.assertFalse(json.loads(stream.getvalue())['starts_work'])

    def test_complete_run_is_abba_with_equal_parameters_and_durable_report(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); output = root / 'report'
            code, report, calls = self.exercise(root, output)
            self.assertEqual(code, 0)
            self.assertEqual(report['status'], 'complete')
            self.assertAlmostEqual(report['comparison']['ratio'], 3)
            bench = [command for command, config, phase in calls if phase == 'benchmark']
            self.assertEqual([cmd[cmd.index('--backend') + 1] for cmd in bench],
                             ['upstream', 'candidate', 'candidate', 'upstream'])
            for flag in ('--seconds', '--m', '--n', '--cpu-threads', '--region-rows'):
                self.assertEqual(len({cmd[cmd.index(flag) + 1] for cmd in bench}), 1)
            self.assertEqual([(g['backend'], g['moment']) for g in report['gates']],
                             [(b, m) for m in ('before', 'after') for b in ('upstream', 'candidate')])
            self.assertFalse(report['uploaded'])
            self.assertIn('3.000x', (output / 'summary.md').read_text(encoding='utf-8'))
            self.assertEqual(sharing.public_report(report)['comparison'], report['comparison'])

    def test_failed_or_interrupted_run_preserves_partial_work_without_gain(self):
        for interruption in (False, True):
            with self.subTest(interruption=interruption), tempfile.TemporaryDirectory() as directory:
                root = Path(directory); output = root / 'report'
                code, report, calls = self.exercise(root, output, fail_at=4, interrupt=interruption)
                self.assertEqual(code, 130 if interruption else 1)
                self.assertEqual(len(report['trials']), 1)
                self.assertIsNone(report['comparison'])
                self.assertIn('No accepted improvement', (output / 'summary.md').read_text(encoding='utf-8'))

    def test_source_change_invalidates_all_completed_trials(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); output = root / 'report'
            code, report, calls = self.exercise(root, output, changed=True)
            self.assertEqual(code, 1)
            self.assertEqual(len(report['trials']), 4)
            self.assertEqual(report['failure_code'], 'source_changed')
            self.assertIsNone(report['comparison'])

    def test_proof_extension_change_between_phases_invalidates_comparison(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); output = root / 'report'
            code, report, calls = self.exercise(root, output, different_proof=True)
            self.assertEqual(code, 1)
            self.assertEqual(report['status'], 'failed')
            self.assertIsNone(report['comparison'])

    def test_uploaded_evidence_revalidates_context_independently(self):
        for field, value in [('cpu_threads', 8), ('backend', 'upstream'),
                             ('proof_extension_sha256', {'_native.cpython-312-darwin.so': 'd' * 64})]:
            report = complete_report()
            report['trials'][2]['context'][field] = value
            with self.subTest(field=field), self.assertRaises((ValueError, c.ComparisonError)):
                sharing.public_report(report)

    def test_preflight_errors_do_not_copy_paths_or_credentials_to_report(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); output = root / 'report'
            secret = '/Users/alice/private ghp_DoNotShareThisCredential'
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                code = c.execute(arguments(output), root,
                                 preflight=lambda: (_ for _ in ()).throw(RuntimeError(secret)))
            self.assertEqual(code, 1)
            for path in output.iterdir():
                text = path.read_text(encoding='utf-8')
                self.assertNotIn('alice', text)
                self.assertNotIn('ghp_', text)

    def test_existing_output_is_preserved_before_any_work(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); sentinel = root / 'existing.txt'; sentinel.write_text('keep')
            with self.assertRaises(c.ComparisonError) as error:
                c.execute(arguments(root), root, preflight=lambda: self.fail('native work'))
            self.assertEqual(error.exception.code, 'output_exists')
            self.assertEqual(sentinel.read_text(), 'keep')
            self.assertEqual(list(root.iterdir()), [sentinel])

    def test_symlinked_output_parent_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); actual = root / 'actual'; actual.mkdir(); alias = root / 'alias'
            try:
                alias.symlink_to(actual, target_is_directory=True)
            except OSError as error:
                self.skipTest('Creating a symlink is not permitted here: ' + str(error))
            with self.assertRaises(c.ComparisonError):
                c.reserve_output(alias / 'report')
            self.assertEqual(list(actual.iterdir()), [])

    def test_readback_mismatch_is_not_announced_as_ready(self):
        original = Path.read_text
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); output = root / 'report'
            def read(path, *args, **kwargs):
                text = original(path, *args, **kwargs)
                return '{}' if path == output / 'report.json' else text
            with patch.object(Path, 'read_text', read), self.assertRaisesRegex(RuntimeError, 'readback'):
                self.exercise(root, output)


class SharingTests(unittest.TestCase):
    def write_report(self, directory, report=None):
        path = Path(directory) / 'report.json'
        path.write_text(json.dumps(report or complete_report()), encoding='utf-8')
        return path

    def test_review_is_offline_and_does_not_create_submission_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_report(directory)
            with patch.object(sharing.subprocess, 'run', side_effect=AssertionError('network submission')), \
                 patch.object(sharing.webbrowser, 'open', side_effect=AssertionError('browser')), \
                 contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(sharing.share(path), 0)
            self.assertEqual(list(Path(directory).iterdir()), [path])

    def test_malformed_report_is_a_cli_error_before_external_actions(self):
        broken = complete_report()
        broken['configuration'] = []
        for report in ([], {'schema': c.SCHEMA}, broken):
            with self.subTest(report=report), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'report.json'
                path.write_text(json.dumps(report), encoding='utf-8')
                with patch.object(sharing.subprocess, 'run', side_effect=AssertionError('external action')), \
                     patch.object(sharing.webbrowser, 'open', side_effect=AssertionError('browser')), \
                     contextlib.redirect_stderr(io.StringIO()) as errors:
                    self.assertEqual(cli.main(['share-report', str(path), '--submit']), 1)
                self.assertIn('pearl-m-miner:', errors.getvalue())
                self.assertNotIn('Traceback', errors.getvalue())
                self.assertEqual(list(Path(directory).iterdir()), [path])

    def test_open_is_a_draft_and_does_not_submit_or_create_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_report(directory)
            with patch.object(sharing.subprocess, 'run', side_effect=AssertionError('submission')), \
                 patch.object(sharing.webbrowser, 'open', return_value=True) as browser, \
                 contextlib.redirect_stdout(io.StringIO()) as stream:
                self.assertEqual(sharing.share(path, open_browser=True), 0)
            self.assertEqual(browser.call_count, 1)
            self.assertTrue(browser.call_args.args[0].startswith(sharing.ISSUES + '?'))
            self.assertIn('draft only', stream.getvalue())
            self.assertEqual(list(Path(directory).iterdir()), [path])

    def test_explicit_submit_only_uploads_allowlisted_data_and_records_receipt(self):
        report = complete_report()
        report['private_key'] = 'NEVER_UPLOAD_ROOT_SECRET'
        report['hardware']['serial'] = 'NEVER_UPLOAD_SERIAL'
        report['trials'][0]['raw_stderr'] = '/Users/alice/NEVER_UPLOAD_LOCAL_PATH'
        calls = []
        def gh(command, **kwargs):
            body = Path(command[command.index('--body-file') + 1]).read_text(encoding='utf-8')
            calls.append((command, body))
            return subprocess.CompletedProcess(command, 0, 'https://github.com/parkerkyle-max/pearl-m-miner/issues/123\n', '')
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_report(directory, report)
            with patch.object(sharing.shutil, 'which', return_value='gh'), \
                 patch.object(sharing.subprocess, 'run', side_effect=gh), \
                 contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(sharing.share(path, submit=True), 0)
                with self.assertRaises((OSError, ValueError, RuntimeError)):
                    sharing.share(path, submit=True)
            self.assertEqual(len(calls), 1)
            command, body = calls[0]
            self.assertEqual(command[command.index('--repo') + 1], 'parkerkyle-max/pearl-m-miner')
            self.assertNotIn('NEVER_UPLOAD', body)
            self.assertNotIn('/Users/alice', body)
            receipt = json.loads(next(Path(directory).glob('submission-*.json')).read_text())
            self.assertEqual(receipt['status'], 'submitted')
            self.assertTrue(receipt['issue_url'].endswith('/123'))

    def test_ambiguous_submission_is_recorded_and_never_retried_automatically(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_report(directory)
            with patch.object(sharing.shutil, 'which', return_value='gh'), \
                 patch.object(sharing.subprocess, 'run', side_effect=subprocess.TimeoutExpired('gh', 60)) as request, \
                 contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(RuntimeError, 'outcome is unknown'):
                    sharing.share(path, submit=True)
                with self.assertRaises((OSError, ValueError, RuntimeError)):
                    sharing.share(path, submit=True)
            self.assertEqual(request.call_count, 1)
            receipt = json.loads(next(Path(directory).glob('submission-*.json')).read_text())
            self.assertEqual(receipt['status'], 'unknown')
            self.assertIsNone(receipt['issue_url'])

    def test_known_metadata_fields_cannot_smuggle_paths_or_credentials(self):
        poisons = [('hardware', 'chip', 'Apple M2 /Users/alice/private'),
                   ('hardware', 'os', 'macOS 27.0 ghp_DoNotPublishThisToken'),
                   ('software', 'version', 'ghp_DoNotPublishThisToken')]
        for section, field, value in poisons:
            report = complete_report(); report[section][field] = value
            with self.subTest(field=field), tempfile.TemporaryDirectory() as directory:
                path = self.write_report(directory, report)
                with patch.object(sharing.shutil, 'which', return_value='gh'), \
                     patch.object(sharing.subprocess, 'run') as request, \
                     self.assertRaises(ValueError):
                    sharing.share(path, submit=True)
                request.assert_not_called()


if __name__ == '__main__':
    unittest.main()
