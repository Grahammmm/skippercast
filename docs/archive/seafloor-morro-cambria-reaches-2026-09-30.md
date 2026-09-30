# Morro/Cambria measured reach batch — September 30, 2026

Reconciled #91/#94 physical reach work against current main after #123, #118
and #124. Reused existing original USGS surveys and native physical caches.
No source qualification, code, science threshold or spatial policy changed.

| Measure | Main after #124 | This batch | Added |
| --- | ---: | ---: | ---: |
| Tier 1 reference-cell coverage, km² | 428.854375 | 518.531875 | 89.677500 |
| Selected valid native footprint, km² | 420.034382 | 507.011262 | 86.976880 |
| Screened habitat, km² | 15.578340 | 15.578340 | 0 |
| New physical patches / supported ranks | 0 | 618 / 601 | 618 / 601 |
| New public/exported locations | 0 | 0 | 0 |

| Reach | Measured km² | Selected native km² | Patches / supported |
| --- | ---: | ---: | ---: |
| morro-bay-r05 | 20.304375 | 19.861929 | 145 / 144 |
| morro-bay-r06 | 61.748125 | 60.023595 | 412 / 399 |
| cambria-san-simeon-r02 | 7.625000 | 7.091355 | 61 / 58 |

[Receipt](../../research/receipts/seafloor-morro-cambria-reach-batch.json)
records exact source IDs, run/physical hashes, supported species ranks and holds.
Seventeen catalog reaches have physical assessments; three lie north of the
requested Monterey boundary. The fourteen within scope have partial original
survey footprints, not fourteen completely mapped coastal segments.
All new candidates remain private; seventeen have incomplete metrics and no
rank. The Point Buchon resampled deep grid is excluded from fine habitat.

## Validation and reproducibility

Pinned `.venv`, `PYTHONPATH=src:.`. Run the existing `seafloor run --physical-only
--fetch` command for the three reach IDs above. All returned `unchanged: true`
on fresh main after #124. 100 focused tests and 2,980 subtests passed. Verified
all new candidates stay at nominal depths <=300 ft, are non-exportable, and
public habitat outputs are empty. Receipt manifest and repository checks pass;
no raw files or private candidate coordinates are committed.

## Whole-coast goal and exact next action

This is a checkpoint, not completion. #123 fixed lossless COG encoding failures;
production run [36746523237](https://github.com/Grahammmm/skippercast/actions/runs/36746523237)
passed real Linux worker and publication verification. Its screened habitat
delta was zero. A later direct Morro manifest returned `updating` during the
next run, so current live expansion has not been asserted.

Next review Morro permanent restrictions as one regional sweep, refresh original
CDFW/NOAA/eCFR sources, extend reviewed reach scope only with documented evidence,
rescreen saved candidates without recomputing terrain, and verify ready live
manifest and PMTiles range bytes. Then perform the Monterey sweep and reconcile
Vandenberg #110 before releasing Conception candidates. Continue native source
search for Carmel/Big Sur and northern Point Arguello. Do not repeat the empty
Carmel NOAA NOS query or bypass the CSUMB TLS certificate mismatch.

Fresh original USGS Point Conception metadata returned HTTP200 with SHA256
`47130b72a75866bb54cea58180f72d73bda9bc5d690fe48536e3480a0a91f7a0`.
It describes a 2013 merged acoustic/lidar TopoBathy product; delivered 1 m pixels
must not be treated as independent original 1 m sounding detail without upstream
review. Do not download/regrade it blindly as an independent survey.

Private resumable state: `var/seafloor/coastal-goal-progress.json`, per-reach
receipts, `var/seafloor/next-morro-cambria-ledger.json`, and test logs. Never copy
an older entire ledger over fresh main: apply only validated reach summaries.
