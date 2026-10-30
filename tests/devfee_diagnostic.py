#!/usr/bin/env python3
"""Explicit accelerated pool lifecycle test, never the normal mining schedule.

After bootstrap and self-test, from the release root:
  python tests/devfee_diagnostic.py --state-path /new/diag-state.json \
    --cycle-active-seconds 60 --wall-seconds 180 -- mine --pool luckypool \
    --address YOUR_PUBLIC_PRL_ADDRESS --worker m1-fee-diagnostic

Requires a fresh state path; prints a receipt only after every worker is reaped.
The fee percentage stays 1%; only this explicit test's active cycle is shortened.
No accepted-share or production-performance claim follows from a lifecycle pass.
"""
import argparse
import json
import os
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from pearl_m_miner import cli
from pearl_m_miner.devfee import run_with_devfee


def main():
    p=argparse.ArgumentParser(description=__doc__,allow_abbrev=False)
    p.add_argument('--state-path',type=Path,required=True)
    p.add_argument('--cycle-active-seconds',type=float,default=60)
    p.add_argument('--wall-seconds',type=float,default=180)
    p.add_argument('miner_args',nargs=argparse.REMAINDER)
    options=p.parse_args()
    options.state_path=options.state_path.resolve()
    if options.state_path.exists():p.error('fresh diagnostic state path required')
    if not 1<=options.cycle_active_seconds<=300:p.error('diagnostic cycle must be 1..300 active seconds')
    if not 10<=options.wall_seconds<=300:p.error('diagnostic duration must be 10..300 wall seconds')
    rest=options.miner_args
    if rest[:1]==['--']:rest=rest[1:]
    args=cli.build_parser().parse_args(rest)
    if args.command!='mine' or args.dev_fee!=1:p.error('diagnostic requires mine with default 1% contribution')
    cli.validate_identity(args);details=cli.preflight();cli.apply_profile(args,details)
    os.chdir(cli.ROOT)
    from pearl_m_miner.validation import require_validated
    require_validated(cli.ROOT,details)
    os.environ['PEARL_M_ACTIVITY']='1'
    sessions=[]
    def log(line):
        print(line,flush=True)
        if line.startswith('PMM_DEVFEE_SESSION '):sessions.append(json.loads(line.split(' ',1)[1]))
    code=run_with_devfee(lambda address,worker,role:cli.build_worker_command(args,address,worker,role),
        user_address=args.address,user_worker=args.worker,fee_percent=1.0,
        interval_seconds=options.cycle_active_seconds,state_path=options.state_path.resolve(),
        time_limit=options.wall_seconds,diagnostic=True,log=log)
    active=[s for s in sessions if s['active_seconds']>0 and s['reaped']]
    sequence=[s['role'] for s in active]
    passed=any(sequence[i:i+3]==['user','dev','user'] for i in range(max(0,len(sequence)-2)))
    print('PMM_DEVFEE_DIAGNOSTIC '+json.dumps(dict(passed=passed,exit_code=code,
        accelerated=True,cycle_active_seconds=options.cycle_active_seconds,
        sessions=sessions,scope='lifecycle and valid scan activity only; check pool replies separately')),flush=True)
    return code if code else (0 if passed else 1)


if __name__=='__main__':raise SystemExit(main())
