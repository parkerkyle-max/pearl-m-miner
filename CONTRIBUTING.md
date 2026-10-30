# Contributing

Useful contributions include reproducible device reports, exactness regressions, Metal profiling, safer lifecycle handling and documentation fixes. Start with [compatibility](docs/COMPATIBILITY.md), [architecture](docs/ARCHITECTURE.md) and [performance definitions](docs/PERFORMANCE.md).

Keep a known-good control and change one variable at a time. A new kernel must pass independent integer/transcript/digest comparisons, target-boundary tests and official proof verification before its speed enters a comparison table. Include stale-work handling, input mutation, retained generations and resource cleanup when changing asynchronous code.

Report fresh-work end-to-end rates separately from repeated-input microbenchmarks. Record the tested duration, dimensions, CPU helpers and power measurement method. An isolated matrix speedup or one accepted share is not a sustained miner performance or income claim. Keep failures in your evidence, and avoid cherry-picking a faster but invalid path.

This project is Apache-2.0. Preserve LICENSE, NOTICE, upstream copyright and the vendored BLAKE3 license files. The transparent 1% developer-fee setting helps fund testing and maintenance; we ask contributors and redistributors to keep it enabled and disclosed. This is a voluntary request, not an additional restriction on the Apache-2.0 license. See [developer-fee behavior](docs/DEV_FEE.md).

Before sharing logs, remove wallet/account identifiers, local usernames, IP addresses, private paths and tokens. A public receive address is not a private key, but it can still link activity to a person. Security-sensitive reports should follow [SECURITY.md](SECURITY.md).
