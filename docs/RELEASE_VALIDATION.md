# Source-release validation

This report describes the packaged **Pearl M-Miner v0.1.0-alpha.1 / Python package 0.1.0a1**, tested on one Apple M1 Max. It is separate from the earlier [research performance results](PERFORMANCE.md). No legacy account-validation probe is counted as release acceptance.

## Test sequence

All times below are UTC. Supervised durations include process startup and shutdown; they are not substituted for a benchmark's measurement window.

| Stage | Started (UTC) | Supervised duration |
| --- | --- | ---: |
| Source bootstrap | 2026-10-30T07:02:49.729330+00:00 | 71.190 s |
| Offline S/proof gate | 2026-10-30T07:04:10.548493+00:00 | 4.085 s |
| Fresh-grid benchmark | 2026-10-30T07:08:59.704803+00:00 | 71.186 s |
| Accelerated fee diagnostic | 2026-10-30T07:05:43.608113+00:00 | 181.086 s |
| Default-config LuckyPool trial | 2026-10-30T07:12:00.642004+00:00 | 181.093 s |

The [machine-readable record](data/release-validation.json) includes exact completion times, measurement windows, counters and original evidence-file hashes.

## Build and offline correctness

The source bootstrap installed package `0.1.0a1` in a new repository-local Python environment. It reused an existing Rust toolchain and Cargo build cache. **This was not an empty-cache, clean-room reproducibility test.**

The release self-test completed **28 official proof checks**, alongside S preparation, small-grid transcript/digest and lifecycle checks. It saved the build/device-bound self-test receipt. This proves the tested offline path, not pool acceptance on every Mac.

## Fresh-work benchmark

The release measured **3.928 protocol-equivalent TH/s** over **60.041238 seconds**, after 10.0 seconds of warm-up. The precise measurement began at `2026-10-30T07:09:10.276888+00:00` and returned 449,839,104 valid tiles. It includes preparation of new grids; it excludes pool submission and developer-route switching.

## Default-configuration live pool trial

The bounded LuckyPool run recorded **8 accepted / 0 rejected / 8 submitted**, with no pending replies. Its displayed 180-second session average was approximately **3.879 TH/s**. This is a local valid-scan protocol-work rate rounded by the original log, not the pool's rolling hashrate or earned income.

The worker log contains the actual pool acknowledgements and a matching session summary. A separate unauthenticated pool API read at 2026-10-30T07:15:34.4561367Z matched all eight accepted shares for the exact trial worker. Its receipt hash is included in the JSON; the rolling API hashrate is not substituted for local throughput. The run used the production default 1% setting, but its duration did **not** exercise the full normal developer interval. All recorded workers were reaped, and native engine cleanup reported no errors.

## Developer-route diagnostic

The separate diagnostic retained a **1%** target while explicitly shortening the cycle to **60 active seconds**. It observed positive valid scan activity in user → developer → user order. Every preceding worker was reaped before the next session started.

This same-pool diagnostic used the same public payout identity for both roles. Its user/developer labels therefore demonstrate worker-role and lifecycle transitions, not different-wallet separation.

| Session order | Role | Valid active scan seconds | Reaped |
| --- | --- | ---: | --- |
| 1 | user | 59.446101 | yes |
| 2 | dev | 0.626248 | yes |
| 3 | user | 61.999042 | yes |
| 4 | dev | 0.624037 | yes |
| 5 | user | 48.762019 | yes |

Totals were 170.207162 user seconds and 1.250284 developer seconds. Whole-region overshoot means this short diagnostic is not an exact realized 1% ratio. The production schedule remains 3564 active user seconds followed by roughly 36 active developer seconds, with overshoot carried forward.

**An accelerated lifecycle pass does not validate a complete production hour, exact 1% revenue, or default developer-wallet credit.** Any observed pool reply counts are preserved by role in the JSON; this report does not infer payout credit from activity. See [developer-fee semantics](DEV_FEE.md).

## Optional cross-pool diagnostic

The separate accelerated cross-pool test ran from `2026-10-30T07:10:14.025842+00:00` to `2026-10-30T07:11:54.838210+00:00` (100.672 supervised seconds). It used distinct payout identities and verified the actual **Kryptex → LuckyPool → Kryptex** connection sequence, successful authorization and certificate-v3 work in each active session. Payouts, worker names and session tokens are deliberately omitted from the public report.

Every role's connection matched its start identity and final reap receipt. All workers were stopped and reaped in order. The diagnostic cycle was 60 active seconds, with 95.640899 user and 0.626353 developer active scan seconds. This validates bounded cross-pool routing and work; it does not validate a full production-hour schedule, long-run revenue or developer-wallet API credit.

## Source binding and limits

43 common runtime/build source inputs were unchanged across these receipts. Pre-build inputs and subsequently built native-library fingerprints are different scopes; this report does not claim they were identical. M2–M5 performance, long-running stability, outlet power and net income remain unverified.

## Evidence hashes

These are hashes of retained original receipts. Only sanitized values are published; raw receipts contain local operational details and are not copied into this repository.

| Original artifact | SHA256 |
| --- | --- |
| `r3b-fresh-bootstrap.json` | `5786c8512114639d3c72198940b92aa840b37a12f3d621d2e27b763acb6f9350` |
| `r4-release-selftest.json` | `cb4407019e65bb7989d9e73f243c56a5cce95953725e0bdde35a05655e24af01` |
| `r5b-release-benchmark60.json` | `4a0740b6998d46f3503663f78a86fa0e4df8abcef1a3ee19b75b5f2f5cd987a9` |
| `r6-release-fee-diagnostic.json` | `88662bc91ce8fa568c63b5b0d54f37ac1deff8dbfdad8cda4c29abc31828384c` |
| `r7-release-luckypool180.json` | `0d1b5e7998849a374b36c75fdb21c98b96408569f7b6d647d99105bc10d959f9` |
| `r6b-release-crosspool-diagnostic.json` | `6e83234bca6186b920145cbc593d9a21b87568f815570f138ee380041d0de5f6` |

Disclosed source revisions:

- `pearl_m_miner/safety.py`: Added BatteryPoller for the benchmark-only cached battery check. Existing thermal-pressure and valid-scan accounting behavior was unchanged by the reviewed change. Per-stage source hashes are preserved in the JSON.
- `pearl_metal_miner/benchmark.py`: Benchmark battery-state polling was cached and obsolete initialization text removed; a fresh benchmark rerun is reported. Per-stage source hashes are preserved in the JSON.

These explicit revisions are excluded from the stable source fingerprint; no other common production source/build input changed. Test-only files are excluded from this runtime binding.

The earlier benchmark artifact `r5-release-benchmark60.json` measured 3.359 TH/s. It is retained as a superseded result rather than silently discarded; it does not establish a live-mining regression. Its receipt SHA256 is `3cafdf2af7d93e406cd5572ccce08a5aae0c06f23d234214d9f403e604ec56a5`.

## CPU test suite

48 CPU correctness and lifecycle tests passed. These include contribution accounting, payout isolation, failed developer routing, restart state and real subprocess cleanup after a closed log sink. They do not emulate native Metal performance.
