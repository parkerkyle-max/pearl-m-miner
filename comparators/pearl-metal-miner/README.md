# Pinned upstream comparison control

`upstream/` contains an unmodified runtime-source subset of
[pearl-metal-miner 0.2.4](https://github.com/Breakwater-ecosystem/pearl-metal-miner/tree/3d4cc7dadbd1de98ba20e9beb162806a0e70266b),
commit `3d4cc7dadbd1de98ba20e9beb162806a0e70266b`. The original
[LICENSE](upstream/LICENSE) and [NOTICE](upstream/NOTICE) are preserved.
`source-manifest.json` records the official archive URL, archive digest, every
included source digest and the expected results of the disclosed patch.

The included `upstream-cert3-compat.patch` is the same Python compatibility
patch published with the dated M2 comparison. It adds certificate-v3 seed,
proof and session handling and precise benchmark output. It does not modify
the upstream native host or GPU kernels. The control must be described as
**pearl-metal-miner 0.2.4 + cert3 compatibility**, not an unmodified end-to-end
upstream release.

The explicit comparison command invokes `packaging/build_compare_control.py`.
That script needs no network: it verifies the retained sources, applies the
patch with exact context and output-hash checks, and builds a separate native
library in `build/runtime/build/`. It neither installs another package nor
overwrites Pearl M-Miner's native library. The build receipt is
`build/build-manifest.json`. `--verify-only` verifies source provenance without
building; `--prepare-only` additionally prepares and verifies the patched
runtime without invoking a compiler.

The comparison worker imports this isolated runtime for upstream phases and
the project runtime for candidate phases. Both use certificate 3, the same
synthetic header, requested dimensions, CPU thread cap and measured duration.
Each retains its own production preparation strategy and miner-chosen matrices;
this is not a claim that both generate identical A/B matrices. Fresh-grid
preparation and returned scans are measured. Compilation, warmup, correctness
gates, pool/network work and hit-triggered proof construction are excluded.
Proof correctness is checked separately on both backends, before accepting a
comparison. No pool connection, payout identity or wallet access is needed.

The upstream gate explicitly runs only seed, GPU arithmetic and official-proof
checks. Its wallet test is not invoked. Runtime imports, source hashes and
native-library hashes are verified; a missing or changed identity fails closed.
Historical M1/M2 results do not qualify this newly integrated comparison runner
on a Mac until an actual run of the runner has completed there.
