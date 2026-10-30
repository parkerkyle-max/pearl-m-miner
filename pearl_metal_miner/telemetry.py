"""Display-only PRL observations; no mining, sockets, fee credit or native calls.

Native timings overlap and must not be summed into an elapsed-time estimate.
Missing measurements stay unknown. The first snapshot has no native delta;
counter resets and non-forward clocks cannot produce a fabricated rate.
"""
from __future__ import annotations

import math
import time


NATIVE_COUNTERS = (
    'prepares', 'prepare_wall_s', 'upload_s', 'guard_gpu_s', 'scans',
    'gpu_s', 'scan_wall_s', 'completed_tiles', 'valid_returned_tiles',
    'stale_discarded_tiles', 'overflow_hits', 'stale_grid_loads',
    'duplicate_commitment_loads', 'sparse_prepares', 'legacy_prepares',
    'csr_prepares', 's_prepares',
)


def _number(value):
    if type(value) not in (int, float):
        return None
    try:
        return value if value >= 0 and math.isfinite(value) else None
    except OverflowError:
        return None


def _product(left, right):
    left, right = _number(left), _number(right)
    if left is None or right is None or right == 0:
        return None
    return _number(left * right)


class Telemetry:
    """One worker's monotonic, bounded-cadence observations.

    Job timestamps mean processed by the mining loop, not network wire arrival.
    Received notifications include repeats; adopted updates count only actual
    job refreshes. Grid log notices survive adoption after a GPU scan.
    """
    def __init__(self, *, clock=time.monotonic, interval=30.0):
        if _number(interval) is None or interval <= 0:
            raise ValueError('telemetry interval must be positive and finite')
        self.clock, self.interval = clock, interval
        self.next_report = clock() + interval
        self.last_received = self.last_adopted = None
        self.received = self.adopted = 0
        self.job_notice = False
        self.previous_time = None
        self.previous_native = {}

    def due(self):
        return self.clock() >= self.next_report

    def job_received(self):
        self.received += 1
        self.last_received = self.clock()

    def job_adopted(self):
        self.adopted += 1
        self.last_adopted = self.clock()
        self.job_notice = True

    def take_job_notice(self):
        result, self.job_notice = self.job_notice, False
        return result

    def snapshot(self, *, rolling_tiles_s, session_tiles_s, work_per_tile,
                 uptime_s, submitted, accepted, rejected, pending,
                 native_stats=None):
        now = self.clock()
        self.next_report = now + self.interval
        forward = self.previous_time is not None and now > self.previous_time
        window = now - self.previous_time if forward else None
        source = native_stats if isinstance(native_stats, dict) else {}
        current = {name: _number(source.get(name)) for name in NATIVE_COUNTERS}
        delta, resets = {}, []
        for name, value in current.items():
            before = self.previous_native.get(name)
            if value is not None and before is not None and value < before:
                resets.append(name)
            delta[name] = (value - before if forward and value is not None
                           and before is not None and value >= before else None)
        self.previous_time, self.previous_native = now, current
        rolling_hs = _product(rolling_tiles_s, work_per_tile)
        session_hs = _product(session_tiles_s, work_per_tile)

        def age(when):
            return now - when if when is not None and now >= when else None

        return {
            'schema': 'pearl-m-telemetry-v1', 'coin': 'PRL',
            'algorithm': 'PearlHash', 'uptime_seconds': _number(uptime_s),
            'local_rate': {
                'basis': 'protocol_equivalent_work_per_wall_second',
                'rolling_window_seconds': 60,
                'rolling_tiles_per_second': _number(rolling_tiles_s),
                'session_tiles_per_second': _number(session_tiles_s),
                'protocol_work_per_tile': _number(work_per_tile),
                'rolling_hs': rolling_hs, 'session_hs': session_hs,
                'rolling_ths': rolling_hs / 1e12 if rolling_hs is not None else None,
                'session_ths': session_hs / 1e12 if session_hs is not None else None,
            },
            'pool_effective_hs': None,
            'shares': {'submitted': _number(submitted), 'accepted': _number(accepted),
                       'rejected': _number(rejected), 'pending': _number(pending)},
            'jobs': {'received_notifications': self.received,
                     'adopted_updates': self.adopted,
                     'last_received_age_seconds': age(self.last_received),
                     'last_adopted_age_seconds': age(self.last_adopted)},
            'native': {'cumulative': current, 'delta': delta,
                       'delta_window_seconds': window, 'counter_resets': resets,
                       'timings_overlap': True},
        }
