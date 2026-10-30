# PRL device validation and optimization roadmap

Pearl M-Miner prioritizes verified PRL mining on specific Apple Silicon
configurations. The [device results matrix](../README.md#device-results) and
[machine-readable results](device-results.json) distinguish measured devices,
planned tests and model slots whose availability is not confirmed. This roadmap
does not promise support, performance, income or a delivery date.

| Priority | Work | Evidence required before claiming support |
| --- | --- | --- |
| 1. Complete the released M1–M6 device validation matrix | Obtain access to released models and test their exact GPU-core, memory and OS configurations; retain failures and untested entries | Source-bound build and correctness checks, timed fresh-work benchmarks, bounded pool acceptance and published limitations for each configuration |
| 2. Optimize each available device in small steps | Once a specific Mac is available, profile its actual bottlenecks and compare one kernel, shape, dispatch or preparation change at a time | Matching baseline/candidate conditions, exactness and proof gates, repeatable full-work gains, thermal observations and separate pool validation; retain the baseline when no gain is established |
| 3. Validate sustained pool operation and thermal behavior | Extend runs, observe job changes, reconnects, stale work, fee transitions, battery/thermal pauses and recovery | Dated duration and accepted/rejected/pending counts, correlated pool replies, temperature history and clear software-versus-outlet power scope |
| 4. Improve source installation and build diagnostics | Reproduce setup on additional Macs; clarify compatible SDK/Python/Rust requirements and actionable build/self-test errors | Recorded environment and cache state, reproducible setup steps and actual build/self-test outcomes; distinguish fresh environments from reused toolchains |
| 5. Make benchmarks reproducible and accept community corrections | Publish commands, timing definitions, baselines and sanitized evidence; reconcile reported discrepancies with the device matrix | Traceable source/version and measurement windows, preserved conflicting results and corrected claims with evidence links |
| Later experimental work: CPU and additional algorithms | Evaluate a complete CPU PRL path or separately selected coin-specific backends while reserving resources for PRL host work | Per-backend correctness and pool acceptance, PRL-only/CPU-only/combined trials, displaced PRL work and measured whole-machine power |

The M1–M6 headings organize the test plan; they do not imply that every family
has released ordinary, Pro, Max and Ultra models. Only released configurations
enter the hardware qualification queue. Unconfirmed model slots remain labeled
as such in the matrix. A passing result on one GPU-core count or memory size
does not qualify every variant with the same chip name.

Optimization decisions are device-specific. Shared Metal APIs or family names
do not establish identical GPU architectures, resource limits or useful tuning
parameters across M1–M6. An available device and a repeatable matched test are
required before claiming an improvement; unsuccessful candidates stay in the
record and do not replace the measured baseline.

Use the [device result form](https://github.com/parkerkyle-max/pearl-m-miner/issues/new?template=device-result.yml)
for a new build or benchmark result, or the
[benchmark discrepancy form](https://github.com/parkerkyle-max/pearl-m-miner/issues/new?template=benchmark-discrepancy.yml)
to question an existing number, comparison or description. A concern can be
reported without a replacement benchmark or a successful local build.

XMR is a longer-term experimental candidate because [XMRig documents macOS and ARMv8
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
pool rate or income. The Alpha 3 release includes this backend. A later test of
the unchanged Alpha 3 source on a 10-core-GPU M2 with 24 GiB memory measured
1.4652 PRL TH/s over 300 offline seconds. Its matched upstream control, bounded
80%-intensity pool trials and full-duty thermal stop are recorded in the
[M2 report](M2_VALIDATION_20261030.md). Other configurations need their own
measurements. Next optimization
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
