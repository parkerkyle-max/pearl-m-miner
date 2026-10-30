# Compatibility and validation

| Target | Status | Published performance |
| --- | --- | --- |
| M1 Max, 32-core GPU, 64 GiB, macOS 26.6.1 | Research backend correctness and bounded live pool run measured | See [performance](PERFORMANCE.md) |
| Other M1 variants | Experimental target; no result from this release | Not measured |
| M2 family | Experimental target | Not measured |
| M3 family | Experimental target | Not measured |
| M4 family | Experimental target | Not measured |
| M5 family | Experimental target | Not measured |
| Intel Mac / non-Metal device | Unsupported | None |
| Apple Neural Engine | Not a mining backend in this release | None |

The optimized backend requires Apple Silicon and macOS 26 or later with a compatible Metal 4 compiler/runtime and development tools. Passing an OS/version check is only a prerequisite. A successful compile and exactness self-test are required on the actual device before a mining trial. The source release is not a portable precompiled wheel, and we do not infer compatibility from a chip's advertised TOPS.

M1 Max research used two CPU helpers. The automatic profile selects M=16384 and N=65536 only on an M1 Max with at least 64 GiB RAM; other devices start at M=8192 and N=16384. Explicit profiles or dimensions may override that choice. The GPU backend uses K=4096 and rank=128; supported bounds and defaults are checked by the CLI/native code. A conservative configuration should be tested before increasing memory use. A local self-test receipt binds the result to key source/library hashes and the OS/device; changing those requires a new self-test before benchmark or mining.

LuckyPool and Kryptex have recorded accepted M1 Max shares. Kryptex uses negotiated gzip-v2, with separate [protocol evidence](KRYPTEX_GZIP.md) and [32-row kernel acceptance](data/m1-pair32-live.json). These bounded tests do not imply an official listing or endorsement. Other inherited Stratum dialects may be configurable, but the existence of a code path is not completed per-pool validation. Pool availability, minimum payout and fee rules are external conditions and can change.

To contribute a new device result, include:

1. Chip and GPU-core count, unified memory, macOS and compiler versions.
2. Commit/version, exact command and configuration, with identities and addresses removed.
3. Successful correctness gate output and a timed fresh-work benchmark.
4. A bounded pool run with submitted/accepted/rejected counts and its time window.
5. AC outlet power if available; otherwise label all reported power as software telemetry.

Do not submit private keys, seed phrases, authentication tokens, local account paths, or unrelated process/network inventories.

The packaged M1 Max release also passed a fresh source build, offline proof gate and bounded LuckyPool trial with eight API-confirmed accepted shares. Kryptex cross-pool authorization/routing was separately exercised. [Release validation](RELEASE_VALIDATION.md) records the precise scopes.
