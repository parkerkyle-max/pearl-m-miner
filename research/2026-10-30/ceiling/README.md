# M1 Max arithmetic ceiling and exact row splitting

Research sources for the [2026-10-30 report](../../../docs/M1_CEILING_20261030.md).
The parent directory is not an automatic deployment tool. Nothing here opens an
SSH connection, installs a miner or changes a wallet. The production miner keeps
its documented optional 1% active-scan contribution.

- `peak/`: 8x8 repeated-input half/float arithmetic and 64x64x128 MPP references;
  GPU timestamps and measured-window wall throughput are distinct.
- `peak_stream/`: every inner iteration consumes a different runtime A/B pair.
  This corroborates arithmetic with more memory traffic; it is not a pure peak.
- `ablation/`: exact frozen sources for component-only measurements and rejected
  BLAKE3 candidates, plus the qualified `prefix_pair32_release.metal`.
  `prefix_pair16.metal` is a correctly computed but slower comparison, not the selected default.
  Repeated component work never earns protocol credit or submits to a pool.
- `cpu/`: public Accelerate SGEMM with full int64 comparison; AMX execution and
  mining income are not established by this benchmark.
- `research_worker.py`: real fresh-grid offline scans, including preparation.
- `check_private_scan.py`: 512 independent transcript/digest/target checks on
  production non-export scans. Use it with official proof gates as described below.
- `source-manifest.json`: exact saved source hashes; documentation is separately
  explanatory. Raw measured outputs are indexed in the report's JSON receipt.

Build the normal miner first with its documented bootstrap, then select its
Python environment. Pause any GPU miner before experiments. Retain temperature,
public thermal-pressure and external deadline supervision, and restore the
original miner after testing. These standalone executables do not perform that
operator lifecycle for you. Private operator scripts are intentionally omitted.

Example from the repository root, with a qualified Mac/SDK:

```sh
ROOT="$PWD"
LAB="$ROOT/research/2026-10-30/ceiling"
sh "$LAB/peak/build.sh"
"$LAB/peak/peak" --mode half --shader "$LAB/peak/peak.metal" \
  --groups 1024 --simdgroups 4 --chains 8 --warmup 20 --seconds 300
```

For a shader candidate, run the existing `tools/prefix_s_miner/check_sparse_native.py`
with `--miner-root "$ROOT" --factory-root "$ROOT/tools/prefix_sparse_host"`, the
compiled `--library`, explicit `--shader`, and `--method s`. Repeat with
`--m 16384 --n 65536 --full-export-only`, then run `check_private_scan.py` with
`--source`, `--library`, and `--shader`. Only after those gates pass, use
`research_worker.py` with the same explicit paths and `--seconds 60 --region-rows 512`.
Interleave baseline and candidate runs. A successful local proof gate is distinct
from a real pool response; never convert a component timing into income.

The row-split candidate changes only `prefix_pair`, retains all 32 prefixes and
the same MAC count, and uses public tensor stores/barriers. The release copy's
only change from the first measured candidate was removing its offline-only
comment; it then received its own proof gates and sustained trial.

Use these tools to qualify other chips. M1 measurements do not prove gains on
M2-M5, Neural Engine mining or compatibility with a future FP8 consensus.
