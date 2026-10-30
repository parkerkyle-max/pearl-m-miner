# M2 qualification experiments

These experiments qualify one **10-core-GPU Apple M2, 24 GiB, MacBook Pro,
macOS 27.0**. They do not qualify the entire M2 family. See the
[report](../../../docs/M2_VALIDATION_20261030.md) and
[sanitized measurements](../../../docs/data/m2-validation-20261030.json).

## Exact sources

- Pearl M-Miner: `v0.1.0-alpha.3`, commit
  `4e01cf91ae492d4ce9b262d32a80774ec941e0fc`.
- Upstream pearl-metal-miner 0.2.4:
  `3d4cc7dadbd1de98ba20e9beb162806a0e70266b` from
  [Breakwater-ecosystem/pearl-metal-miner](https://github.com/Breakwater-ecosystem/pearl-metal-miner).
- Official proof extension:
  `3c84be9fb4b2b279967ad3f9f74e67fb8c9cce30`.

`upstream-cert3-compat.patch` changes the upstream Python protocol/host/self-test
paths for certificate v3 and adds precise benchmark JSON. The control uses the
**unchanged upstream GPU kernels and native library**. It is not advertised as
an unmodified end-to-end upstream release. The original cert2 synthetic test is
retained in the data as historical context, not the primary matched control.
The source/build receipt includes hashes of both the patch and native inputs.

Use separate source directories. Build Pearl M-Miner using its documented
bootstrap and run the self-test first. For the control, check out the exact
upstream commit, apply this patch with `git apply`, build
`sh packaging/build_macos.sh`, and use the same arm64 Python environment and
pinned official proof extension. Do not overwrite your production miner.

## Matched fresh-work comparison

From the upstream control directory, using the prepared Python environment:

```sh
python -m pearl_metal_miner.miner --benchmark --benchmark-seconds 300 \
  --m 8192 --n 16384 --region-rows 512 --cpu-threads 2 \
  --no-notify --no-dashboard
```

From the Pearl M-Miner directory:

```sh
.venv/bin/pearl-m-miner self-test
.venv/bin/pearl-m-miner benchmark --seconds 300 \
  --m 8192 --n 16384 --region-rows 512 --cpu-threads 2
```

Both use K=4096, rank=128 and 524288 reported PRL work units per tile. Warmup is
excluded from the measurement window. Each benchmark creates fresh nonce grids;
neither is a repeated-buffer matrix microbenchmark or a pool-income measurement.
Keep AC power, record thermal behavior, and do not run both GPU tests at once.

## Tuning and arithmetic reference

The evidence retains the tested N=16384/32768/65536 shapes, the larger
M=16384/N=65536 shape, region sizes 256/512/1024, and the 16/32/64-row kernel
experiments. Changing matrix size is not the same as changing the algorithm's
K or rank; those protocol parameters were held constant.

Candidate shaders must first pass `tools/prefix_s_miner/check_sparse_native.py`
with `--method s`, the candidate `--shader` and built `--library`. The
`candidate_benchmark.py` wrapper is offline-only and accepts explicit M/N.
The retained-generation, precision and official-proof gates must not be skipped.

The arithmetic reference uses the existing [peak tools](../ceiling/peak):

```sh
sh research/2026-10-30/ceiling/peak/build.sh
research/2026-10-30/ceiling/peak/peak --mode float \
  --shader research/2026-10-30/ceiling/peak/peak.metal \
  --groups 512 --simdgroups 4 --chains 4 --warmup 10 --seconds 300 \
  --output peak-float-300.json
```

The denominator counts two operations per completed MAC. GPU-timestamp and
wall-time TFLOP/s are distinct. Integer fixtures include 3969, mixed signs and
the 2^24 boundary; passing those fixtures is not a proof for all legal inputs.
Different matrix geometry can have a different ceiling. The reported direct-
arithmetic reference is not a universal bound on every future PRL algorithm.

## Pool trial and power boundaries

Use your own public address for pool trials. The miner must never receive a
seed, private key or wallet password. The test plans and receipts distinguish
the offline timing window from bounded pool sessions; a small share count is
not a precise pool-rate estimate. The default optional 1% contribution was not
turned into a claim of measured net income.

The first full-duty live attempt hit the lab's 95°C average-sensor guard after
about 119 seconds (2 accepted, 0 rejected). The equal 600-second retry windows
use `--intensity 80` on both miners. Intensity is a scheduling control, not a
guarantee of proportional hashrate. Keep this thermal stop with the evidence;
do not present the intensity-100 offline result as the sustained live result.

Software telemetry is from macmon 0.10.0, sampled once per second and aligned
to the timed window using UTC timestamps. It is not outlet-meter power.
The independent lab supervisor required AC, stopped at serious/critical OS
thermal pressure or a 95°C average CPU/GPU sensor, and reaped only its owned
test processes. That extra lab guard is not a claim that the shipped miner has
a calibrated 95°C temperature setting. User applications were left running;
the pre-test check found no material idle GPU workload or swap.
