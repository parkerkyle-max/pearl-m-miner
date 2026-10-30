# M2 qualification and matched comparison — 2026-10-30

**The existing Alpha 3 backend works on this tested M2 configuration, with a
thermal qualification limit.** We kept the 32-row kernel and default
M=8192/N=16384/region=512 settings. The full-duty live attempt hit the lab's
95°C guard, so the equal-duration live comparison uses **80% intensity**.
The full-duty offline headline must not be presented as a sustained live rate.
This update adds device evidence and operating guidance; it does not change or
retag Alpha 3 code.

![M2 matched comparison](../assets/m2-comparison.png)

## Device, build and fairness

- Apple M2, 10 GPU cores, 24 GiB unified memory, MacBook Pro Mac14,7,
  macOS 27.0, native arm64 Python 3.12, AC power, low-power mode off.
- Fresh repository-local virtual environment and native source build. Existing
  Rust/toolchain/cache state was reused: this is not an empty-machine build.
- Command Line Tools with SDK 27.0 built the runtime shader path successfully.
  A standalone `xcrun metal` executable was unavailable and was not needed by
  this build. A compatible SDK/runtime and clang++ remain required.
- No unrelated applications were stopped. Idle GPU use was about 2–3.5%, no
  swap was observed, and no material competing GPU job was found. This was a
  real desktop test, not a claim of a perfectly isolated laboratory system.
- Pearl M-Miner source: `4e01cf91ae492d4ce9b262d32a80774ec941e0fc`.
  Upstream 0.2.4: `3d4cc7dadbd1de98ba20e9beb162806a0e70266b`.
  Both used proof commit `3c84be9fb4b2b279967ad3f9f74e67fb8c9cce30`.
- The upstream control adds certificate-v3 seed/proof/session compatibility and
  precise timing output. **Its native GPU kernels/library are unchanged.** The
  complete patch and hashes are published. Original unpatched cert2 synthetic
  trials are retained separately and are not the primary current-protocol result.

## Matched 300-second fresh-work measurements

Both miners use M=8192, N=16384, K=4096, rank=128, region=512, two CPU helpers
and intensity 100. They ran sequentially, with separate warmup excluded. Both
include fresh nonce-grid preparation, but exclude pool networking and
hit-triggered proof construction. One tile is 524288 protocol work units.

| Miner | Measured duration | Local protocol rate | Software system power |
| --- | ---: | ---: | ---: |
| pearl-metal-miner 0.2.4 + cert3 patch | 300.004 s | 0.406127 TH/s | 20.58 W |
| Pearl M-Miner Alpha 3 default | 300.021 s | **1.465227 TH/s** | 26.11 W |

The local throughput ratio is **3.608× (+260.78%)**.
This comparison is against the named upstream GPU implementation, **not Pearly**.
Power is macmon 0.10.0 software telemetry aligned to the measurement interval,
not an outlet meter. Wall efficiency, electricity cost and paid income remain
unmeasured. GPU-average temperature in the default run peaked at
92.3°C; no swap was observed.

At an ideal steady 1% developer scan-time allocation, `local_rate × 0.99`
would give **1.450575 TH/s** of user capacity,
257.17% above the zero-dev-fee control. This is
only a capacity model: pool fees, stale work, payout difficulty, proof overhead
and the activity-based schedule prevent treating it as a measured income gain.
The bounded sessions do not establish a complete normal 3564/36-second fee cycle.
The live qualification below uses 80% intensity because of the full-duty thermal
stop; its user capacity is lower than the full-duty offline model above.

## Tuning attempts retained, including the non-winners

| Trial | Measured duration | Local TH/s | Software W |
| --- | ---: | ---: | ---: |
| `pair16-bench` | 60.02 s | 1.403640 | 27.22 |
| `pair64-bench` | 60.05 s | 1.309244 | 25.70 |
| `pair32-control` | 60.01 s | 1.465868 | 26.44 |
| `cert3-control-a` | 120.01 s | 0.386943 | 20.59 |
| `auto-control-a` | 45.03 s | 1.410009 | 26.05 |
| `n32768` | 45.08 s | 1.436034 | 26.72 |
| `n65536` | 45.02 s | 1.459368 | 26.86 |
| `max-shape` | 45.17 s | 1.454270 | 26.72 |
| `region256` | 45.01 s | 1.399256 | 24.51 |
| `region1024` | 45.01 s | 1.459589 | 26.09 |
| `auto-control-b` | 45.02 s | 1.460922 | 25.96 |
| `cert3-control-b` | 120.02 s | 0.389192 | 20.49 |

The initial 45-second default control was 1.410009 TH/s and the later control
was 1.460922 TH/s. That drift is as large as the apparent benefit of increasing
N or region size. The best larger-shape/region results did not beat the later
default control. Therefore a few percent from a single short trial is not
promoted as an optimization. Kernel alternatives have their own proof gates and
timings above. No unproven candidate replaced the production kernel.

One lab attempt failed before timing because a coordinator named `queue.py`
shadowed Python's standard library. Renaming the coordinator fixed the harness;
the failed receipt is retained, and the retry is separately identified. This
was not an arithmetic rejection and contributed no performance sample.

## What is the M2 arithmetic ceiling?

The [Metal Benchmarks microarchitecture research](https://github.com/philipturner/metal-benchmarks)
lists a 10-core M2 model at 1.398 GHz. The model calculation is:

```text
10 GPU cores × 128 lanes × 2 operations/FMA × 1.398 GHz = 3.57888 TFLOP/s
3.57888 / 2 = 1.78944 PRL TH/s for this direct prefix-scan arithmetic
```

This is a **conditional algorithm-specific reference**, not an Apple-published
mining specification or a proof that no future PRL algorithm can do better.
The current scan performs 1048576 main matrix floating-point operations per
tile while the reporting convention credits 524288 PRL work units. Hashing,
preparation, proof generation, memory access, dispatch and cooling consume
additional resources. Algebraic reuse or a different valid algorithm can change
that relationship; CPU/ANE acceleration would require separate validation.

The 300-second float matrix microbenchmark measured
**3.320770 GPU TFLOP/s** and
**3.257120 wall-time TFLOP/s**. Dividing these by two gives
arithmetic-equivalent references, not pool rates. Short half/float/MPP trials
and exact integer fixtures are also retained. The MPP microbenchmark uses a
different tile geometry, so its lower result is not a universal miner ceiling.
We do not label a cross-workload ratio as literal GPU utilization.

## Correctness and bounded pool evidence

The release passed 28 official proof checks. The actual default production
dimensions also passed their official-proof brackets, and 512 independent
transcript/digest/target checks covered the production non-export scan path.
The source/build hashes bind those checks to the installed Alpha 3 backend.

The initial 100%-intensity live run stopped at the lab's conservative 95°C
average-sensor guard after about 119 seconds, with **2 accepted / 0 rejected**.
It had not completed the requested ten minutes and is not counted as a successful
full-duration trial. This was a lab thermal stop, not an arithmetic failure or
a manufacturer-defined damage threshold. The shipped miner's thermal-pressure
policy is distinct from the lab's Celsius guard. OS-controlled fans responded
slowly to the load increase; we did not override fan control or raise the guard.

After cooldown, both repeated live tests used **80% intensity**, the same
LuckyPool CPU entrance, distinct test workers and
the same owner-controlled public PRL address. Recovery secrets were not supplied.
The test identity is omitted from the public evidence. These are log-observed
verdicts, separately checked against the pool API where indicated in the receipt.

| Miner | Requested window | Final cumulative local TH/s (rounded) | Software W | Peak GPU-average °C | Accepted / rejected |
| --- | ---: | ---: | ---: | ---: | ---: |
| Pearl M-Miner Alpha 3 | 600 s | 1.0376 | 19.95 | 85.1 | 3 / 0 |
| Upstream 0.2.4 + cert3 compatibility | 600 s | 0.3051 | 16.37 | 80.1 | 1 / 0 |



Small accepted-share counts establish protocol compatibility when nonzero; they
do not measure precise pool hashrate or guarantee payment. The trial workers
were stopped after the bounded test. No mining autostart or user-app shutdown
was installed. The M1 Max production miner was not changed by this experiment.

The cumulative live rates are each miner's rounded final session average,
including real job/proof/network interruptions. They are not a dashboard rate;
the upstream and final prefix paths can differ at the stale-scan boundary.
Use the precisely timed offline table for the primary matched throughput ratio.
Live software power averages cover each full process phase, including startup.
The live sessions ran sequentially and did not start at identical temperatures
or fan speeds, so this is not a controlled cooling-system comparison.
These ten-minute samples do not establish overnight thermal or uptime stability.
Local verification failures are recorded separately in the JSON evidence.

For this tested laptop, start a bounded live trial conservatively:

```sh
.venv/bin/pearl-m-miner mine --pool luckypool \
  --address YOUR_PUBLIC_PRL_ADDRESS --worker my-m2 \
  --intensity 80 --time-limit 600
```

The 80% setting is explicit operating guidance, not a new automatic M2 default.
Cooling, ambient conditions and other workloads can differ on another machine.

## Reproduction and scope

- [Machine-readable measurements and source hashes](data/m2-validation-20261030.json)
- [Control patch, plans, sanitized logs and power samples](../research/2026-10-30/m2)
- [Compatibility table](COMPATIBILITY.md) · [M1 Max report](M1_CEILING_20261030.md)
- [Search/AI publication methods and their limits](DISCOVERABILITY.md)

Only this 10-core M2/24 GiB/macOS 27.0 configuration is newly qualified. M2 Pro,
Max, Ultra, 8-core M2, other memory sizes and M3–M5 remain unmeasured here. The
immutable Alpha 3 CLI `info` metadata predates this supplementary test and still
names M1 Max; the dated compatibility table and this report provide the later
evidence. The original tag and computational source are deliberately unchanged.
