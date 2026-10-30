# How the M-series backend works

Pearl M-Miner is a Metal GPU miner. Apple Neural Engine use has not been established by these experiments and contributes nothing to the published hashrate.

The backend is derived from [pearl-metal-miner](https://github.com/Breakwater-ecosystem/pearl-metal-miner). Commitment and proof verification use the official Pearl implementation pinned to `3c84be9fb4b2b279967ad3f9f74e67fb8c9cce30`. It retains integer-equivalent protocol semantics while changing the representation and scheduling of work.

## Exact dataflow

The supported path uses K=4096, rank=128 and all 32 required prefix boundaries. With a legal zero B signal, the noised B matrix can be written `B' = VQ`. For every required prefix L:

```text
X_L = A'[:L] Q[:L]^T
C_L = X_L V^T

S_L = P_A[:L] Q[:L]^T
X_L = U_A S_L + nonce_correction_L
```

The CPU builds the compact prefix matrices S using signed scatter updates. Metal tensor operations form X, apply the exact nonce correction, and scan X against V. Two related prefixes are folded directly into their transcript slot, followed by the keyed BLAKE3 operation. All 32 prefix contributions and their rotate/XOR order are preserved. Computing only the final matrix product would produce the wrong transcript.

The leading scan work is still `32 × m × n × 128 = m × n × K`. This is a dataflow and scheduling optimization, not a claim of removing 32 times the arithmetic. Preparation adds a smaller matrix operation in exchange for avoiding a slower scatter-heavy GPU path and large CPU intermediate materialization.

## Why unified memory still needs careful ownership

Unified memory removes the need for a discrete GPU's physical host/device transfer path, but it does not remove bandwidth, allocation, layout conversion, synchronization or lifetime costs. The new path uploads compact immutable inputs and keeps large X intermediates GPU-private. A reusable temporary buffer is held under a preparation mutex until the GPU has completed and guards have been read. Each published generation owns its final half-precision buffers and proof inputs.

A fresh nonce changes the A commitment and noise seed, producing new work. Fixed B reuse is scoped by the job, header, certificate, configuration and dimensions. It cannot be keyed merely by a Python object address. Old generations remain immutable while in-flight scans or proofs refer to them.

## Precision is a gate, not a quality setting

Half storage and float accumulation are enabled only for actual inputs that preserve exact integer arithmetic:

- S and X must survive an exact conversion to half and back.
- Their conservative accumulation bounds must remain within the exact integer range of float32.
- For each X row/prefix, `L1(X) × 32 <= 2^24`; actual V values must remain in `[-32,31]`.
- Nonce leaf position, contents, dimensions and sparse pair indices are validated.

An invalid input is rejected. It is not silently rounded, approximated or counted as successful work. This matters even if a particular invalid S would later multiply to zero.

## Verification completed on M1 Max

The research gate compared every element of a 67,108,864-element int32 X fixture and its half representation against an independent construction. Large-grid scan validation checked 271 selected/hit tiles and four official proof target brackets; it did not CPU-verify every large-grid output tile. Small-grid tests checked complete transcripts, digests and hit sets, plus 28 official proof target brackets for the S path.

Separate tests exercised near-limit positive and negative integers, nonrepresentable half values, overflow guards, target equality, old handles, retained generations, mutation and lifetime boundaries. The live trial then submitted seven shares accepted by the pool. Mathematical correctness tests, live acceptance and sustained performance remain separate gates.

## What has not been established

The experiments do not establish a 15 TH/s path, a chip-wide theoretical maximum, an Apple Neural Engine mining implementation, or identical gains on other M-series chips. More memory capacity or a faster SSD alone does not eliminate the matrix scan. Compatibility reports must include the exact chip, macOS, compiler, correctness results and bounded live evidence.
