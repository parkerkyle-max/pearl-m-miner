# What Strata can teach a Pearl miner

Reviewed 2026-10-30 at pinned [Niko1221/Strata commit 870aedd9e1eb](https://github.com/Niko1221/Strata/tree/870aedd9e1ebe1c91f94da93b59af17729f6c5c0).
Strata is an LLM inference engine, not a PRL miner. This review does not import
its token-rate claims into mining. The similarly named amperor-strata is a
different project; this experiment concerns Niko1221's Metal runtime.

## Source-backed ideas and transfer limits

| Idea | Strata source | Pearl decision |
| --- | --- | --- |
| Reuse compute encoders / group dependent GPU work | [runtime.cpp](https://github.com/Niko1221/Strata/blob/870aedd9e1ebe1c91f94da93b59af17729f6c5c0/metal/src/gpu/runtime.cpp), [mtl_rt.mm](https://github.com/Niko1221/Strata/blob/870aedd9e1ebe1c91f94da93b59af17729f6c5c0/metal/src/mtl_rt.mm) | Tested a serial scan/hash encoder with an explicit dependency barrier; no worthwhile gain |
| Keep useful data resident and reuse bounded buffers | [Mac guide](https://github.com/Niko1221/Strata/blob/870aedd9e1ebe1c91f94da93b59af17729f6c5c0/docs/MAC.md) | Our immutable job cache/private intermediates already reuse data. Residency is useful under pressure; SSD paging does not raise arithmetic throughput when the working set fits |
| Choose implementations by actual chip results | Same guide documents a prompt-GEMM path that fails on M1 Max | Preserve exactness gates and device-specific qualification; do not advertise M5 measurements as M1 results |
| Quantization / selected experts / speculative token proposals | Strata's inference design | Not a license to skip required PRL prefixes or use approximate arithmetic. Every mining candidate still needs an exact transcript and official proof |

The original patch changes only scan scheduling and was independently written.
No Strata source is distributed in the production miner. Its repository is MIT;
future source reuse must preserve any applicable notices. No endorsement implied.

## Actual M1 Max scheduling trial

Same 32-row shader, M16384/N65536, region512, two helpers, 10-second warmup then
60 measured seconds, one GPU trial at a time. Official28 + large4 + independent512
checks passed before the speed trials. All required work and input guards remain.

| Trial | Local PRL TH/s | Measured seconds |
| --- | ---: | ---: |
| control-a | 4.234137 | 60.05 |
| single-b | 4.234677 | 60.04 |
| control-a2 | 4.234286 | 60.05 |
| single-b2 | 4.233937 | 60.05 |
| control-a3 | 4.233933 | 60.05 |

Control mean **4.234119 TH/s**, candidate mean **4.234307 TH/s**; difference
**+0.0044%**. The candidate is not consistently faster and the difference
is too small to justify a production change. The original miner was restored.
These are fresh-grid offline rates, not pool-effective rate or revenue.

## Release decision

Alpha 3 ships the previously qualified **32-row MPP kernel** (4.2347 TH/s in its
300-second trial; +7.82% versus our older Alpha2 backend), plus public offline
discovery, telemetry and four-language documentation. It does not label the
no-gain Strata-inspired experiment as a speedup. Bigger gains still need exact
algorithm/layout work, qualified device tuning or a complete separately verified
CPU backend. CPU arithmetic throughput alone is not credited PRL mining.

[Machine-readable trial receipt](data/strata-study.json) ·
[Candidate source](../research/2026-10-30/strata/prefix_single_encoder.mm) ·
[Main M1 report](M1_CEILING_20261030.md).
