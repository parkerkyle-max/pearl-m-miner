# Apple Silicon PRL comparators and repository snapshot

This is a limited public GitHub search, observed **2026-10-30, approximately
22:17–22:18 UTC**, for actual Apple Silicon Pearl/PRL GPU miners and their release
repositories. It is not an exhaustive census or a claim to have found the most
starred miner on all of GitHub. Repository stars change and measure attention,
not performance, safety, adoption or protocol compatibility. Author performance
claims below were not independently reproduced during this research.

## Stars in the inspected dedicated-miner sample

Repository metadata came from the public GitHub API and official repository
pages. All five had GitHub's `fork` flag set to `false`; that flag describes
GitHub's repository relationship, not independent authorship or absence of
derived code. Pearl M-Miner's derivation from pearl-metal-miner remains disclosed.

| Rank within this sample | Repository | Stars | License / distribution |
| --- | --- | ---: | --- |
| 1 | [Pearl M-Miner](https://github.com/parkerkyle-max/pearl-m-miner) — this project | 1 | Apache-2.0 |
| =2 | [Augustas11/pearl-apple-miner](https://github.com/Augustas11/pearl-apple-miner) | 0 | Apache-2.0 |
| =2 | [Breakwater-ecosystem/pearl-metal-miner](https://github.com/Breakwater-ecosystem/pearl-metal-miner) | 0 | Apache-2.0 |
| =2 | [MoonShiesty/pearl-apple-miner](https://github.com/MoonShiesty/pearl-apple-miner) | 0 | Python code MIT; bundled native binaries have a separate restrictive license |
| =2 | [Pearly: pearly-miner/pearly-releases](https://github.com/pearly-miner/pearly-releases) | 0 | Proprietary binary releases and EULA; not an open-source miner |

The former `jonathanbtc/pearl-metal-miner` resolves to
**`Breakwater-ecosystem/pearl-metal-miner`**; the
[GitHub repository API for the old name](https://api.github.com/repos/jonathanbtc/pearl-metal-miner)
returned that canonical full name. They are one upstream, not two competitors.
[Pearly's official website](https://pearly.dev/) links to
`pearly-miner/pearly-releases`; unrelated repositories named `pearly` must not be
counted as that miner. The observed Pearly release was
[v1.0.3](https://github.com/pearly-miner/pearly-releases/releases/tag/v1.0.3).

## Current comparison and next candidates

| Project | Relevant backend / protocol | Comparison status and limits |
| --- | --- | --- |
| pearl-metal-miner | Hand-written Metal NoisyGEMM, transcript and BLAKE3 GPU work with host proof machinery | First integrated experimental control: 0.2.4 at commit `3d4cc7dadbd1de98ba20e9beb162806a0e70266b`, plus disclosed cert3 compatibility. Original native host and GPU kernels are unchanged. |
| Augustas11/pearl-apple-miner (`pmk`) | Rust host and Swift/Metal kernels with exact int8/int32 GEMM; README explicitly describes cert3 and cert4 | Next candidate for a **cert3-only** adapter. Not integrated. Its TOPS / TOPS-equivalent labels cannot automatically be treated as our PRL TH/s. No result or advantage is promised. |
| MoonShiesty/pearl-apple-miner | MLX GPU, optional ARM SME CPU on M4 and newer; Stratum V1 pool and solo paths | Not integrated. Its published K=2048, rank=128 and mixed CPU+GPU results do not match this project's K=4096 GPU comparison. Current certificate compatibility and a GPU-only run need verification first. |
| Pearly | Native macOS GUI; Metal 4 int8 tensor route aimed at M5 GPU neural accelerators; PRL and a separate Ycash mode | Not integrated. Proprietary distribution prevents source-level timing/proof audit. Any future test would be an optional, user-installed black-box comparison with a separately disclosed scope. |

The integrated upstream control is included as retained source with its original
license and notice. It builds offline in a separate directory; users do not need
to install another miner. Its source manifest, exact compatibility patch and
build identities are described in the [control documentation](../comparators/pearl-metal-miner/README.md).
The baseline must be labeled **0.2.4 + cert3 compatibility**, not an unmodified
end-to-end upstream release or its latest branch. The
[historical M2 report](M2_VALIDATION_20261030.md) records the earlier matched
manual control; it is not hardware acceptance of the new comparison runner.

Augustas's README reports M3 Ultra measurements and mainnet HeroMiners shares,
but the underlying raw logs were not public in the inspected documentation.
Its cert4 regression-network evidence and cert3 results are distinct; neither
establishes a cert4 public-pool comparison with Pearl M-Miner. Before adding an
adapter, match the protocol, accepted proof format, work size, timing denominator
and device. See the [project's own documentation](https://github.com/Augustas11/pearl-apple-miner).

MoonShiesty's repository API reports MIT, but its
[binary license](https://github.com/MoonShiesty/pearl-apple-miner/blob/main/BINARY-LICENSE)
separately restricts modification and reverse engineering of bundled binaries.
Do not describe the whole distribution as unrestricted MIT source or reuse those
binaries as a modifiable reference implementation.

Pearly's inspected release documentation targets macOS 26+ and an M5 Max test
configuration, lists a 2% developer fee, and says M1–M4 were untested by that
project. It also describes a PRL stop condition after a proposed FP8 activation;
that release is not evidence of a cert4 comparator. Its separate Ycash mode
cannot be included in a PRL speed comparison. These are release-specific claims
from [Pearly's repository](https://github.com/pearly-miner/pearly-releases), not a
prediction of future compatibility.

## Related projects excluded from this ranking

| Repository | Observed stars | Reason for separate treatment |
| --- | ---: | --- |
| [open-jarvis/OpenJarvis](https://github.com/open-jarvis/OpenJarvis) | 12,527 | Stars belong to a broad AI framework, not a dedicated miner. Its [Apple Silicon mining guide](https://github.com/open-jarvis/OpenJarvis/blob/main/docs/user-guide/mining-apple-silicon.md) describes a real experimental PyTorch MPS GPU path with CPU hashing/proofs and validator-accepted PlainProofs, but solo node/gateway support rather than pool mining. A custom high-performance Metal kernel is future work. Apache-2.0. |
| [minerjed/open-pearl-miner](https://github.com/minerjed/open-pearl-miner) | 0 | NVIDIA/AMD implementation; Apple Metal is only on the roadmap. Its [custom license](https://github.com/minerjed/open-pearl-miner/blob/main/LICENSE) includes developer-fee retention, so it is not plain MIT. |
| [prlgts/pearly-gates](https://github.com/prlgts/pearly-gates) | 0 | NVIDIA RTX 50-series PRL project, not the Mac Pearly application. No asserted license was returned by the inspected API metadata. |
| [filipef101/pearly](https://github.com/filipef101/pearly) | 1 | A React Native password/notes vault, not a miner. PolyForm Noncommercial license. |

BTC and XMR miners are excluded because a different algorithm's H/s cannot rank
PRL throughput. A roadmap entry, a framework's total stars or a similarly named
repository does not establish an available Apple Silicon PRL GPU comparator.

## Fair comparison requirements

Use the same physical Mac, exact GPU/memory configuration, power conditions,
protocol and requested work shape. Retain every timed run, cooldown, version,
source/build identity and failure. Separate warmup from the measurement; do not
mix pure GEMM TOPS, cached hot loops, different K values, GPU+CPU totals, offline
PRL throughput, pool estimates or payouts into one ranking.

The experimental runner measures fresh preparation plus completed scans and
checks correctness separately before and after timing. A failed gate, thermal
or battery interruption, or timeout produces no ratio. A slower valid result
remains a valid result. Community reports are self-reported and require review
before inclusion in the public matrix. Follow the
[community testing guide](COMMUNITY_TESTING.md) to inspect the plan, run a bounded
test and decide whether to share it.
