"""Contribution accounting, durable state and sequential worker lifecycle tests."""
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from pearl_m_miner import devfee as d


class Clock:
    def __init__(self): self.now = 1000.0
    def __call__(self): return self.now
    def advance(self, seconds): self.now += seconds


class MemoryStore:
    path = 'memory-state'
    def __init__(self): self.value = None; self.fail = False; self.writes=[]
    def read(self, ppm, interval_ns):
        return d.Ledger.load(self.value, ppm, interval_ns) if self.value else d.Ledger(ppm, interval_ns)
    def write(self, ledger):
        if self.fail: raise OSError('injected write failure')
        self.value = json.loads(json.dumps(ledger.record()))
        self.writes.append(self.value)


class FakeWorkers:
    def __init__(self, clock, *, startup=0, fail_dev=False, idle_dev=False, stop_event=None):
        self.clock = clock; self.startup = startup; self.fail_dev = fail_dev; self.idle_dev = idle_dev
        self.live = set(); self.history = []; self.events = []; self.stop_event = stop_event
    def __call__(self, command, session, clock):
        owner = self
        if owner.live: raise AssertionError('overlapping workers')
        role, address, worker = command
        owner.history.append((role, address, worker, session))
        class Child:
            def __init__(self):
                self.started = clock(); self.stopped = False; self.code = None
                owner.live.add(session)
            def read(self, timeout=0.1):
                clock.advance(timeout)
                if role == 'dev' and owner.fail_dev:
                    self.code = 9; return None
                if (role == 'dev' and owner.idle_dev) or clock() - self.started < owner.startup:
                    return None
                value = dict(session=session, seconds=timeout, tiles=1,
                             proof_job=role + '-job', payout=address)
                owner.events.append(value)
                return d.ACTIVITY_PREFIX + json.dumps(value)
            def poll(self): return self.code
            def stop(self, on_line):
                if self.stopped: raise AssertionError('double stop')
                self.stopped = True; owner.live.remove(session); self.code = 0
                return 0
        return Child()


class Gates(unittest.TestCase):
    def make(self, *, duration=25, startup=0, fail_dev=False, idle_dev=False, store=None,
             ppm=10000, interval=10, stop_event=None):
        clock = Clock(); workers = FakeWorkers(clock, startup=startup, fail_dev=fail_dev, idle_dev=idle_dev)
        state = store or MemoryStore(); logs = []; stop = stop_event or threading.Event()
        s = d.Supervisor(lambda address, worker, role: [role, address, worker], coin='PRL',
                         user_address='public-user-wallet', user_worker='user-worker',
                         dev_address=d.DEFAULT_DEV_ADDRESS, ppm=ppm, interval_ns=interval*d.NS,
                         store=state, time_limit=duration, stop_event=stop, diagnostic=True, log=logs.append,
                         clock=clock, wall_clock=clock, worker_factory=workers)
        return s, clock, workers, state, logs

    def test_default_exact_active_cycle_and_overshoot(self):
        ledger = d.Ledger(10000, 3600*d.NS)
        ledger.user(3564*d.NS)
        self.assertTrue(ledger.due); self.assertEqual(ledger.budget_ns,36*d.NS)
        ledger.reserve(200*d.NS); ledger.developer(36*d.NS); ledger.finish()
        self.assertEqual(ledger.balance,0)
        # A 0.1-second whole-region developer overrun is carried, not forgotten.
        ledger.user(3564*d.NS); ledger.reserve(200*d.NS)
        ledger.developer(round(36.1*d.NS)); ledger.finish()
        self.assertEqual(ledger.balance,-round(.1*d.NS)*(d.SCALE-10000))
        ledger.user(round(3573.9*d.NS))
        self.assertEqual(ledger.budget_ns,36*d.NS)

    def test_user_region_overshoot_is_not_truncated(self):
        ledger = d.Ledger(10000,3600*d.NS)
        ledger.user(3565*d.NS)
        self.assertGreater(ledger.balance,ledger.threshold)
        self.assertGreater(ledger.budget_ns,36*d.NS)

    def test_failure_debt_is_bounded_and_restart_credit_preserved(self):
        ledger = d.Ledger(10000,3600*d.NS)
        ledger.user(999999*d.NS,capped=True)
        self.assertEqual(ledger.balance,ledger.threshold)
        loaded = d.Ledger.load(ledger.record(),10000,3600*d.NS)
        self.assertEqual(loaded.budget_ns,36*d.NS)

    def test_restart_reserved_dev_allowance_never_recharged(self):
        ledger = d.Ledger(10000,3600*d.NS); ledger.user(3564*d.NS)
        ledger.reserve(200*d.NS); ledger.developer(10*d.NS)
        loaded = d.Ledger.load(ledger.record(),10000,3600*d.NS)
        old = loaded.balance
        self.assertEqual(loaded.recover_interruption(),190*d.NS)
        self.assertEqual(loaded.balance,old); self.assertFalse(loaded.due)
        self.assertEqual(loaded.reserved_ns,0)

    def test_atomic_state_replace_failure_leaves_previous_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = d.StateStore(Path(tmp)/'state.json'); store.acquire()
            try:
                first=d.Ledger(10000,3600*d.NS); first.user(42*d.NS); store.write(first)
                original=store.path.read_bytes(); first.user(10*d.NS)
                with patch.object(d.os,'replace',side_effect=OSError('injected atomic replace failure')):
                    with self.assertRaises(OSError):store.write(first)
                self.assertEqual(store.path.read_bytes(),original)
                self.assertEqual(len(list(Path(tmp).glob('.state.json.*'))),0)
                self.assertEqual(store.read(10000,3600*d.NS).balance,42*d.NS*10000)
            finally:store.close()

    def test_state_lock_and_corrupt_size_rejection(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'state.json'; first=d.StateStore(path); second=d.StateStore(path)
            first.acquire()
            try:
                with self.assertRaises(RuntimeError):second.acquire()
                path.write_bytes(b'x'*(d.MAX_STATE_BYTES+1))
                with self.assertRaises(ValueError):first.read(10000,3600*d.NS)
            finally:first.close();second.close()
            second.acquire();second.close()

    def test_record_rejects_foreign_sessions_bad_times_and_stale_work(self):
        good={'session':'a','seconds':.1,'tiles':2}
        self.assertEqual(d.activity_ns(d.ACTIVITY_PREFIX+json.dumps(good),'a'),100000000)
        for change in ({'session':'b'},{'seconds':float('nan')},{'seconds':-1},
                       {'seconds':True},{'seconds':61},{'tiles':0},{'tiles':False}):
            with self.subTest(change=change),self.assertRaises(ValueError):
                d.activity_ns(d.ACTIVITY_PREFIX+json.dumps(dict(good,**change)),'a')

    def test_user_dev_user_sessions_and_correct_payout_no_overlapping(self):
        s,clock,workers,state,logs=self.make(duration=22)
        self.assertEqual(s.run(),0);self.assertFalse(workers.live)
        roles=[v[0] for v in workers.history]
        self.assertEqual(roles[:3],['user','dev','user'])
        self.assertEqual(len(set(v[3] for v in workers.history)),len(workers.history))
        for role,address,worker,session in workers.history:
            self.assertEqual(address,d.DEFAULT_DEV_ADDRESS if role=='dev' else 'public-user-wallet')
            self.assertEqual(worker,d.DEV_WORKER if role=='dev' else 'user-worker')
            for event in [e for e in workers.events if e['session']==session]:
                self.assertEqual(event['proof_job'],role+'-job')
                self.assertEqual(event['payout'],address)
        self.assertEqual(state.value['reserved_ns'],0)
        self.assertTrue(any('ACCELERATED DIAGNOSTIC' in line for line in logs))

    def test_startup_downtime_not_charged(self):
        s,clock,workers,state,logs=self.make(duration=11,startup=5)
        s.run();self.assertEqual([v[0] for v in workers.history],['user'])
        self.assertLess(s.total_user_ns,7*d.NS)

    def test_dev_failure_returns_user_and_backoff_no_tight_loop(self):
        s,clock,workers,state,logs=self.make(duration=30,fail_dev=True)
        s.run();self.assertEqual([v[0] for v in workers.history],['user','dev','user'])
        self.assertEqual(s.total_dev_ns,0)
        self.assertGreater(state.value['retry_after'],clock())
        self.assertLessEqual(s.ledger.balance,s.ledger.threshold)

    def test_dev_idle_timeout_returns_user(self):
        s,clock,workers,state,logs=self.make(duration=110,idle_dev=True)
        s.run();self.assertEqual([v[0] for v in workers.history],['user','dev','user'])
        self.assertEqual(s.total_dev_ns,0)

    def test_zero_fee_no_dev_and_no_state_write(self):
        s,clock,workers,state,logs=self.make(ppm=0,duration=20)
        state.fail=True;s.run()
        self.assertEqual([v[0] for v in workers.history],['user']);self.assertIsNone(state.value)

    def test_failure_to_persist_disables_fee_and_keeps_user_mining(self):
        s,clock,workers,state,logs=self.make(duration=20);state.fail=True
        s.run();self.assertEqual([v[0] for v in workers.history],['user'])
        self.assertFalse(s.enabled)

    def test_cancellation_drains_current_session_and_reconciles(self):
        stop=threading.Event();s,clock,workers,state,logs=self.make(duration=100,stop_event=stop)
        original=workers.__call__
        def factory(command,session,c):
            child=original(command,session,c)
            if command[0]=='dev':stop.set()
            return child
        s.worker_factory=factory;s.run()
        self.assertFalse(workers.live);self.assertEqual(state.value['reserved_ns'],0)

    def test_clean_restart_resumes_user_credit_before_fee(self):
        first,_,_,state,_=self.make(duration=5)
        first.run();credit=state.value['balance'];self.assertGreater(credit,0)
        second,_,workers,_,_=self.make(duration=8,store=state)
        second.run();self.assertEqual([v[0] for v in workers.history],['user','dev','user'])

    def test_launch_failure_refunds_reservation_and_returns_user(self):
        s,_,workers,state,_=self.make(duration=20)
        original=workers.__call__
        def spawn(command,session,clock):
            if command[0]=='dev':raise OSError('injected spawn failure')
            return original(command,session,clock)
        s.worker_factory=spawn;s.run()
        self.assertEqual([v[0] for v in workers.history],['user','user'])
        self.assertEqual(state.value['reserved_ns'],0);self.assertFalse(workers.live)

    def test_write_failure_during_dev_keeps_durable_reservation(self):
        s,_,workers,state,_=self.make(duration=110,interval=1000)
        # Seed nearly all user credit so the long diagnostic developer session
        # reaches a scheduled checkpoint before ending.
        initial=d.Ledger(10000,1000*d.NS);initial.user(985*d.NS);state.value=initial.record()
        original=workers.__call__
        def spawn(command,session,clock):
            child=original(command,session,clock)
            if command[0]=='dev':state.fail=True
            return child
        s.worker_factory=spawn;s.run()
        self.assertEqual([v[0] for v in workers.history],['user','dev','user'])
        self.assertGreater(state.value['reserved_ns'],0)
        recovered=d.Ledger.load(state.value,10000,1000*d.NS)
        recovered.recover_interruption();self.assertFalse(recovered.due)

    def test_checkpoint_cadence_and_forced_session_boundaries(self):
        s,_,workers,state,_=self.make(duration=23,interval=1000)
        s.run()
        self.assertGreater(len(workers.events),200)
        # Initial receipt, four five-second checkpoints and final forced flush.
        self.assertLessEqual(len(state.writes),7)
        self.assertEqual(state.value['balance'],s.ledger.balance)
        t,_,_,other,_=self.make(duration=12)
        t.run()
        self.assertTrue(any(v['reserved_ns']>0 for v in other.writes))
        self.assertEqual(other.writes[-1]['reserved_ns'],0)
        self.assertEqual(other.writes[-1]['balance'],t.ledger.balance)

    def test_failed_stop_never_launches_other_identity(self):
        s,_,workers,_,_=self.make(duration=20)
        original=workers.__call__
        def spawn(command,session,clock):
            child=original(command,session,clock)
            def fail_stop(on_line):raise RuntimeError('not reaped')
            child.stop=fail_stop;return child
        s.worker_factory=spawn
        with self.assertRaisesRegex(RuntimeError,'not reaped'):s.run()
        self.assertEqual([v[0] for v in workers.history],['user'])

    def test_signal_handler_requests_cleanup_and_restores_prior_handler(self):
        signals={name:getattr(signal,name) for name in ('SIGINT','SIGTERM','SIGHUP') if hasattr(signal,name)}
        previous={number:signal.getsignal(number) for number in signals.values()}
        for name,number in signals.items():
            def fake_run(supervisor):
                signal.getsignal(number)(number,None)
                self.assertTrue(supervisor.stop_event.is_set());return 0
            with self.subTest(signal=name),patch.object(d.Supervisor,'run',fake_run):
                status=d.run_with_devfee(lambda *args:[],user_address='x',fee_percent=0,log=lambda _:None)
                self.assertEqual(status,128+number)
                self.assertEqual(signal.getsignal(number),previous[number])

    def test_shortened_cycle_requires_explicit_diagnostic(self):
        with self.assertRaisesRegex(ValueError,'diagnostic'):
            d.run_with_devfee(lambda *a:[],user_address='x',interval_seconds=10)
        for value in (-1,6,math.inf,math.nan,.12345):
            with self.assertRaises(ValueError):d.fee_ppm(value)

    def test_real_worker_lifecycle_and_current_session_activity(self):
        # Local Python subprocess only; no network, GPU, wallet or pool use.
        lines=[]
        code="import os,json,time;print('PMM_ACTIVITY '+json.dumps(dict(session=os.environ['PEARL_M_SESSION'],seconds=.01,tiles=1)),flush=True);time.sleep(30)"
        child=d.Worker([sys.executable,'-u','-c',code],'real-test')
        try:
            line=child.read(3);self.assertEqual(d.activity_ns(line,'real-test'),10000000)
        finally:child.stop(lines.append)
        self.assertIsNotNone(child.poll())

    def test_real_shutdown_with_broken_log_consumer_reaps_worker(self):
        # Real separate process/group, with unread output when its consumer
        # disappears. No network, miner or GPU is involved.
        gone=threading.Event();logs=[]
        def sink(line):
            if gone.is_set():raise BrokenPipeError('consumer closed its stdout pipe')
            logs.append(line)
        code="import time;print('queued shutdown output',flush=True);time.sleep(30)"
        s=d.Supervisor(lambda *args:[sys.executable,'-u','-c',code],coin='PRL',
            user_address='public-user',user_worker='user-worker',dev_address=d.DEFAULT_DEV_ADDRESS,
            ppm=0,interval_ns=3600*d.NS,store=None,time_limit=None,stop_event=threading.Event(),
            diagnostic=False,log=sink)
        s.start_worker('user');child=s.worker
        try:
            deadline=time.monotonic()+3
            while child.lines.empty() and time.monotonic()<deadline:time.sleep(.01)
            self.assertFalse(child.lines.empty(),'real child must have unread output before sink closes')
            gone.set();s.stop_worker()
            self.assertIsNone(s.worker);self.assertIsNotNone(child.poll())
            self.assertIsInstance(s.log_error,BrokenPipeError);self.assertTrue(s.stop_event.is_set())
            self.assertFalse(child.reader.is_alive())
        finally:
            if s.worker is not None:s.stop_worker()

    def test_real_shutdown_drains_after_arbitrary_on_line_exception(self):
        code="import time;print('one',flush=True);print('two',flush=True);time.sleep(30)"
        child=d.Worker([sys.executable,'-u','-c',code],'callback-failure')
        calls=[]
        def broken(line):
            calls.append(line);raise RuntimeError('injected output callback defect')
        try:
            deadline=time.monotonic()+3
            while child.lines.qsize()<2 and time.monotonic()<deadline:time.sleep(.01)
            self.assertGreaterEqual(child.lines.qsize(),2)
            child.stop(broken)
            self.assertIsNotNone(child.poll());self.assertFalse(child.reader.is_alive())
            self.assertGreaterEqual(len(calls),2);self.assertIsInstance(child.drain_error,RuntimeError)
        finally:
            if child.poll() is None:child.stop(lambda _:None)

    def test_already_closed_sink_does_not_start_detached_worker(self):
        s,_,workers,_,_=self.make()
        def gone(line):raise BrokenPipeError('closed before launch')
        s.log_sink=gone
        self.assertEqual(s.run(),1)
        self.assertFalse(workers.history);self.assertFalse(workers.live)

    def test_fake_callback_exception_cannot_skip_kill_escalation_and_wait(self):
        clock=Clock();worker=d.Worker.__new__(d.Worker)
        worker.clock=clock;worker.drain_error=None;worker.eof=threading.Event()
        worker.lines=d.queue.Queue();pending=['first','second'];signals=[];called=[]
        class Process:
            pid=1234567;code=None;waited=False
            stdout=type('Output',(),{'close':lambda self:None})()
            def poll(self):return self.code
            def send_signal(self,number):signals.append(number)
            def terminate(self):signals.append('terminate')
            def kill(self):signals.append('kill');self.code=-9;worker.eof.set()
            def wait(self,timeout):
                if self.code is None:raise AssertionError('wait before forced exit')
                self.waited=True;return self.code
        worker.process=Process()
        worker.reader=type('Reader',(),{'join':lambda self,timeout:None})()
        def read(timeout=.1):
            clock.advance(timeout)
            return pending.pop(0) if pending else None
        worker.read=read
        def callback(line):called.append(line);raise BrokenPipeError('fake sink disappeared')
        def killpg(pid,number):
            self.assertEqual(pid,1234567);signals.append(number)
            if number==signal.SIGKILL:worker.process.code=-9;worker.eof.set()
        with patch.object(d.os,'killpg',killpg,create=True):
            worker.stop(callback)
        self.assertEqual(called,['first','second'])
        self.assertTrue(worker.process.waited);self.assertIsInstance(worker.drain_error,BrokenPipeError)
        self.assertGreaterEqual(clock.now-1000,d.STOP_GRACE_SECONDS+1)
        self.assertGreaterEqual(len(signals),3)


if __name__=='__main__':unittest.main()
