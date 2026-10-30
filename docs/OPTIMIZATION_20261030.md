# M1 Max optimization trials — 2026-10-30

**Earlier-round decision: retain the existing PRL computation backend and 512-row dispatch.** The private-buffer, dispatch-size and guarded register-fold candidates below did not demonstrate a worthwhile improvement. The display-only telemetry and task-log fix were deployed after validation. A later 32-row candidate has now passed local qualification, been deployed locally and produced a verified Kryptex-accepted user share, described next.

## Later local qualification: 32-row subblocks

The unreleased candidate replaces each 64x64x128 MPP operation with two
sequential 32x64x128 operations and a smaller public output store. It preserves
every K term, all 32 prefixes, transcript hashing, target checks and actual-input
exactness guards. Native dispatch remains 128 threads, four SIMDgroups and
512 region rows. No private cooperative-tensor layout assumption is introduced.

| Local fresh-grid measurement | Duration | Protocol-equivalent TH/s |
| --- | --- | ---: |
| Existing Alpha 2 S-prefix backend, baseline controls | Four runs of at least 60 s | 3.927237 mean |
| 32-row candidate | Two runs of at least 60 s | 4.234368 mean |
| Exact release candidate, sustained check | 300.015 s | 4.234744 |

The matched short-run mean improvement is **7.82% over the existing Alpha 2
S-prefix backend**, on this M1 Max only. It is not a new comparison against
Pearly, upstream or other M-series chips. The five-minute test is a separate
confirmation of local sustained throughput, not a pool-effective rate.
The four baseline controls include the three interleaved controls and the
GPU-only control after the separate CPU coexistence experiment; the concurrent
CPU/GPU run itself is not included in this baseline mean.

The candidate passed 28 official proof checks, four production-dimension proof
brackets and 512 independent checks of the production non-export path. Large-grid
gates check selected tiles and returned hits rather than every tile. The
fresh-grid timing includes grid preparation but excludes pool submission/proof
and network work. Separate bounded live acceptance is recorded below; no precise
pool rate, fee-adjusted income or outlet-power efficiency is claimed. See [the ceiling/work-count report](M1_CEILING_20261030.md)
for measurement details and retained controls.

Local deployment completed at **2026-10-30 09:41:08 UTC**. The deployed shader
is the exact 300-second-tested release copy; it passed another official
self-test and a 45.056-second CLI benchmark at **4.233946 TH/s**. The existing
Kryptex worker resumed with its guardian and production configuration unchanged.
At **09:42:42 UTC**, the new user session had **one accepted and zero rejected
shares**. All 35 runtime fingerprints matched the qualified build; the accepted
reply matched the gzip submit ID and a locally verified job. Developer-session
shares are excluded. The [sanitized live receipt](data/m1-pair32-live.json)
binds these observations to the new shader. This short window verifies acceptance,
not a precise pool-effective rate or income, and is not a public release.

## Earlier-round matched offline measurements

One M1 Max (32 GPU cores, 64 GiB), macOS 26.6.1; M=16384, N=65536, K=4096, rank=128; two CPU helpers. Each run used a nine-second warmup followed by at least 45 seconds of measured fresh-grid scanning. Only one GPU miner/test ran at a time. Controls were interleaved with candidates. Protocol work is 524288 per returned tile.

| Candidate | Runs | Mean local TH/s | Change vs initial control | Decision |
| --- | ---: | ---: | ---: | --- |
| Current backend, 512 rows | 3 | 3.9272 | +0.000% | Retained |
| GPU-private transcript | 1 | 3.9275 | +0.008% | Not adopted; no meaningful gain |
| 128-row dispatch | 1 | 3.8684 | -1.496% | Not adopted; slower |
| 2048-row dispatch | 1 | 3.9320 | +0.123% | Not adopted; small single-run difference, longer stale-work exposure |
| Register fold, full layout guard | 2 | 2.9448 | -25.015% | Not adopted; slower |
| Register fold, unrolled full guard | 2 | 3.3511 | -14.668% | Not adopted; slower |
| Current backend + display telemetry | 1 | 3.9274 | +0.006% | Display update deployed; computational backend unchanged |

The 2048-row setting has a longer single dispatch and therefore can discard more work when a pool job changes. Its roughly one-tenth-percent offline difference is insufficient to establish a live improvement. GPU-private storage also gave no useful speed change. The register variants passed correctness checks but were slower. Explicitly expanding the layout-check loop improved that candidate, without beating the original kernel. No check was removed or replaced with an assumed permanent layout.

These are local protocol-equivalent rates including grid preparation, not pool rate, income or a chip theoretical limit. Software `sys_power` and temperature observations are preserved per measurement window in [the JSON receipt](data/optimization-20261030.json). They are not outlet readings; no whole-machine energy-efficiency or net-profit claim is made.

## Earlier-round correctness and deployment

- Private transcript: 28 official proof checks plus 512 independently reconstructed transcript/digest/target checks, including alternating CPU-export and production scan modes.
- Each register variant: natural specialization, forced fallback and injected mismatch paths; full small-grid transcript/hash/hit checks; 28 official proof checks and four production-dimension proof brackets; production non-export checks. Large-grid gates inspect selected tiles and all returned hits, not every large-grid tile.
- Display update: 77 CPU tests passed on Windows and Mac, 28 official proof checks passed on Mac, and its offline rate remained about 3.927 TH/s. Live telemetry was parsed and correlated with separate user/developer sessions.
- Every bounded batch in this earlier round confirmed the owned production guardian resumed. Pool identity, optional 1% active-scan contribution and thermal protection were retained. Its private-buffer, dispatch-size and register-fold candidates were not deployed as the production miner.

After that earlier round's restoration, the display-patched miner submitted a gzip proof
accepted by Kryptex at **08:37:34 UTC**; the 08:37:59 snapshot recorded one
accepted and zero rejected in the new user session. Its initial 30-second
local rate was about 3.852 TH/s including startup, a task change and proof work.
This is a distinct live window, not the offline 3.927 TH/s benchmark. The
[live receipt](data/observability-live-validation.json) binds the observation
to the deployed display-source hashes.

## Next work

Use the new live stage/stale counters to guide further tile/dispatch/layout experiments. Keep the PRL backend independently testable, qualify other M-series devices with real measurements, then test CPU XMR through a separate backend. Compare PRL-only, XMR-only and dual configurations using accepted work, resource contention and measured wall power. Different algorithms' hash rates must remain separate. See [the PRL-first roadmap](ROADMAP.md).

The isolated candidate patches and correctness tools are retained in [research/2026-10-30](../research/2026-10-30/README.md). Real Alpha 2 gzip-share acceptance is separate evidence in [the protocol report](KRYPTEX_GZIP.md).
