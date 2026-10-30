# Optional 1% developer support

Pearl M-Miner is Apache-2.0 open source. Its default developer contribution is **1% of completed, valid GPU scan time**. We ask users and redistributors to preserve this support and its visible disclosure because ongoing device testing and correctness maintenance take time. This is a voluntary request, not a license condition. Use `--dev-fee 0` to disable it explicitly.

## What is counted

The runtime reports the native wall duration of each completed region only when that region remains valid for its job. The normal schedule is 3564 active seconds for the user's identity, then 36 active seconds for the developer identity. Region-boundary overshoot is carried forward rather than rounded away.

Startup, compilation, connecting, waiting for a job, disconnection, battery/temperature pauses and stale scans do not create new billable activity. Consequently “1%” is not a claim of exactly 36 wall-clock seconds per hour, exactly 1% of accepted shares, or exactly 1% of revenue. Pool fees are separate. Reconnecting and rebuilding pool work can reduce useful throughput, and the release should be assessed end to end.

The first launch starts with user work. Scheduler state is persisted across restarts, so routine restarts do not reset an earned developer allocation or charge it twice. User and developer roles are disclosed in the logs.

On macOS, the state lives under `~/Library/Application Support/PearlM-Miner/` in a `contribution-<identity-and-settings-hash>.json` file. An operating-system lock prevents concurrent owners. State is capped at 4096 bytes, checkpointed every five seconds, and atomically written and synchronized at switches and exit. A crash can lose at most the uncheckpointed user credit, which favors the user. Before developer work, the scheduler reserves a bounded window; an uncertain remainder after a crash is not charged again. `--dev-fee 0` creates no contribution state. After the state lock is acquired, state-read or checkpoint failures disable the contribution for that run rather than guessing an amount to charge. Failure to acquire the lock aborts startup to prevent concurrent owners.

## Separate identities and failure handling

The public developer PRL address is:

```text
prl1pwjessemugthkad9hkttcx2rvenux2q0w0xcah2j0a7zfrycjhz5qhn7apw
```

`pearl-m-miner info` or `info --json` displays the configured address and route
offline. Developer work uses `pearl-cpu-eu1.luckypool.io:3370`; your own rewards
follow your separate `--address`. See [wallet and payout visibility](WALLET_AND_PAYOUTS.md).

Developer work uses the project's disclosed public PRL receiving identity through LuckyPool, even if the user selected another supported pool. The previous worker is stopped and reaped before the next identity starts. Sessions, jobs and proofs are not shared across payout identities.

If the developer pool fails, including 90 seconds without valid activity or reaching the developer-window cap, the runtime returns to user work. Retry backoff starts at 300 seconds. Deferred developer activity is capped to one cycle rather than accumulated into an arbitrarily long later charge. The user's pool endpoint is not silently rewritten into the developer endpoint.

No wallet private key or recovery phrase is required. A public payout address provides a destination, not control over the wallet. The compiled source and runtime disclosure are the authority for the configured developer route.

## Evidence boundaries

The published 3.869 TH/s M1 Max research result was measured before this release scheduler was enabled. It demonstrates the backend, not an entire fee cycle. Do not subtract 1% from a noisy pool-share count and call that measured net revenue, or multiply a user-only accepted-work measurement by 0.99 again.

A release check must independently cover user/developer switching, persisted state, overshoot, worker cleanup and failure recovery. A short live session that never reaches a developer interval does not prove developer payout acceptance. Any completed live routing validation should be reported with its actual duration and counts, separately from unit tests and the original backend trial.

The implementation is [pearl_m_miner/devfee.py](../pearl_m_miner/devfee.py). Accelerated diagnostic cycles belong to the test harness; normal installation commands use the disclosed production schedule.

The first release passed 48 CPU tests and accelerated same-pool and cross-pool lifecycle trials. The cross-pool trial used distinct public identities and returned to the user after developer work. Its developer window produced no accepted share; a full production cycle and actual developer-wallet credit remain unverified. [Exact release evidence](RELEASE_VALIDATION.md).
