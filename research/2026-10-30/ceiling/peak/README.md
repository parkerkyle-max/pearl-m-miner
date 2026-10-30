# Standalone M1 matrix arithmetic measurement

This is a research microbenchmark, not a miner. It never connects to a pool or
reads a wallet. It does not install a service, change power limits, touch another
process, or infer mining income. Run it only while the existing GPU miner is
paused and a parent supervisor records temperature/power and guarantees cleanup
and restoration. The executable additionally refuses macOS serious/critical
thermal pressure before each dispatch.

The source requires an arm64 Mac with macOS26+, a compatible Metal4/Xcode
Command Line Tools installation, and an Apple unified-memory GPU. Windows can
run the independent CPU arithmetic/count audit, but cannot qualify these Metal
kernels. No GPU result is claimed by this source-only preparation.

## Build and initial gates

```sh
sh build.sh
./peak --mode half --verify-only --groups 64 --shader peak.metal --output half-gate.json
./peak --mode float --verify-only --groups 64 --shader peak.metal --output float-gate.json
./peak --mode mpp --verify-only --groups 16 --shader peak.metal --output mpp-gate.json
```

`PEAK_RESULT` contains the JSON result. `--output` saves it atomically and
verifies the saved bytes. Failures produce `PEAK_ERROR` and nonzero exit.
Source/executable SHA256, chip name, OS, dispatch dimensions and work counts
bind every result. Unsupported types, compiler failures, incorrect outputs or
invalid timestamps fail; there is no fallback that silently times another path.

The CPU-only count/fixture check is:

```sh
python check_counts.py
```

## What each mode measures

| Mode | Arithmetic | Work per iteration |
| --- | --- | --- |
| `half` | `simdgroup_matrix<half,8,8>` operands, float accumulation | groups × SIMDgroups × chains × 8×8×8 MAC |
| `float` | `simdgroup_matrix<float,8,8>` operands, float accumulation | same |
| `mpp` | production-like Metal tensor operation, half operands, float accumulation, 64×64×128 | groups ×64×64×128 MAC; four SIMDgroups cooperate on one product |

One MAC counts as two FLOPs. `gpu_tflops` uses completed command-buffer GPU
timestamps; `wall_tflops` also includes encode/wait/cadence and periodic output
validation. Neither rate is a PRL hash rate. Divide neither by a remembered
hardware peak nor by a different kernel's cost without documenting that model.

The8×8 kernels load runtime matrices before the repeated multiply-accumulate
loop and store every independent accumulator afterward. The inner loop has no
explicit device load/store. Compiler spills have not been inspected, so this
does not assert zero physical memory traffic. The B inputs differ per chain;
all matrices are runtime buffer data and the iteration count is a runtime
argument. These choices keep the result observable, but do not prove every
counted matrix instruction executes: invariant products might be hoisted by
the compiler. Generated ISA has not been audited. Treat unexpectedly high
rates as unqualified until corroborated with the separate varying-operand
`peak_stream` control or instruction inspection; safe compilation/output
checks alone are not proof of the executed instruction count.

MPP's tensors remain device-backed and `operation.run` reads them per iteration;
they may be hot in caches. It ends with the same documented tensor store through
threadgroup memory used by the current miner, followed by an observed output
copy. It is a separate workload, not a claim to measure register-only MPP.

## Exactness fixtures

Every output is compared with an independent signed-int64 dot product multiplied
by the iteration count. The absolute sum of products across all iterations is
bounded by2^24 before interpreting a fixture as exact:

- Nonzero, varied runtime integers in `{-2,-1,1,2}`.
- Constant63 operands: each product is3969, which is **not** representable in
  half even though each input is. This catches unwanted half-product rounding.
- Constant127 operands: each product16129 is likewise not exactly half.
- Mixed-sign127 inputs near the conservative float32 exact-integer bound.
- Constant64 inputs reaching exactly2^24 after repeated accumulation.

These tests qualify observed behavior on their actual compiled path, not every
legal Pearl input. They do not replace the miner's actual-input X/half/L1 guards
or official proof verification. Performance iterations use only the small
integer fixture, with a maximum32768 iterations and conservative bound≤2^24.

## Calibration, sweep and sustained run

The default calibration doubles iterations from1 until approximately20ms of
GPU time or an iteration/latency cap. It verifies every calibration output.
`--target-ms` can be1..100. Any **observed** GPU dispatch over`--max-ms` (maximum
250) fails. This is an after-completion bound, not a GPU preemption mechanism;
an external parent deadline/temperature guard is still necessary.

Short sweeps should test only a few explicit configurations, for example:

```sh
./peak --mode half --groups 1024 --simdgroups 4 --chains 1 --warmup 5 --seconds 20
./peak --mode half --groups 1024 --simdgroups 4 --chains 4 --warmup 5 --seconds 20
./peak --mode half --groups 1024 --simdgroups 4 --chains 8 --warmup 5 --seconds 20
./peak --mode float --groups 1024 --simdgroups 4 --chains 4 --warmup 5 --seconds 20
./peak --mode mpp --groups 64 --warmup 5 --seconds 20
```

Then sustain the selected settings for five minutes per path:

```sh
./peak --mode half --groups 1024 --simdgroups 4 --chains 4 --warmup 20 --seconds 300 --output half-300.json
./peak --mode float --groups 1024 --simdgroups 4 --chains 4 --warmup 20 --seconds 300 --output float-300.json
./peak --mode mpp --groups 64 --warmup 20 --seconds 300 --output mpp-300.json
```

Check the actual sweep winner rather than assuming the example4-chain setting
is best.10-second windows expose sustained drift. Periodic full-output checks
are included in wall time but not GPU timestamps. Initial compile, correctness
fixtures, calibration and warmup are explicitly excluded from measured rates.
The last output is fully verified before a result is emitted. Pair timestamps
with the parent's sensor samples; software package power is not outlet power.
