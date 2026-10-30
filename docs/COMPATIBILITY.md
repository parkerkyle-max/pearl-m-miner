# Compatibility and validation

The authoritative model-by-model status is the
[collapsible M1–M6 device results matrix](../README.md#device-results), backed
by [device-results.json](device-results.json). Use those entries for measured
configurations, comparison baselines, dates, evidence and planned tests. Family
headings and unconfirmed model slots are organizational placeholders, not a
claim that all listed variants exist or that this release supports them.

Two exact configurations currently have published qualification evidence:

- **M1 Max, 32-core GPU, 64 GiB, macOS 26.6.1:** Alpha 3's selected backend
  measured **4.2347 PRL TH/s over 300 offline seconds**. Matched shorter trials
  showed **+7.82% versus our own Alpha 2 backend**, not a new upstream or Pearly
  comparison. See the [M1 report](M1_CEILING_20261030.md),
  [matched trial details](OPTIMIZATION_20261030.md) and
  [Alpha 3 deployment and pool acceptance](ALPHA3_VALIDATION.md).
- **M2, 10-core GPU, 24 GiB, macOS 27.0:** the unchanged Alpha 3 source passed
  build and proof gates and measured **1.4652 PRL TH/s over 300 offline seconds**.
  A matched 300-second upstream control measured 0.4061 TH/s. Bounded pool
  trials used **80% intensity** after the full-duty attempt reached the external
  lab's thermal stop. See the [M2 report](M2_VALIDATION_20261030.md); the offline
  result is not a sustained live-rate promise.

Untested GPU-core counts, memory sizes, OS versions and other variants remain
unqualified, including variants in a family with a measured entry. A planned
test is not a support commitment. Intel Macs and non-Metal devices are
unsupported. CPU, Apple Neural Engine and multi-coin mining are not shipped
backends in this release.

The optimized backend requires Apple Silicon and macOS 26 or later with a compatible Metal 4 compiler/runtime and development tools. Passing an OS/version check is only a prerequisite. A successful compile and exactness self-test are required on the actual device before a mining trial. The source release is not a portable precompiled wheel, and we do not infer compatibility from a chip's advertised TOPS.

M1 Max research used two CPU helpers. The automatic profile selects M=16384 and N=65536 only on an M1 Max with at least 64 GiB RAM; other devices start at M=8192 and N=16384. Explicit profiles or dimensions may override that choice. The GPU backend uses K=4096 and rank=128; supported bounds and defaults are checked by the CLI/native code. A conservative configuration should be tested before increasing memory use. A local self-test receipt binds the result to key source/library hashes and the OS/device; changing those requires a new self-test before benchmark or mining.

LuckyPool and Kryptex have recorded accepted M1 Max shares. Kryptex uses negotiated gzip-v2, with separate [protocol evidence](KRYPTEX_GZIP.md) and [32-row kernel acceptance](data/m1-pair32-live.json). These bounded tests do not imply an official listing or endorsement. Other inherited Stratum dialects may be configurable, but the existence of a code path is not completed per-pool validation. Pool availability, minimum payout and fee rules are external conditions and can change.

Use the [device result form](https://github.com/parkerkyle-max/pearl-m-miner/issues/new?template=device-result.yml) to contribute a measured configuration or a failed build/self-test. Include the following where available; a failed step does not require completing later steps:

1. Chip and GPU-core count, unified memory, macOS and compiler versions.
2. Commit/version, exact command and configuration, with identities and addresses removed.
3. Successful correctness gate output and a timed fresh-work benchmark.
4. A bounded pool run with submitted/accepted/rejected counts and its time window.
5. AC outlet power if available; otherwise label all reported power as software telemetry.

Do not submit private keys, seed phrases, authentication tokens, local account paths, or unrelated process/network inventories.

To question an existing figure, baseline or compatibility description, use the
[benchmark discrepancy form](https://github.com/parkerkyle-max/pearl-m-miner/issues/new?template=benchmark-discrepancy.yml).
A source link and description of the concern are useful; a successful local
build or a replacement benchmark is not required to report a possible error.

The packaged M1 Max release also passed a fresh source build, offline proof gate and bounded LuckyPool trial with eight API-confirmed accepted shares. Kryptex cross-pool authorization/routing was separately exercised. [Release validation](RELEASE_VALIDATION.md) records the precise scopes.

## Later M2 qualification supplement

The dated [M2 report](M2_VALIDATION_20261030.md) qualifies the unchanged Alpha 3
source on the exact configuration listed above. The immutable release CLI
metadata still names the earlier M1 Max qualification. The device results matrix
and website manifest include the later evidence; neither implies all M2 models or
all macOS releases have been tested. The existing conservative M2 defaults were
retained after shape/dispatch/kernel experiments. No runtime auto-tuner is claimed.
