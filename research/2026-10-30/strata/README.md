# Serial encoder reuse experiment

The candidate differs from the qualified native host only in `pfx_scan`: reuse
the serial compute encoder for the hash stage and insert an explicit buffer
barrier after prefix dispatch. No numerical, job, proof or fee rule changes.
It is an original patch inspired by Strata's scheduling design; no Strata source
was copied. The controlled full-work trials found no meaningful gain, so this
candidate is **not** the production default. See [study](../../../docs/STRATA_REVIEW.md).

Build it with the same clang flags as `tools/prefix_s_miner/build.sh`, giving the
output a separate name. Use the qualified pair32 shader. Run the official gate,
the production-dimension gate and the non-export scan gate before interleaved
60-second fresh-grid trials. The operator must stop other GPU work, keep thermal
and deadline guards, and restore the original miner. This source does not manage
that lifecycle itself.
