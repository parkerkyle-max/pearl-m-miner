# Changelog

## 0.1.0a3 — M1 Max optimization, public discovery and four languages

- Separates local protocol TH/s, share results, job freshness and native stage counters in bounded 30-second telemetry.
- Restores new-job log notices when the job arrives during a GPU scan; ordinary nonce grids remain quiet.
- Adds 11 CPU telemetry tests and a PRL-first, separately verified multi-algorithm roadmap.
- Records two subsequent Alpha 2 gzip shares accepted by Kryptex, with sanitized request/reply evidence.
- Retains failed/no-gain private-buffer, dispatch-size and guarded register-fold experiments with matched timing and correctness tools. That earlier round kept the production computation backend and 512-row dispatch unchanged and established no computational speedup.
- Locally qualifies the 32-row MPP subblock backend: two interleaved 60-second fresh-grid trials averaged 4.2344 TH/s versus 3.9272 TH/s for the existing Alpha 2 S-prefix backend (+7.82%); the exact release candidate sustained 4.2347 TH/s for 300 seconds. Full K work, all transcript prefixes, hashes, targets and input guards are preserved.
- Records 28 official proof checks, four production-dimension proof brackets and 512 independent non-export-path checks for the candidate. Local deployment completed after another official self-test and a 45-second CLI recheck at 4.23395 TH/s; the same Kryptex worker resumed with its guardian/configuration unchanged. A bounded new user session recorded one accepted and zero rejected shares, with the reply bound to the deployed build and matching gzip submission. This [acceptance receipt](docs/data/m1-pair32-live.json) is not a precise pool-rate or income measurement. This is not a new Pearly/upstream/M2–M5 comparison. [Ceiling and work-count report](docs/M1_CEILING_20261030.md).

- Adds offline `info --json`, the public developer payout guide, Chinese/Japanese/Korean READMEs and multilingual static documentation.
- Records a Strata-inspired encoder-reuse trial: +0.0044% mean difference, no meaningful gain; the candidate is not enabled. [Study](docs/STRATA_REVIEW.md).
- Publishes machine-readable capabilities, llms.txt, FAQ and an explicit AI installation sequence.

## 0.1.0a2 — Kryptex gzip

- Implements explicit per-connection v2 negotiation and gzip of original proof bytes.
- Prevents stale encoding, authorization and socket state from leaking across reconnects.
- Records proof compression sizes/timing and excludes failed sends from submitted counts.
- Adds 18 protocol tests and a real official-proof roundtrip tool. [Evidence](docs/KRYPTEX_GZIP.md).

## 0.1.0a1 — experimental source release

- Introduces Pearl M-Miner, an Apache-2.0 derivative of pearl-metal-miner focused on Apple Silicon Metal GPU mining.
- Adds prefix-based scan scheduling and S-matrix preparation, with actual-input exactness guards and immutable per-job GPU/proof state.
- Includes incremental nonce/Merkle preparation and compact GPU inputs to reduce CPU preparation and intermediate memory traffic.
- Publishes reproducible, sanitized M1 Max research results, with historical upstream/Pearly context and a separate already-optimized baseline.
- Adds a disclosed, optional 1% developer-time contribution. Its schedule and failure handling are documented separately from research performance.
- Ships as source with local build and verification commands; other M-series devices remain experimental targets.

See [performance](docs/PERFORMANCE.md) for evidence boundaries. Research backend measurements do not by themselves validate every packaging or fee-runtime behavior.
