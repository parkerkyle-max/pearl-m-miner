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

## Subsequent Alpha 3 live acceptance

After the version update, the new Kryptex user session received a matching
successful reply at **2026-10-30 10:04:27 UTC**. The 10:05:20 UTC snapshot
recorded **1 accepted / 0 rejected**, with runtime file hashes matched to the
qualified Alpha 3 deployment and the production configuration unchanged.
The proof passed the local official verifier, then the 276161-byte payload
was gzip-compressed to 2554 bytes. Submission ID 11 and the job ID match the
pool's `result: true` reply. Developer sessions are excluded.

See [the sanitized Alpha 3 live receipt](data/alpha3-live.json). This is actual
acceptance evidence, not a precise pool-rate measurement, income measurement,
long-duration stability result or listing approval. The release tag is unchanged;
this is a later evidence supplement for the same deployed source.

## Subsequent M2 qualification

The unchanged release was freshly built on a 10-core-GPU M2 with 24 GiB memory
and macOS 27.0. [The M2 supplement](M2_VALIDATION_20261030.md) records the matched
upstream control, 300-second measurements, tuning non-winners, exactness gates
and bounded pool trials. This does not change the Alpha 3 tag or qualify all
M2 variants. Documentation and discovery pages now reflect both tested devices.
