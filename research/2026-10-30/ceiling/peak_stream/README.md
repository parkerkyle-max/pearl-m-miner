# Varying-operand matrix control

This is a separate control for the `peak` repeated-operand microbenchmark.
Every inner iteration reads a distinct preallocated runtime A/B matrix pair.
There are no cyclic slots or modulo reuse inside a dispatch. All products
contribute to final outputs, and the CPU-int64 oracle sums the actual products
across the sequence. Multiplying the first product by the iteration count
fails the included varying-input fixture.

This removes the particular invariant-AB hoisting opportunity. It does not
constitute an ISA audit or prove a register-only hardware ceiling. Fresh
operand loads make it a **memory-plus-compute control**. The 8×8 path in
particular may be bandwidth limited; do not call its lower rate the GPU's
arithmetic limit.

No SSH, pool, wallet, service or GPU execution is performed by source creation.
Run only under the parent's existing temperature/deadline supervision, with the
production GPU miner paused and restored afterward. The executable also checks
macOS thermal pressure before each bounded dispatch. As with `peak`, the 250 ms
limit is observed after completion, not preemption.

## Layout and counts

- A: `[sets, allocated_iterations, M, K]`.
- B: `[sets, allocated_iterations, chains, N, K]`, used transposed.
- Output: `[sets, chains, M, N]`, summing every requested iteration.
- 8×8: `sets=groups*SIMDgroups`, `M=N=K=8`.
- MPP: `sets=groups`, `M=N=64`, `K=128`, `chains=1`; four SIMDgroups cooperate.
- MACs/dispatch = `sets*chains*M*N*K*iterations`; FLOPs are twice that.

`--iterations` is fixed 1..512, default 32. No auto-increase occurs because the
unique sequences are allocated before execution. `--target-ms` is deliberately
unsupported. Input allocation/oracle state is capped at 2 GiB of CPU storage;
Metal buffers consume additional memory. The JSON separately records logical
input bytes and output bytes per dispatch. Actual cache/memory traffic is not
measured by those logical counts.

The small runtime fixture uses varied nonzero values in `{-2,-1,1,2}` with a
distinct iteration-dependent seed. Constant 63, 127, mixed-sign 127 and 64 boundary
fixtures use the same paths and full output verification, reducing the number
of active iterations when needed to keep the conservative absolute sum ≤2^24.
The result explicitly records whether the 64 fixture reaches exactly 2^24;
smaller fixed iteration counts may remain below that boundary.
Full CPU reference construction happens before the measured window and can be
expensive for large MPP configurations; retain that startup cost in the overall
experiment receipt, not the reported GPU rate.

## Commands

```sh
sh build.sh
python check_stream_counts.py

# Small correctness gates first.
./peak_stream --mode half --groups 4 --iterations 32 --verify-only --output half-gate.json
./peak_stream --mode float --groups 4 --iterations 32 --verify-only --output float-gate.json
./peak_stream --mode mpp --groups 4 --iterations 32 --verify-only --output mpp-gate.json

# Bounded thirty-second controls; parent still supervises sensors and lifecycle.
./peak_stream --mode half --groups 512 --simdgroups 4 --chains 4 --iterations 32 --warmup 5 --seconds 30 --output half-30.json
./peak_stream --mode float --groups 512 --simdgroups 4 --chains 4 --iterations 32 --warmup 5 --seconds 30 --output float-30.json
./peak_stream --mode mpp --groups 64 --iterations 32 --warmup 5 --seconds 30 --output mpp-30.json
```

Both controls have initial compile, correctness/reference generation and
warmup outside the measured window. Results distinguish GPU timestamps from
wall cadence, include per-window observations and Unix timestamps, bind shader
and executable hashes, and fully check the last output before publishing a
`PEAK_RESULT` JSON record with schema `m1-matrix-stream-v1`.
