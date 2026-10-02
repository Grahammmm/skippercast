# PGE South: preserve measured coverage for habitat-quality review

Four original CSUMB grids from NOAA's PGE South archive add 111.051791419 km²
of selected nominal shore–300 ft depth support across Morro reaches r08–r10
and northern Arguello r01. The 2 m F/G/H and 5 m G products share one survey
family. Native resolution, valid cells, NAVD88/GEOID03 metadata, unknown
quantitative uncertainty and interpolation mask, and original/normalized
checksums are retained. Credited noncommercial terms and the for-profit and
navigation restrictions remain in force.

These rows are `physical-only`. The producer's same-bathymetry rough/smooth
interpretations document manual vessel-heave exclusions. Native comparisons
and visual checks identified material disagreement: 1,172 of 1,195 direct
source candidates had no rough-class overlap. Smooth classification alone
does not prove bad depth or an artifact, and it is not a rock/sand observation.
No separate georeferenced artifact mask was identified in the archive review.

The private four-reach proof retains 4,255 physical candidates (1,091 more
than the earlier selections) and all 5,794 planning cells, including 4,649 with selected measured support. A second run with
explicit private source eligibility reproduced the candidate geometries,
measurements and ranks exactly; all candidates remain held and nonexportable,
all output hashes verify, and the public ledger was unchanged. Current-code
integration after the Avila J containment repeated all four private runs and
confirmed identical native geometries, metrics, ranks, thresholds and depth
cells after excluding only the new quality annotations from comparison.
Default public source selection matches the base branch exactly. These figures
are private processing results, not new publicly available fishing spots.
Held geometry, raw grids and caches are not in the public repository.

Source quality also affects shared percentile thresholds. Adding these grids
can change candidates from other source IDs, including a reach where the
new source produces no passing polygons. The default production selection
therefore excludes the entire unresolved batch. A later release needs a
reviewed artifact or positive-support method and tests of native alignment,
tiled equivalence, source dependencies and before/after results; a fresh MPA
screen cannot resolve the quality issue.

Evidence is in the four `seafloor-pge-south-*-review.json` source receipts,
`seafloor-pge-south-ancillary-review.json`, and
`seafloor-pge-south-habitat-quality-review.json` under `research/receipts/`.
They identify the original publisher archive and metadata. The source catalog
registers those receipts for future bounded processing. No scientific
threshold, rights gate or spatial-publication rule changes in this batch.
