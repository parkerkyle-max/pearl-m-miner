# Public Accelerate exact-integer SGEMM component benchmark

This measures **Accelerate SGEMM**, not PRL mining and not verified AMX execution.
No wallet, network connection, mining proof, or fee is involved.

On the target Mac, build and run:

```sh
clang++ -O3 -std=c++17 accelerate_exact.cpp -framework Accelerate -o accelerate_exact
VECLIB_MAXIMUM_THREADS=1 ./accelerate_exact --seconds 45 --size 512 --k 512 > cpu-one-thread.json
VECLIB_MAXIMUM_THREADS=4 ./accelerate_exact --seconds 45 --size 512 --k 512 > cpu-four-thread.json
```

The environment variable is a requested limit only; the benchmark does not claim
Accelerate honored it. Avoid `-ffast-math`; use the same binary and arguments for
CPU-only and GPU-concurrent measurements. Default duration is 60 seconds. Supported
flags: `--seconds`, `--size`, `--k`, `--seed`, `--help`.

Runtime-generated deterministic inputs are integers in [-2,2]. Products have
magnitude at most 4, so every possible partial dot-product sum has magnitude at
most `4*K` (at most 4096 for supported K). Those products and sums are exactly
representable in float32. A separate int64 scalar implementation checks **every
output cell** after warmup and after timing. It checks this fixture, not arbitrary
input ranges or Pearl prefix transcripts. Reusing the matrices deliberately
measures cached SGEMM throughput; it is not end-to-end changing-workload speed.

JSON distinguishes timed wall duration from complete process workload duration,
reports actual completed GEMMs, MAC/s, FLOP/s (two FLOPs per MAC), correctness,
and unverified AMX/thread-limit status. The duration can overshoot by one SGEMM.
Timing excludes initialization, the oracle, and two warmup calls. The final result
is observable and checked, preventing a discarded-output microbenchmark.

For a shared-power experiment, obtain an isolated GPU mining baseline, run this
component concurrently for a bounded window, and then repeat the isolated GPU
baseline. Compare GPU valid throughput over matched steady windows. These CPU
MAC/s **cannot** be added to pool PRL hashrate or earnings. Whole-machine power
needs a synchronized meter reading; this executable does not measure power.

Prepared on Windows. Native Accelerate compilation and execution must be verified
on the target Mac before treating any results as evidence.
