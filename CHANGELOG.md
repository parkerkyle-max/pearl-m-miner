# Changelog

## 0.1.0a2 — Kryptex gzip

- Implements explicit per-connection v2 negotiation and gzip of original proof bytes.
- Prevents stale encoding, authorization and socket state from leaking across reconnects.
- Records proof compression sizes/timing and excludes failed sends from submitted counts.
- Adds 18 protocol tests and a real official-proof roundtrip tool. [Evidence](docs/KRYPTEX_GZIP.md).

## 0.1.0a1 â€” experimental source release

- Introduces Pearl M-Miner, an Apache-2.0 derivative of pearl-metal-miner focused on Apple Silicon Metal GPU mining.
- Adds prefix-based scan scheduling and S-matrix preparation, with actual-input exactness guards and immutable per-job GPU/proof state.
- Includes incremental nonce/Merkle preparation and compact GPU inputs to reduce CPU preparation and intermediate memory traffic.
- Publishes reproducible, sanitized M1 Max research results, with historical upstream/Pearly context and a separate already-optimized baseline.
- Adds a disclosed, optional 1% developer-time contribution. Its schedule and failure handling are documented separately from research performance.
- Ships as source with local build and verification commands; other M-series devices remain experimental targets.

See [performance](docs/PERFORMANCE.md) for evidence boundaries. Research backend measurements do not by themselves validate every packaging or fee-runtime behavior.
