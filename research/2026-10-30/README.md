# Isolated M1 Max optimization candidates

These patches are retained experiments, not enabled production features. Apply
only one to a disposable checkout of Alpha 2 (`8f1af9a7c5e590a0011e0d7af7d689528565dc37`).
Stop other GPU miners before correctness gates or timing. Retain temperature,
battery and thermal-pressure protection. Do not copy an old self-test receipt.

- `private-transcript.patch`: uses GPU-private transcript storage for scans
  without CPU export, checking storage mode as well as capacity on reuse.
- `register-fold.patch`: register XOR and 64 partial words instead of a full
  4096-float store/reload. Every threadgroup validates the actual accumulator's
  complete layout in that same compiled pipeline. A mismatch uses the original
  path. Diagnostic controls cover forced fallback and injected mismatch.
- `register-fold-unroll.patch`: the same complete guard, with an explicitly
  expanded 32-slot loop. No layout-qualification cache or skipped check.

All candidates retain the 32 required prefixes, exact integer bounds,
generation/target binding and official proof construction. Correct outputs
do not establish a speed improvement. Full results are in
[the optimization report](../../docs/OPTIMIZATION_20261030.md).

Apply a single patch with `git apply --ignore-space-change PATH_TO_PATCH`;
Alpha 2 contains some CRLF source files, while these patches use LF context.
Rebuild with `sh bootstrap.sh`. Example gate commands from the disposable root:

```sh
.venv/bin/pearl-m-miner self-test

PYTHONPATH=tools/prefix_s_miner .venv/bin/python \
  research/2026-10-30/check_register_fold.py \
  --library tools/prefix_s_miner/libprefix.dylib \
  --shader tools/prefix_s_miner/prefix.metal \
  --output register-fold-gate.json

.venv/bin/python research/2026-10-30/check_private_scan.py \
  --source . --library tools/prefix_s_miner/libprefix.dylib \
  --shader tools/prefix_s_miner/prefix.metal

.venv/bin/pearl-m-miner benchmark --seconds 45 --region-rows 512
```

The register gate applies only to the register-fold patches. The private-scan
gate applies to either candidate and compares all 512 small-grid transcripts,
digests and hit decisions while alternating exported/non-exported scan modes.
Re-run the baseline between candidates, preserve failed results, and check real
pool acceptance before adopting a computational change.
