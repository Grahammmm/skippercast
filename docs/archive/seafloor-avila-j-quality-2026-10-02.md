# Preserve Avila J depth while reviewing habitat quality

Original CSUMB Avila Block J depth remains valuable as measured support, but
its automatic reef candidates need further artifact review. The producer's
same-depth rough/smooth product documents vessel-heave effects and manual
smoothing. Exact native comparisons found no producer-rough overlap for
832 of the 833 previously passing J candidates; none had majority overlap.
Native examples show narrow banded terrain on broad smooth slopes.

These observations justify containment, not a claim that every smooth pixel
or every candidate is wrong. The classification is not independent rock/sand
ground truth, nor is smooth an invalid-depth mask. Quantitative source
accuracy and the J 2 m acquisition/datum remain unresolved as before.

The source is now `physical-only`, with a persistent source-bound quality
hold. Default production selection excludes J. This also removes its effect
on shared thresholds: Morro r09 selected 35 J cells even though it produced
no passing J polygon. Recompute r09, r10 and Arguello r01 using unchanged
scientific rules and current whole-polygon restrictions.

| Public eligibility across the three reaches | Before | After |
| --- | ---: | ---: |
| Selected measured support, km² | 106.335550776 | 73.649008914 |
| Physical candidates | 2,153 | 1,206 |
| Spatially passing candidates | 2,008 | 1,138 |
| Passing habitat area, km² | 25.068119163 | 17.091635380 |

Private reruns retain all 2,153 original physical candidates, their exact
geometry, metrics, species fit, thresholds and selected depth cells. The
quality hold persists through private screening, and those outputs cannot
enter public tiles or exports. Public output bytes and the committed ledger
remain unchanged by private runs. Every remaining public-eligible polygon
passed the existing depth/fit checks and touched none of the current MPA,
federal or security exclusions.

This is a quality correction with zero new measured coverage, not a claim
that retained bathymetry disappeared. The 32.686541862 km² decrease concerns
public source eligibility; original data and private processing are kept.
Avila I is a separate unresolved follow-up and is not newly validated here.
No numerical threshold, mask, resolution, license or closure rule was relaxed.

Evidence: `research/receipts/seafloor-pge-avila-terrain-review.json` identifies
the original producer archive, native classification members and metadata;
`research/receipts/seafloor-avila-j-quality-review.json` records the decision
and reproducible aggregate before/after checks. Held geometry and original
rasters remain private. A later release needs separately reviewed artifact
or positive-support evidence and calibration tests. Fresh legal screening
alone cannot clear the source-quality concern.
