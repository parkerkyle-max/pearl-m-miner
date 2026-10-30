# Alpha 3 deployment validation

On 2026-10-30 the existing M1 Max installation was updated to Python package
`0.1.0a3`. The exact previously qualified 32-row shader/native host/adapter were
preserved. This was a source update over the existing native environment, not a
fresh bootstrap or a qualification of other Macs.

- 79 portable CPU/lifecycle/protocol tests passed on Windows and on the Mac.
- The official-proof self-test passed again on the Mac.
- A 45.0565-second fresh-grid CLI recheck measured **4.233911 TH/s**, after warmup.
- The public offline `info --json` command reported the expected version and
  developer route. It does not start mining or open a network connection.
- The original Kryptex worker, configuration and thermal guardian resumed.

[Machine-readable deployment receipt](data/alpha3-deployment.json) contains file
hashes, timing and scope. [The main M1 report](M1_CEILING_20261030.md) records the
longer 300-second measurement, matched Alpha 2 comparison and exactness gates.
[The earlier same-kernel pool receipt](data/m1-pair32-live.json) is a separate
observation of pool acceptance; it does not measure precise pool speed or income.

Public documentation includes English, Chinese, Japanese and Korean README files,
an offline capability manifest and static multilingual pages. Search/AI indexing
and pool listing are external decisions, not release validation results.
