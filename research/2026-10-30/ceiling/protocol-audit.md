# M1 Max Pearl optimization: primary-source audit

Assembled / source status checked during this run: **2026-10-30 08:48 UTC**.
This audit distinguishes published specifications, author-reported experiments,
mathematical deductions, and hardware behavior that still needs measurement.

## Corrections that affect the ceiling calculation

- **10.4 TFLOPS is an estimate here, not a verified Apple M1 Max specification.**
  Apple's [M1 announcement](https://www.apple.com/ca/newsroom/2020/11/apple-unleashes-m1/)
  explicitly gives 2.6 TFLOPS for the 8-core M1 GPU. Its
  [M1 Max announcement](https://www.apple.com/newsroom/2021/10/introducing-m1-pro-and-m1-max-the-most-powerful-chips-apple-has-ever-built/)
  specifies up to 32 GPU cores. Scaling equal-rate cores gives
  `2.6 * 32 / 8 = 10.4 TFLOPS`. A direct Apple statement assigning 10.4 to M1 Max
  was not found. Sustained matrix throughput still needs a matching microbenchmark.
- **64 GB does not identify the GPU core count.** Apple's
  [2021 16-inch specifications](https://support.apple.com/en-us/111901) list
  M1 Max with 24 or 32 GPU cores and 64 GB as a memory option. Read the actual machine.
- For the currently examined dense path, if one credited work unit costs one MAC
  and one MAC counts as two FLOPs, the nominal conditional ceiling is
  `10.4 / 2 = 5.2 TH/s` before other work. This is neither a pool guarantee nor a
  universal upper bound for all valid Pearl algorithms or all SoC engines.
- **A product below 4096 is not necessarily exact in half.** For example,
  `63 * 63 = 3969`, while binary16 spacing in that range is 2. Half inputs followed
  by multiplication and accumulation at float precision must be distinguished
  from a separately rounded half product. Noise can expand the operand range;
  using +/-127 for K=4096 gives `4096 * 127^2 = 66,064,384 > 2^24`.
  A selected sparse/zero input path and its proven guards do not prove arbitrary
  dense noisy inputs correct. Check prefix transcripts, not just the final dot product.

## Apple architecture: what the sources do and do not establish

- [Apple WWDC21](https://developer.apple.com/videos/play/wwdc2021/10153/)
  confirms native 16-bit types, lower register use and energy, and potentially
  higher peak rates. It does **not** establish a universal M1 FP16=FP32 throughput
  contract. It supports function constants, avoiding redundant unified-memory
  copies, and choosing narrow local indices when their range permits.
- The exact claim that hash and matrix instructions share every ALU, and the claim
  that NVIDIA hashing is effectively free, remain **unverified generalizations**.
  Execution units, instruction issue, registers, caches, and power can all matter.
  Use this miner's ablation results instead of assigning overhead from architecture lore.
- An absence of a public int8 `simdgroup_matrix` type is not by itself proof of
  the physical absence of every integer matrix facility. The classic API and the
  newer Metal 4 tensor API must be distinguished. The current official
  [MSL PDF](https://developer.apple.com/metal/Metal-Shading-Language-Specification.pdf)
  exceeded the browser extractor size limit in this audit, so its complete type
  table was **not independently re-read here**. Use installed SDK headers and
  successful compilation plus numerical tests for implementation decisions.
- [Apple's M5 announcement](https://www.apple.com/newsroom/2025/10/apple-unleashes-m5-the-next-big-leap-in-ai-performance-for-apple-silicon/)
  confirms a Neural Accelerator in each GPU core, programmable through Metal 4
  Tensor APIs. Those units differ from the separate Neural Engine. M1 performance
  does not establish M5 performance; neither does successful Core ML execution
  alone prove execution on the ANE.
- Public Accelerate SGEMM is useful to test CPU-side contribution. Calling it
  does not establish that AMX ran, and its FLOP/s must not be credited as PRL work.

## External mining numbers and FP8 risk

- [The original MI300X paper, section 4.7](https://arxiv.org/html/2606.04819v1)
  does report 44 ms BLAKE3, 38 ms noise generation, and 14 ms difficulty checking
  for its Triton/ROCm implementation. These are not M1 overhead proportions.
- [pmk's author README](https://github.com/Augustas11/pearl-apple-miner)
  reports M3 Ultra 80-core results: 16.08 TOPS for 600 seconds, 0.06% GPU idle gap,
  and paired cert-v3 15.9 versus cert-v4 8.1 TOPS-equivalent. It publishes summaries,
  not raw logs. These are author reports, not independently reproduced measurements.
- [The author's official PIP discussion](https://github.com/pearl-research-labs/pips/issues/14)
  explains that the fast FP8 path uses a constant-magnitude input family and a
  half-unit grid to avoid B200 truncation. It is not arbitrary-input FP8 speed.
  The author asks whether future jackpot policy will preserve that family and
  reports only 0.2-0.6 TOPS-equivalent for generic exact emulation on M5.
- [PIP-3](https://pearl-research-labs.github.io/pips/pip-0003/) is Draft with
  deployment TBD. Its certificate numbering is stale relative to the code:
  [official PR #311](https://github.com/pearl-research-labs/pearl/pull/311) is still
  open and implements certificate-v4. No activation height was verified here.
- [The official FP8 arithmetic reference](https://raw.githubusercontent.com/pearl-research-labs/pearl/fp8-scheme/zk-pow/src/v4/api/utils.rs)
  contains device-specific accumulation: 32-product groups, a 26-bit B200 window,
  a 14-bit H100 window with 128-product promotion, and signed-zero handling that
  affects hashed bits. Simply decoding FP8 to half is insufficient. Pin a commit
  before validating, because the linked development branch can change.

## Priorities

1. Measure sustained half-input/float-accumulator and float-input paths with
   observable outputs; separately measure the real miner and its non-GEMM work.
2. Retain exact reference checks, adversarial bounds, and a known-good fallback.
3. Tune tile shape, register pressure, specialization, and launch layout using
   interleaved repeated baselines; reject changes below repeatability noise.
4. Test Accelerate concurrently only after an isolated baseline. Compare total
   valid mining output and power, not the sum of unrelated benchmark rates.
5. Track certificate-v4 in a separate pinned validation path; don't advertise
   generic FP8 support or future policy acceptance from a component benchmark.
