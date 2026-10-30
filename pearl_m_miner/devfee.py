"""Transparent, voluntary developer time contribution; no wallet secrets.

Only completed, non-stale native scan wall time reported by our own current
worker is credited. Startup, connections, waiting, pauses, proof preparation and
pool fees are separate. Normal long-run target is 1%; this is not 1% of income
or of elapsed wall time. Whole-region overshoot is carried into later cycles.
Workers are separate, sequential processes: a proof is never rerouted between
user and developer sessions. An optional contribution can be disabled with 0.
"""
from __future__ import annotations

import contextlib
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import queue
import signal
import subprocess
import sys
import tempfile
import threading
import time
import uuid

DEFAULT_DEV_ADDRESS = 'prl1pwjessemugthkad9hkttcx2rvenux2q0w0xcah2j0a7zfrycjhz5qhn7apw'
DEV_POOL = 'luckypool'
DEV_HOST = 'pearl-cpu-eu1.luckypool.io'
DEV_PORT = 3370
DEV_WORKER = 'pearl-m-miner-devfee'
ACTIVITY_PREFIX = 'PMM_ACTIVITY '
SCALE = 1_000_000
NS = 1_000_000_000
MAX_ACTIVITY_SECONDS = 60.0
MAX_STATE_BYTES = 4096
MAX_BALANCE = 86400 * NS * SCALE
DEFAULT_INTERVAL_SECONDS = 3600
DEV_IDLE_SECONDS = 90.0
STOP_GRACE_SECONDS = 30.0
CHECKPOINT_SECONDS = 5.0


def fee_ppm(percent: float) -> int:
    value = float(percent)
    if not math.isfinite(value) or not 0 <= value <= 5:
        raise ValueError('dev fee must be between 0 and 5 percent (0 disables it)')
    ppm = round(value * 10_000)
    if abs(value - ppm / 10_000) > 1e-9:
        raise ValueError('dev fee supports up to four decimal places in percent')
    return ppm


@dataclass
class Ledger:
    ppm: int
    interval_ns: int
    balance: int = 0
    reserved_ns: int = 0
    observed_dev_ns: int = 0
    retry_after: float = 0.0
    failures: int = 0

    @property
    def threshold(self):
        return self.interval_ns * self.ppm * (SCALE - self.ppm) // SCALE

    @property
    def due(self):
        return self.ppm > 0 and self.balance >= self.threshold

    @property
    def budget_ns(self):
        return max(0, self.balance // (SCALE - self.ppm))

    def user(self, ns, capped=False):
        # At most one contribution window is owed after developer outages. A
        # later recovery must never trigger hours of catch-up developer mining.
        limit = self.threshold if capped else self.threshold + round(
            (MAX_ACTIVITY_SECONDS + STOP_GRACE_SECONDS + 5) * NS) * self.ppm
        self.balance = min(limit, self.balance + ns * self.ppm)

    def reserve(self, ns):
        if self.reserved_ns or ns <= 0:
            raise ValueError('invalid developer reservation')
        self.reserved_ns = ns
        self.observed_dev_ns = 0
        self.balance -= ns * (SCALE - self.ppm)

    def developer(self, ns):
        if not self.reserved_ns or ns < 0:
            raise ValueError('developer activity without reservation')
        if self.observed_dev_ns + ns > self.reserved_ns:
            raise ValueError('developer activity exceeds reserved wall bound')
        self.observed_dev_ns += ns

    def finish(self):
        self.balance += (self.reserved_ns - self.observed_dev_ns) * (SCALE - self.ppm)
        self.reserved_ns = self.observed_dev_ns = 0

    def recover_interruption(self):
        """Unknown previous developer work is never charged a second time."""
        forgiven = max(0, self.reserved_ns - self.observed_dev_ns)
        # Reservation was durably deducted before launching the developer. On
        # unclean restart retain that deduction; discard the unused allowance
        # in the user's favor instead of estimating unknown completed work.
        self.reserved_ns = self.observed_dev_ns = 0
        return forgiven

    def record(self):
        return dict(version=1, ppm=self.ppm, interval_ns=self.interval_ns,
                    balance=self.balance, reserved_ns=self.reserved_ns,
                    observed_dev_ns=self.observed_dev_ns,
                    retry_after=self.retry_after, failures=self.failures)

    @classmethod
    def load(cls, value, ppm, interval_ns):
        if not isinstance(value, dict) or value.get('version') != 1:
            raise ValueError('unsupported contribution state')
        integers = ('ppm', 'interval_ns', 'balance', 'reserved_ns', 'observed_dev_ns', 'failures')
        if any(type(value.get(k)) is not int for k in integers):
            raise ValueError('invalid contribution state integers')
        if value['ppm'] != ppm or value['interval_ns'] != interval_ns:
            raise ValueError('contribution state settings differ')
        if not abs(value['balance']) <= MAX_BALANCE:
            raise ValueError('contribution state balance outside limit')
        if not 0 <= value['observed_dev_ns'] <= value['reserved_ns'] <= 86400 * NS:
            raise ValueError('invalid contribution reservation')
        retry = value.get('retry_after')
        if type(retry) not in (int, float) or not math.isfinite(retry) or retry < 0:
            raise ValueError('invalid contribution retry time')
        if not 0 <= value['failures'] <= 10:
            raise ValueError('invalid contribution retry count')
        return cls(ppm, interval_ns, value['balance'], value['reserved_ns'],
                   value['observed_dev_ns'], float(retry), value['failures'])


class StateStore:
    """One bounded atomic JSON file, plus an OS-owned exclusive advisory lock."""
    def __init__(self, path):
        self.path = Path(path)
        self.lock = None

    def acquire(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = open(str(self.path) + '.lock', 'a+b')
        try:
            if os.name == 'nt':
                import msvcrt
                self.lock.seek(0)
                if not self.lock.read(1):
                    self.lock.write(b'0'); self.lock.flush()
                self.lock.seek(0)
                msvcrt.locking(self.lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            self.lock.close(); self.lock = None
            raise RuntimeError('contribution state is already in use by another miner') from error

    def read(self, ppm, interval_ns):
        if not self.path.exists():
            return Ledger(ppm, interval_ns)
        with self.path.open('rb') as stream:
            raw = stream.read(MAX_STATE_BYTES + 1)
        if len(raw) > MAX_STATE_BYTES:
            raise ValueError('contribution state exceeds size limit')
        return Ledger.load(json.loads(raw), ppm, interval_ns)

    def write(self, ledger):
        if self.lock is None:
            raise RuntimeError('state write without lock')
        payload = (json.dumps(ledger.record(), sort_keys=True, separators=(',', ':')) + '\n').encode()
        if len(payload) > MAX_STATE_BYTES:
            raise ValueError('contribution state too large')
        fd, name = tempfile.mkstemp(prefix='.' + self.path.name + '.', dir=self.path.parent)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(payload); stream.flush(); os.fsync(stream.fileno())
            os.replace(name, self.path)
            if os.name != 'nt':
                directory = os.open(self.path.parent, os.O_RDONLY)
                try: os.fsync(directory)
                finally: os.close(directory)
        finally:
            with contextlib.suppress(FileNotFoundError): os.unlink(name)

    def close(self):
        if self.lock is not None:
            self.lock.close(); self.lock = None


def default_state_path(coin, address, worker, dev_address, ppm, interval_ns):
    key = hashlib.sha256(json.dumps([coin, address, worker, dev_address, ppm, interval_ns],
                                   separators=(',', ':')).encode()).hexdigest()[:24]
    base = (Path.home() / 'Library/Application Support/PearlM-Miner' if sys.platform == 'darwin'
            else Path(os.environ.get('LOCALAPPDATA', Path.home() / '.local/state')) / 'PearlM-Miner')
    return base / ('contribution-' + key + '.json')


def activity_ns(line, session):
    if not line.startswith(ACTIVITY_PREFIX):
        return None
    value = json.loads(line[len(ACTIVITY_PREFIX):])
    if not isinstance(value, dict) or value.get('session') != session:
        raise ValueError('activity has a foreign or missing worker session')
    seconds, tiles = value.get('seconds'), value.get('tiles')
    if (type(seconds) not in (int, float) or not math.isfinite(seconds)
            or not 0 < seconds <= MAX_ACTIVITY_SECONDS or type(tiles) is not int or tiles <= 0):
        raise ValueError('activity has invalid seconds or valid-work count')
    return max(1, round(seconds * NS))


class Worker:
    def __init__(self, command, session, clock=time.monotonic):
        if not command or any(type(part) is not str or '\0' in part for part in command):
            raise ValueError('worker command must be a nonempty string list')
        env = os.environ.copy(); env['PEARL_M_SESSION'] = session; env['PYTHONUNBUFFERED'] = '1'
        options = {'creationflags': subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == 'nt' else {'start_new_session': True}
        self.process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                        stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace',
                                        bufsize=1, env=env, **options)
        self.lines = queue.Queue(maxsize=512); self.eof = threading.Event(); self.clock = clock
        self.drain_error = None
        self.reader = threading.Thread(target=self._read, name='contribution-output', daemon=True)
        self.reader.start()

    def _read(self):
        try:
            while True:
                line = self.process.stdout.readline(65537)
                if not line: break
                # An overlong line cannot become a valid accounting record.
                if len(line) > 65536:
                    line = '[devfee] discarded an overlong worker output line\n'
                self.lines.put(line.rstrip('\r\n'))
        finally:
            self.eof.set()

    def poll(self): return self.process.poll()

    def read(self, timeout=0.1):
        try: return self.lines.get(timeout=timeout)
        except queue.Empty: return None

    def stop(self, on_line):
        def deliver(line):
            try: on_line(line)
            except BaseException as error:
                # Cleanup cannot depend on an output consumer still existing.
                # Keep draining so a full pipe/queue cannot prevent child exit;
                # the caller can inspect this error only after reap succeeds.
                if self.drain_error is None: self.drain_error = error
        def drain_until(deadline):
            while self.clock() < deadline:
                line = self.read(0.02)
                if line is not None: deliver(line)
                if self.poll() is not None and self.eof.is_set() and self.lines.empty(): return True
            return self.poll() is not None and self.eof.is_set() and self.lines.empty()
        if self.poll() is None:
            with contextlib.suppress(ProcessLookupError):
                if os.name == 'nt': self.process.send_signal(signal.CTRL_BREAK_EVENT)
                else: os.killpg(self.process.pid, signal.SIGINT)
        done = drain_until(self.clock() + STOP_GRACE_SECONDS)
        if not done:
            with contextlib.suppress(ProcessLookupError):
                if os.name == 'nt':
                    if self.poll() is None: self.process.terminate()
                else: os.killpg(self.process.pid, signal.SIGTERM)
        if not done: done = drain_until(self.clock() + 1)
        if not done:
            with contextlib.suppress(ProcessLookupError):
                if os.name == 'nt':
                    if self.poll() is None: self.process.kill()
                else: os.killpg(self.process.pid, signal.SIGKILL)
        if not done: done = drain_until(self.clock() + 3)
        if not done:
            raise RuntimeError('previous worker did not exit and drain; refusing overlapping mining')
        code = self.process.wait(timeout=1)
        self.reader.join(timeout=1); self.process.stdout.close()
        return code


class Supervisor:
    def __init__(self, build_command, *, coin, user_address, user_worker, dev_address,
                 ppm, interval_ns, store, time_limit, stop_event, diagnostic, log,
                 clock=time.monotonic, wall_clock=time.time, worker_factory=Worker):
        self.build_command = build_command
        self.coin, self.user_address, self.user_worker = coin, user_address, user_worker
        self.dev_address, self.ppm, self.interval_ns = dev_address, ppm, interval_ns
        self.store, self.time_limit, self.stop_event = store, time_limit, stop_event
        self.log_sink, self.clock, self.wall_clock, self.worker_factory = log, clock, wall_clock, worker_factory
        self.log_error = None
        self.diagnostic = diagnostic
        self.ledger = Ledger(ppm, interval_ns); self.enabled = bool(ppm)
        self.worker = None; self.role = 'user'; self.session = ''
        self.started = self.last_activity = self.worker_started = self.clock()
        self.session_active_ns = self.dev_budget_ns = 0
        self.total_user_ns = self.total_dev_ns = 0
        self.bad_activity = False
        self.last_checkpoint = -math.inf

    def log(self, message):
        if self.log_error is not None: return
        try: self.log_sink(message)
        except Exception as error:
            # A closed terminal or `... | head` must request shutdown, not leave
            # the detached worker running when logging interrupts cleanup.
            self.log_error = error
            self.stop_event.set()

    def emit(self, message): self.log('[devfee] ' + message)

    def persist(self, force=False):
        if not self.enabled: return False
        # Live accounting remains exact in memory. A crash can lose at most one
        # five-second user checkpoint, which reduces the requested contribution.
        # Developer unknown work is covered by its durable advance reservation.
        if not force and self.clock() - self.last_checkpoint < CHECKPOINT_SECONDS:
            return True
        try:
            self.store.write(self.ledger); self.last_checkpoint = self.clock(); return True
        except (OSError, ValueError, RuntimeError) as error:
            self.enabled = False
            self.emit('state persistence failed; developer contribution disabled for this run: ' + str(error))
            return False

    def receive(self, line):
        if not line.startswith(ACTIVITY_PREFIX):
            self.log(line); return
        try:
            ns = activity_ns(line, self.session)
            elapsed_ns = round((self.clock() - self.worker_started + 1.0) * NS)
            if self.session_active_ns + ns > elapsed_ns:
                raise ValueError('reported active time exceeds this worker lifetime')
            self.session_active_ns += ns; self.last_activity = self.clock()
            if self.role == 'dev':
                self.ledger.developer(ns); self.total_dev_ns += ns
            else:
                self.ledger.user(ns, capped=self.wall_clock() < self.ledger.retry_after)
                self.total_user_ns += ns
            self.persist()
        except (ValueError, TypeError, OverflowError, json.JSONDecodeError) as error:
            self.bad_activity = True
            self.emit('accounting record refused; no credit from this record: ' + str(error))

    def stop_worker(self):
        if self.worker is not None:
            previous = self.worker
            previous.stop(self.receive)
            self.worker = None
            self.emit('previous worker stopped and reaped; session=' + self.session)
            self.log('PMM_DEVFEE_SESSION ' + json.dumps(dict(role=self.role, session=self.session,
                payout=self.dev_address if self.role == 'dev' else self.user_address,
                active_seconds=self.session_active_ns / NS, reaped=True), separators=(',', ':')))
            if getattr(previous, 'drain_error', None) is not None:
                raise RuntimeError('output handler failed during shutdown; previous worker was reaped') from previous.drain_error

    def start_worker(self, role):
        if self.worker is not None: raise RuntimeError('worker overlap forbidden')
        self.role = role; self.session = uuid.uuid4().hex
        self.session_active_ns = 0; self.bad_activity = False
        self.worker_started = self.last_activity = self.clock()
        address = self.dev_address if role == 'dev' else self.user_address
        worker = DEV_WORKER if role == 'dev' else self.user_worker
        route = f'{DEV_POOL} {DEV_HOST}:{DEV_PORT}' if role == 'dev' else 'configured user pool'
        self.emit(f'start {role}; payout={address}; worker={worker}; route={route}; session={self.session}')
        if self.stop_event.is_set(): raise KeyboardInterrupt
        command = self.build_command(address, worker, role)
        self.worker = self.worker_factory(command, self.session, self.clock)

    def enter_dev(self):
        self.stop_worker()
        self.dev_budget_ns = self.ledger.budget_ns
        # Pre-reserve the entire bounded developer wall window + stop grace.
        # If power dies before reconciliation, leftover allowance is forgiven
        # rather than charged again. No developer process starts before fsync.
        self.dev_wall_limit = DEV_IDLE_SECONDS + self.dev_budget_ns / NS
        reservation = math.ceil((self.dev_wall_limit + STOP_GRACE_SECONDS + 5) * NS)
        self.ledger.reserve(reservation)
        if not self.persist(force=True):
            self.ledger.finish(); self.start_worker('user'); return
        try: self.start_worker('dev')
        except Exception as error:
            self.emit('developer launch failed: ' + str(error)); self.leave_dev(failed=True)

    def leave_dev(self, failed):
        self.stop_worker()
        self.ledger.finish()
        if failed:
            self.ledger.failures = min(10, self.ledger.failures + 1)
            delay = min(3600, 300 * 2 ** (self.ledger.failures - 1))
            self.ledger.retry_after = self.wall_clock() + delay
            self.emit(f'developer unavailable; returning to user, retry no sooner than {delay}s; no long catch-up charge')
        else:
            self.ledger.failures = 0; self.ledger.retry_after = 0
        self.persist(force=True); self.start_worker('user')

    def run(self):
        self.emit(f'voluntary contribution={self.ppm / 10000:g}%; disable with --dev-fee 0; pool fees are separate')
        self.emit('accounting=completed valid native scan wall time only; startup/wait/pause excluded; reconnect overhead is extra')
        self.emit(f'developer payout={self.dev_address}; route={DEV_POOL} {DEV_HOST}:{DEV_PORT}; state={self.store.path if self.store else "disabled"}')
        if self.diagnostic:
            self.emit('ACCELERATED DIAGNOSTIC ONLY; shortened active-time cycle, not the production schedule')
        if self.enabled:
            try:
                self.ledger = self.store.read(self.ppm, self.interval_ns)
                # Wall-clock changes must not suppress retries indefinitely.
                self.ledger.retry_after = min(self.ledger.retry_after, self.wall_clock() + 3600)
                forgiven = self.ledger.recover_interruption()
                if forgiven: self.emit(f'unclean prior developer session: up to {forgiven / NS:.6f}s allowance forgiven; never charged again')
                self.persist(force=True)
            except (OSError, ValueError, TypeError) as error:
                self.enabled = False
                self.emit('state could not be safely read; continuing user mining with contribution disabled: ' + str(error))
        code = 0
        try:
            self.start_worker('user')
            while True:
                if self.stop_event.is_set(): break
                if self.time_limit and self.clock() - self.started >= self.time_limit: break
                line = self.worker.read(0.1)
                if line is not None: self.receive(line)
                if self.worker.poll() is not None:
                    if self.role == 'dev': self.leave_dev(failed=True); continue
                    code = self.worker.poll(); break
                if self.role == 'dev':
                    done = self.session_active_ns >= self.dev_budget_ns
                    failed = (not self.enabled or self.bad_activity
                              or self.clock() - self.last_activity >= DEV_IDLE_SECONDS
                              or self.clock() - self.worker_started >= self.dev_wall_limit)
                    if done or failed: self.leave_dev(failed=failed and not done)
                elif self.enabled and not self.bad_activity and self.ledger.due and self.wall_clock() >= self.ledger.retry_after:
                    self.enter_dev()
        except KeyboardInterrupt:
            code = 1 if self.log_error is not None else 130
        finally:
            self.stop_worker()
            if self.ledger.reserved_ns: self.ledger.finish()
            self.persist(force=True)
            self.emit(f'run accounted user={self.total_user_ns / NS:.6f}s dev={self.total_dev_ns / NS:.6f}s; valid scan time, not income')
        return 1 if self.log_error is not None and not code else code


def run_with_devfee(build_command, *, coin='PRL', user_address, user_worker='pearl-m-miner',
                    dev_address=DEFAULT_DEV_ADDRESS, fee_percent=1.0,
                    interval_seconds=DEFAULT_INTERVAL_SECONDS, state_path=None,
                    time_limit=None, stop_event=None, diagnostic=False, log=print):
    """Run separate user/developer worker sessions and return their exit status.

    build_command(address, worker, role) must replace the payout, worker and pool
    arguments, never append conflicting duplicates. The developer role uses the
    disclosed DEV_POOL/HOST/PORT. Worker stdout activity must include the exact
    PEARL_M_SESSION environment token. Benchmark/help must not call this function.
    Non-default cycle lengths require explicit diagnostic=True and separate state.
    """
    ppm = fee_ppm(fee_percent)
    if coin.upper() != 'PRL': raise ValueError('this contribution route supports PRL only')
    if not user_address or not user_worker: raise ValueError('user payout and worker are required')
    if ppm and not dev_address: raise ValueError('developer public payout is required when enabled')
    if (not math.isfinite(float(interval_seconds)) or interval_seconds <= 0
            or interval_seconds > 86400): raise ValueError('invalid contribution cycle')
    if interval_seconds != DEFAULT_INTERVAL_SECONDS and not diagnostic:
        raise ValueError('shortened contribution cycles require explicit diagnostic=True')
    if time_limit is not None and (not math.isfinite(float(time_limit)) or time_limit < 0):
        raise ValueError('invalid supervisor time limit')
    interval_ns = round(interval_seconds * NS)
    if ppm and interval_ns * ppm // SCALE < 1: raise ValueError('contribution window is too short')
    store = None
    requested_stop = stop_event or threading.Event()
    caught_signal = []
    old_handlers = {}
    def handle_signal(number, frame):
        caught_signal.append(number); requested_stop.set()
    try:
        if ppm:
            path = state_path or default_state_path(coin, user_address, user_worker, dev_address, ppm, interval_ns)
            store = StateStore(path); store.acquire()
        if threading.current_thread() is threading.main_thread():
            for name in ('SIGINT', 'SIGTERM', 'SIGHUP'):
                number = getattr(signal, name, None)
                if number is not None:
                    old_handlers[number] = signal.getsignal(number)
                    signal.signal(number, handle_signal)
        code = Supervisor(build_command, coin=coin, user_address=user_address, user_worker=user_worker,
                          dev_address=dev_address, ppm=ppm, interval_ns=interval_ns, store=store,
                          time_limit=time_limit, stop_event=requested_stop,
                          diagnostic=diagnostic, log=log).run()
        return 128 + caught_signal[0] if caught_signal else code
    finally:
        for number, previous in old_handlers.items(): signal.signal(number, previous)
        if store is not None: store.close()
