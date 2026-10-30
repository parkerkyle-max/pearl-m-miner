# Current S-prefix work model and remaining candidate

This document describes the existing integer/certificate-v3 route. It is not
an absolute bound across all possible algorithms or a future protocol fork.

One credited tile contains `h=2`, `w=64`, `K=4096`, `rank=128`.
`reference.difficulty_factor` is therefore `h*w*floor(K/rank)*rank = 524288`.

The S scan computes all 32 prefix matrices. Per tile this requires
`32 * 2 * 64 * 128 = 524288` scalar MACs, or **1048576 FLOPs** when one MAC/FMA
counts as two operations. Thus **1 PRL protocol-equivalent TH/s corresponds to
2 TFLOP/s of leading scan arithmetic** for this implementation.

At the pre-change baseline of approximately 3.927 TH/s, that is 7.854 TFLOP/s of scan work.
If a 10.4 TFLOP/s peak applies to the actual half-input/float-accumulation path,
the scan-only conditional ceiling is **5.2 TH/s**. At M16384/N65536 the X
preparation additionally performs `32*M*128*128` MACs per fresh grid, or
1024 MACs per credited tile when amortized across a fully scanned grid; stale
or partially scanned grids increase preparation per credited tile. Counting only these two matrix operations gives
`5.2 / (1 + 1024/524288) = 5.18986355 TH/s`.

Hashing, folding, conversions, validation, noise, commitments, task changes,
thermal/power limits and scheduling reduce an achievable result. A different
algorithm could change physical work per credited tile, so 5.2 is not a
proof of a universal Pearl upper bound. The 10.4 number and mixed-precision
applicability must be checked separately against primary sources/microbenchmarks.

## Existing features already cover several suggestions

- Noise sources and immutable fixed-B structures are cached by full job scope.
- `form_x` and `prefix_pair` already use half operands, float accumulation and
  compile-time `64x64x128` MPP matrix descriptors; K/rank/prefix count are fixed.
- Actual S/X half round trips and L1 accumulation bounds gate every generation.
  X is not assumed to remain in the raw input range -64..64.
- BLAKE3 arithmetic already uses `uint` (32-bit). The `ulong` operations are
  address indexing; changing them indiscriminately risks overflow for large grids.
- The difficulty check already starts at byte31 (most significant byte of a
  little-endian digest) and exits on the first unequal byte. Equality accepts.
- Register fold and full-guard unroll were already tested and lost performance.

## This experiment

`prefix_profile.mm` adds a diagnostic-only `pfx_profile_stages` ABI. It leaves
the production `pfx_scan` path unchanged and splits timing into combined,
GEMM+fold, and BLAKE3+target command buffers. It repeats immutable work, returns
no mining hits and does not advance/credit the miner. Device timestamps and
wall time are recorded; independent stage sums can differ from combined time
because of cache and scheduling effects. Component timing is not a roofline
proof or fresh-job mining performance.

Two exact shader candidates are also generated:

- `prefix_hash_unroll.metal`: seven BLAKE3 rounds with statically indexed
  message schedules, removing runtime permutation arrays.
- `prefix_hash_unroll_rotate.metal`: the same code plus Metal `rotate` for
  32-bit rotate-right (expressed as left rotation by `32-n`).

The compiler may already make these transformations. Benchmark them only
after independent transcript/digest and official-proof checks pass. They do
not omit any proof/hash/target operation, so later fresh-grid timing can compare
them fairly. No speed improvement has been established by generating this code.

## Parent-controlled commands on Mac

Stage the entire isolated folder; `prepare.py` is a Windows-side generator
and need not run on the Mac. Existing release Python supplies dependencies.

```sh
sh build.sh
python profile_stages.py --source /path/to/pearl-m-miner \
  --library ./libprefixprofile.dylib --shader ./prefix_baseline.metal \
  --cycles 6 --iterations 8 --output baseline-stages.json
```

For each candidate, first run the release's `check_sparse_native.py` with its
`--library` set to the diagnostic library and `--shader` set to the candidate,
`--method s`, and the release `--miner-root`/`--factory-root`. Also run its
production-dimension `--m 16384 --n 65536 --full-export-only` gate. Then repeat
the stage profile and the existing fresh-grid offline benchmark with identical
dimensions/dispatches. Keep the actual proof/hash path for all production
throughput comparisons. Parent owns pause/resume and external thermal guards.
