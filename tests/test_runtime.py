"""No GPU/network: payout isolation, RAM profiles and safety state behavior."""
import contextlib
import io
import json
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from pearl_m_miner import cli, safety
from pearl_metal_miner.wallet import encode_address


class RuntimeTests(unittest.TestCase):
    def args(self, *extra):
        return cli.build_parser().parse_args(['mine','--address','krxAbCdEf12',*extra])

    def test_kryptex_case_is_preserved_only_for_that_pool(self):
        args=self.args('--pool','kryptex');cli.validate_identity(args)
        self.assertEqual(args.address,'krxAbCdEf12')
        with self.assertRaises(ValueError):cli.validate_identity(self.args())

    def test_invalid_username_separators_and_nonascii_refused(self):
        for text in ('krxABC.x','krxABC\n','krx你好ABC','krxA/B','krxABC@x','KRXabcd'):
            args=self.args('--pool','kryptex');args.address=text
            with self.assertRaises(ValueError):cli.validate_identity(args)

    def test_native_address_validated_both_pools(self):
        for pool in cli.POOLS:
            args=self.args('--pool',pool);args.address=encode_address(bytes(32))
            cli.validate_identity(args)
            args.address=args.address[:-1]+'x'
            with self.assertRaises(ValueError):cli.validate_identity(args)

    def test_worker_separators_rejected(self):
        for text in ('two words','x.y','a/b','é','x\n'):
            args=self.args('--pool','kryptex');args.worker=text
            with self.assertRaises(ValueError):cli.validate_identity(args)

    def test_auto_shapes_match_only_measured_large_hardware(self):
        for chip,mem,expected in [('Apple M1 Max',64,(16384,65536)),
                                  ('Apple M1 Max',32,(8192,16384)),
                                  ('Apple M2',64,(8192,16384)),
                                  ('Apple M1',8,(8192,16384))]:
            args=self.args();cli.apply_profile(args,{'chip':chip,'memory_bytes':mem*(1<<30)})
            self.assertEqual((args.m,args.n),expected)

    def test_dev_route_cannot_inherit_user_identity_or_endpoint(self):
        args=self.args('--pool','kryptex','--host','user.example','--port','1234')
        cli.apply_profile(args,{'chip':'Apple M1','memory_bytes':8*(1<<30)})
        cmd=cli.build_worker_command(args,'DEV_ADDRESS','devworker','dev')
        self.assertEqual(cmd.count('--address'),1)
        self.assertEqual(cmd[cmd.index('--pool')+1],'luckypool')
        self.assertEqual(cmd[cmd.index('--host')+1],'pearl-cpu-eu1.luckypool.io')
        self.assertEqual(cmd[cmd.index('--port')+1],'3370')
        self.assertNotIn('user.example',cmd);self.assertNotIn(args.address,cmd)
        self.assertNotIn('--time-limit',cmd)

    def test_thermal_pause_resume_and_invalid_state(self):
        values=iter([2,3,1]);sleeps=[]
        with contextlib.redirect_stdout(io.StringIO()) as output:
            safety.wait_until_safe(lambda:next(values),sleep=sleeps.append)
        self.assertEqual(sleeps,[2,2]);self.assertIn('thermal-recovered',output.getvalue())
        with self.assertRaises(RuntimeError):safety.wait_until_safe(lambda:-1,sleep=sleeps.append)

    def test_activity_has_session_and_no_nonfinite_credit(self):
        with patch.dict(os.environ,{'PEARL_M_SESSION':'unit-session','PEARL_M_ACTIVITY':'1'}):
            with contextlib.redirect_stdout(io.StringIO()) as output:safety.activity(.123,64)
        record=json.loads(output.getvalue().split(' ',1)[1])
        self.assertEqual(record['session'],'unit-session');self.assertEqual(record['seconds'],.123)
        with self.assertRaises(RuntimeError):safety.activity(float('nan'),64)

    def test_battery_queries_are_cached_ac_and_fast_during_pause(self):
        now=[0.0];calls=[];source=['ac']
        def read():calls.append(now[0]);return source[0]
        battery=safety.BatteryPoller(read,clock=lambda:now[0])
        self.assertFalse(battery.on_battery())
        source[0]='battery'
        # Frequent GPU scans must not spawn a subprocess on every iteration.
        for i in range(1,2000):
            now[0]=i/100
            self.assertFalse(battery.on_battery())
        self.assertEqual(calls,[0.0])
        now[0]=20.0;self.assertTrue(battery.on_battery())
        source[0]='ac'
        now[0]=21.9;self.assertTrue(battery.on_battery())
        now[0]=22.0;self.assertFalse(battery.on_battery())
        for i in range(2201,4200):
            now[0]=i/100;self.assertFalse(battery.on_battery())
        self.assertEqual(calls,[0.0,20.0,22.0])
        now[0]=42.0;self.assertFalse(battery.on_battery())
        self.assertEqual(calls,[0.0,20.0,22.0,42.0])


if __name__=='__main__':unittest.main()
