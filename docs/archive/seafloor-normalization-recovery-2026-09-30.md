# Recover portable native normalization — September 30, 2026

Worker logs from production run 36731694768 identify the actual failure:
`Normalized source differs from reviewed manifest`, before terrain computation.
Jobs reported handled failure receipts while their GitHub steps returned success;
aggregation subsequently reported a generic `no current completed result`.
The earlier Point Buchon handoff inferred aggregation rejection from this summary;
the worker logs now correct that diagnosis. No evidence of an MPA blocker.

This change adds a reviewed encoding-independent content identity for four usable
original sources. It includes exact float32 depth/uncertainty values, per-band
validity, identified CRS, affine, shape, descriptions, depth basis and datum.
Original-source checksums, cached encoded-file SHA256 and review metadata/count
checks remain mandatory. Legacy reviews without a content identity still require
the exact reviewed file checksum. A different lossless encoding may pass only
with matching reviewed scientific content. No arbitrary new COG bytes are blessed.

The content hash is streamed in 64-row stripes. Tests demonstrate different
lossless compression/block sizes change file bytes without changing science;
changed depth, uncertainty, mask, origin, datum or original identity fails.
Worker source-review failures now retain their specific diagnostic at aggregation,
without crediting stale state or publishing the affected region.

All four original sources were reingested and verified against their prior
reviewed scientific content locally. The review receipt preserves original and
old/new encoded hashes. Full Linux CI and a main-only production dispatch remain
required to verify portable equivalence on the actual cloud runtime.

A local proof processed Conception r06/r07 successfully with the revised checker:
24.291250 km² tier-1 reference-cell coverage and 22.064070 km² selected native
footprint, 477 physical patches (63 with incomplete metric support). All are held.
Those ledger changes are deliberately separate from this processing-fix PR;
private resumable evidence is in `var/seafloor/recovery-coverage-ledger.json` and
`var/seafloor/reaches/point-arguello-conception-r0{6,7}`. Neither PR totals nor
handled worker success should be counted as public coverage.

Next: pass checks and land the fix, rerun the production job once and inspect the
actual worker receipts/public manifest. Reconcile #118 on fresh main; add the new
content identity to its Point Buchon source before cloud execution. Reconcile
#97/#104/#91 source and ledger work using current sources and fresh generated
results, never replacing the entire newer ledger. Continue remaining original
source windows; review spatial scope and publish only passing polygons.
