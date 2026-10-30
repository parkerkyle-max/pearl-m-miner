"""CPU-only state-machine regression gates. No Metal, network or proof claims."""
from dataclasses import dataclass, replace
import hashlib
import json
import queue
import threading
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

import numpy as np

import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"tools/prefix_s_miner"))
import prefix_adapter as adapter
REAL_NATIVE = adapter.Native


HEADER = bytes(range(76))


@dataclass(frozen=True)
class Job:
    target: int = 100
    job_id: str = 'job'
    session_generation: int = 1
    header_bytes: bytes = HEADER
    cert_version: int = 3


class Pattern:
    def __init__(self, values): self.values = values
    def to_list(self): return list(self.values)


class FakeNative:
    def __init__(self): self.device_name = 'CPU MOCK'; self.closed = False; self.lib = NS(pfx_thermal_state=lambda: 0)
    def close(self): self.closed = True


class FakePrepared:
    made = []
    scans = 0
    on_prepare = None
    on_scan = None

    def __init__(self, native, x, v, seed):
        self.stats = NS(wall_seconds=.01, upload_seconds=.005, guard_gpu_seconds=.001)
        self.n = len(v); self.next_band = 0; self.closed = False
        type(self).made.append(self)
        if type(self).on_prepare: type(self).on_prepare()

    def scan(self, lo, bands, bound, **kwargs):
        if self.closed or lo != self.next_band:
            raise adapter.PrefixError('closed/repeated region')
        self.next_band = lo + bands
        type(self).scans += 1
        if type(self).on_scan: type(self).on_scan()
        return [(0, 0)], None, None, NS(tiles=bands * 32 * (self.n // 64),
            total_hits=1, stored_hits=1, gpu_seconds=.01, wall_seconds=.012)

    def close(self): self.closed = True


class Gates(unittest.TestCase):
    def setUp(self):
        adapter._ENGINES.clear(); adapter._CONNECTIONS.clear()
        adapter.Native = FakeNative; adapter.Prepared = FakePrepared
        FakePrepared.made = []; FakePrepared.scans = 0
        FakePrepared.on_prepare = FakePrepared.on_scan = None
        class Connection:
            def __init__(self):
                self.events = queue.Queue(); self.dead = threading.Event(); self.generation = 1
        self.ref = NS(config_to_bytes=lambda *x: b'config',
                      compute_job_key=lambda h, c: hashlib.sha256(h + c).digest(),
                      difficulty_factor=lambda *x: 1)
        self.miner = NS(PoolConnection=Connection, Job=Job, ref=self.ref,
            job_identity=lambda j: (j.session_generation, j.job_id, j.header_bytes, j.cert_version), log=lambda x: None)
        adapter.install_prefix_engine(self.miner)
        self.shape = NS(k=4096, r=128, h=2, w=64,
                        rows_pattern=Pattern([0, 32]), cols_pattern=Pattern(range(64)))

    def tearDown(self):
        for engine in adapter._ENGINES: engine.close()

    def grid(self, job=Job(), nonce=1):
        identity = self.miner.job_identity(job)
        key = self.ref.compute_job_key(job.header_bytes, b'config')
        a_root = hashlib.sha256(key + b'A' + nonce.to_bytes(16, 'little')).digest()
        b_root = hashlib.sha256(key + b'B').digest()
        a_seed = hashlib.sha256(key + a_root).digest()
        b_seed = hashlib.sha256(key + b_root).digest()
        return NS(_fusion_zero_b_prefix=True, shape=self.shape, m_dim=128, n_dim=128,
            cert_version=job.cert_version, job_key=key, a_seed=a_seed, b_seed=b_seed,
            tree_a=NS(root=a_root,overlay=NS(nonce=nonce,leaf=bytes(1 if (nonce>>bit)&1 else 255 for bit in range(128))+bytes(896))), tree_bt=NS(root=b_root),
            b_generation=NS(owner='test-owner',scope=(identity, job.header_bytes, b'config', job.cert_version, 128, 128, 0)),
            prefix_x=np.frombuffer(bytes(32 * 128 * 128 * 4), np.int32).reshape(32, 128, 128),
            prefix_v=np.frombuffer(bytes(128 * 128), np.int8).reshape(128, 128))

    def engine(self, job=Job(), connected=True):
        connection = self.miner.PoolConnection() if connected else None
        if connection:
            connection.generation = job.session_generation
            connection.events.put(job)
        return self.miner.Engine(self.shape, 128, 128), connection

    def sweep(self, engine, grid, target=100, index=0):
        return engine.sweep_region(index, 32, grid.a_seed, target.to_bytes(32, 'little'))

    def test_ordinary_regions_and_native_no_rescan(self):
        engine, _ = self.engine(); grid = self.grid(); engine.load_grid(grid)
        self.assertEqual(self.sweep(engine, grid)[1], 64)
        with self.assertRaises(adapter.PrefixError): self.sweep(engine, grid)
        self.assertEqual(self.sweep(engine, grid, index=1)[1], 64)
        self.assertEqual(engine.stats['valid_returned_tiles'], 128)

    def test_old_job_same_header_is_stale_without_gpu_and_recovers(self):
        current = Job(job_id='new')
        engine, _ = self.engine(current); old = self.grid(Job(job_id='old'))
        engine.load_grid(old)
        self.assertEqual(self.sweep(engine, old), ([], 0))
        self.assertEqual(len(FakePrepared.made), 0)
        self.assertEqual(engine.stats['stale_grid_loads'], 1)
        fresh = self.grid(current, nonce=2); engine.load_grid(fresh)
        self.assertEqual(self.sweep(engine, fresh)[1], 64)

    def test_old_session_and_certificate_are_stale_not_exceptions(self):
        for old, current in ((Job(session_generation=1), Job(session_generation=2)),
                             (Job(cert_version=2), Job(cert_version=3)),
                             (Job(header_bytes=bytes(76)), Job())):
            engine, _ = self.engine(current); grid = self.grid(old)
            engine.load_grid(grid)
            self.assertEqual(self.sweep(engine, grid), ([], 0))
        self.assertEqual(FakePrepared.scans, 0)
        self.assertEqual(len(FakePrepared.made), 0)

    def test_same_commitment_new_python_object_and_new_target_never_recounts(self):
        engine, connection = self.engine(); first = self.grid()
        engine.load_grid(first); self.assertEqual(self.sweep(engine, first)[1], 64)
        connection.events.put(Job(target=200))
        same = self.grid(Job(target=200))  # independent object, identical cryptographic work
        self.assertIsNot(same, first)
        engine.load_grid(same)
        self.assertEqual(self.sweep(engine, same, target=200), ([], 0))
        self.assertEqual(engine.stats['duplicate_commitment_loads'], 1)
        self.assertEqual(engine.stats['completed_tiles'], 64)
        self.assertEqual(len(FakePrepared.made), 1)
        fresh = self.grid(Job(target=200), nonce=2); engine.load_grid(fresh)
        self.assertEqual(self.sweep(engine, fresh, target=200)[1], 64)
        self.assertEqual(engine.stats['valid_returned_tiles'], 128)

    def test_relabeling_same_commitment_is_not_new_work(self):
        engine, connection = self.engine(); first = self.grid()
        engine.load_grid(first); self.sweep(engine, first)
        renamed = Job(job_id='renamed', session_generation=2)
        connection.generation = 2; connection.events.put(renamed)
        same = self.grid(renamed); engine.load_grid(same)
        self.assertEqual(self.sweep(engine, same), ([], 0))
        self.assertEqual(FakePrepared.scans, 1)

    def test_target_change_during_prepare_discards_and_closes_snapshot(self):
        engine, connection = self.engine(); grid = self.grid()
        FakePrepared.on_prepare = lambda: connection.events.put(Job(target=200))
        engine.load_grid(grid)
        self.assertTrue(FakePrepared.made[0].closed)
        self.assertEqual(self.sweep(engine, grid), ([], 0))
        self.assertEqual(FakePrepared.scans, 0)
        self.assertEqual(engine.stats['completed_tiles'], 0)
        self.assertEqual(engine.stats['stale_grid_loads'], 1)

    def test_scope_change_during_scan_counts_only_stale_completed_work(self):
        engine, connection = self.engine(); grid = self.grid(); engine.load_grid(grid)
        FakePrepared.on_scan = lambda: connection.events.put(Job(job_id='changed'))
        self.assertEqual(self.sweep(engine, grid), ([], 0))
        self.assertEqual(engine.stats['completed_tiles'], 64)
        self.assertEqual(engine.stats['stale_discarded_tiles'], 64)
        self.assertEqual(engine.stats['valid_returned_tiles'], 0)
        self.assertEqual(self.sweep(engine, grid, index=1), ([], 0))
        self.assertEqual(FakePrepared.scans, 1)

    def test_offline_benchmark_and_dead_connection_fail_closed(self):
        engine, _ = self.engine(connected=False); grid = self.grid()
        engine.load_grid(grid); self.assertEqual(self.sweep(engine, grid)[1], 64)
        engine.load_grid(self.grid()); self.assertEqual(self.sweep(engine, grid), ([], 0))
        online, connection = self.engine(); next_grid = self.grid(nonce=2)
        connection.dead.set(); online.load_grid(next_grid)
        self.assertEqual(self.sweep(online, next_grid), ([], 0))

    def test_bounded_highwater_rejects_old_nonce_across_long_run(self):
        engine, _ = self.engine()
        for nonce in range(1, 101): engine.load_grid(self.grid(nonce=nonce))
        self.assertEqual(engine._nonce_highwater, 100)
        self.assertFalse(hasattr(engine, '_seen_commitments'))
        old=self.grid(nonce=1); engine.load_grid(old)
        self.assertEqual(self.sweep(engine, old), ([], 0))

    def test_owner_change_and_forged_nonce_leaf_refused(self):
        engine, _ = self.engine(); engine.load_grid(self.grid(nonce=5))
        bad=self.grid(nonce=6); bad.b_generation.owner='other'
        with self.assertRaises(adapter.PrefixError): engine.load_grid(bad)
        bad=self.grid(nonce=6); bad.tree_a.overlay.leaf=bytes(1024)
        with self.assertRaises(adapter.PrefixError): engine.load_grid(bad)

    def test_internally_contradictory_binding_is_rejected(self):
        engine, _ = self.engine(); grid = self.grid()
        grid.b_generation.scope = (self.miner.job_identity(Job()), b'bad-header', b'config', 3, 128, 128, 0)
        with self.assertRaises(adapter.PrefixError): engine.load_grid(grid)
        self.assertEqual(len(FakePrepared.made), 0)


class AbiGates(unittest.TestCase):
    def test_wrong_native_abi_rejected_before_context_or_shader(self):
        class Version:
            def __call__(self): return 999
        lib = NS(pfx_abi_version=Version())
        with patch.object(adapter.C, 'CDLL', return_value=lib):
            with self.assertRaisesRegex(adapter.PrefixError, 'unsupported prefix native ABI'):
                REAL_NATIVE(library='unused.dylib', shader='does-not-exist.metal')

    def test_missing_native_abi_rejected_before_context_or_shader(self):
        with patch.object(adapter.C, 'CDLL', return_value=NS()):
            with self.assertRaises(AttributeError):
                REAL_NATIVE(library='unused.dylib', shader='does-not-exist.metal')


if __name__ == '__main__':
    suite = unittest.TestSuite([unittest.defaultTestLoader.loadTestsFromTestCase(c) for c in (Gates, AbiGates)])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful(): raise SystemExit(1)
    print('REVIEWED_ADAPTER_CPU_GATES ' + json.dumps({'cases': result.testsRun,
        'scope': 'CPU state-machine mock only; no GPU/proof/network', 'status': 'PASS'}))
