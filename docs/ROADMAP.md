# PRL first, then additional algorithms

Pearl M-Miner remains the Apple Silicon PRL backend. Further algorithms should
be separate, explicitly selected backends in a multi-device coordinator rather
than variations of the PRL proof code. This roadmap is not a compatibility,
performance or income claim.

| Stage | Work | Evidence required before claiming support |
| --- | --- | --- |
| Understand sustained PRL work | Expose preparation, scan, stale work, task updates and share observations | Consistent local counters; separately correlated pool replies |
| Improve PRL efficiency | Profile preparation/allocation, GPU dispatch and batch sizes; test one change at a time | Exactness/proof gates, matched baseline/candidate runs, temperatures and power scope |
| Qualify more M-series devices | Conservative shapes, explicit memory limits and per-device configuration | Exact chip/OS/build, offline correctness, timed fresh work and real pool acceptance |
| Add CPU XMR experimentally | Integrate a reviewed CPU backend while reserving resources for PRL host work | PRL-only, XMR-only and dual trials; accepted shares, lost PRL work and whole-machine power |
| Add further algorithms | Separate backend, pool dialect, public payout address and qualification per algorithm | Correctness, lifecycle, thermal/resource and real-pool evidence for each supported route |

XMR is a candidate for the CPU stage because [XMRig documents macOS and ARMv8
CPU support](https://xmrig.com/docs/miner), and [Monero describes CPUs as more
efficient for RandomX mining than GPUs](https://www.getmonero.org/get-started/mining/).
Those capabilities do not establish a net benefit when run alongside PRL on
this Mac. The paired resource and power measurements remain required.

## Current local qualification

The Alpha 3 32-row MPP subblock backend passed offline proof/production-path
checks and sustained 4.2347 PRL TH/s for 300 seconds on this M1 Max. Two shorter
matched trials averaged 7.82% above the existing Alpha 2 S-prefix backend.
The exact candidate is now deployed locally after another official self-test
and a 45-second CLI recheck, and the original Kryptex worker has resumed.
A bounded new Kryptex user session recorded one accepted and zero rejected
shares, bound to the deployed build and matching gzip submission in the
[live receipt](data/m1-pair32-live.json). This verifies acceptance, not precise
pool rate or income. The Alpha 3 release includes this backend. Other M chips need
their own measurements. Next optimization
decisions should use the measured matrix
ceiling, full-work timings and correctness gates in [the M1 Max report](M1_CEILING_20261030.md),
including unsuccessful controls, rather than advertised TOPS alone.

A separate bounded coexistence experiment ran public Accelerate `cblas_sgemm`
alongside GPU mining work. It measured about **1.06 TFLOP/s** of CPU-side API
matrix throughput; complete output checks before and after timing matched the
integer reference for that fixture. This does **not** identify the executing
hardware as AMX, validate arbitrary mining inputs, or establish credited CPU PRL
work. It is a contention/feasibility experiment, not an implemented CPU PRL
backend or an additional-income result. A CPU PRL route would still need fresh
work, all transcript/hash/proof stages and pool acceptance before comparison.

## Observations used for optimization

During active mining, the worker emits a compact `PMM_TELEMETRY` JSON record
approximately every 30 seconds, after a completed loop iteration. A blocked GPU
call or thermal pause can delay reporting; the log is not an independent
liveness watchdog. The usual human-readable line also includes local PRL TH/s.

The `pearl-m-telemetry-v1` schema separates:

- `local_rate`: measured tile rates converted with the protocol work per tile;
  the rolling window is 60 seconds, while the session average covers the worker
  session. These are not the pool's effective-rate estimate.
- `shares`: submitted, accepted, rejected and pending counts for this worker.
- `jobs`: processed notification count, adopted-update count and monotonic ages.
  Duplicate notifications can raise the received count without changing the
  adopted count. Ages describe processing by the mining loop, not wire arrival.
- `native`: a bounded set of cumulative timing/work counters plus deltas since
  the previous report. The first delta, missing values, counter resets and
  non-forward clock intervals are `null`, not zero. Timing stages overlap and
  must not be added together. Stale discarded tiles stay separately visible.

`pool_effective_hs` remains `null`: it must come from a separately attributed
pool observation. A session identifier allows correlation with the existing
user/developer session logs. The record contains no wallet address or endpoint.
This telemetry does not contribute fee credit or alter proof/target processing.

## Shared runtime, separate algorithm claims

Future integrations can share discovery, owned-process lifecycle, thermal and
battery policy, configuration checks, telemetry and fee accounting. PRL's
matrix/transcript optimization is algorithm-specific; other coins need their
own computation and verification paths. Apple Neural Engine remains unqualified.

CPU and GPU jobs on an M-series Mac share memory bandwidth, power and cooling.
An additional CPU workload must be evaluated against the PRL work it displaces.
Compare total value only with explicit price/time/fee assumptions and measured
power. H/s from different algorithms, MAC/s and pool/local duplicate observations
must never be added to advertise a combined hashrate.

Use one disclosed project fee scheduler. A coordinator must explicitly disable
the child project's fee and verify the resulting user/developer routes. Existing
active-scan-time and scheduled-wall-time policies are different and must not be
silently substituted; external backend and pool fees remain separate. A missing
coin-specific developer destination is an unconfigured route.

No target speed, release date, gain on an untested chip, or profitable dual-mining
configuration is promised. Keep failed controls and publish only reproducible,
sanitized evidence.
