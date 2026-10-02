# Preserve depth coverage while reviewing habitat quality

An original survey can contain useful measured depth while its automatic terrain
candidates need further review. Treating that as an all-or-nothing source hold
either loses useful coverage or releases questionable fishing targets.

The motivating case is the original [PGE South producer archive](https://data.ngdc.noaa.gov/platforms/ocean/ships/ventresca/PGE_South/multibeam/data/version2/products/PGE_South_additional_products.tar.gz).
Its rough/smooth derivatives document subjective thresholds and manual artifact
exclusions, including vessel heave. Native comparisons found substantial
disagreement with automatic terrain candidates. The producer classes are derived
from the same depth survey: they are neither independent rock/sand evidence nor
a valid/invalid bathymetry mask. An absent rough classification alone does not
prove that a candidate is an artifact.

## Bounded pipeline change

A reviewed bathymetry row may now carry `habitat_quality_hold`, containing its
original source SHA-256, actual review date, an artifact-review or interpretation
reason, inventoried evidence pointers and explanatory notes. Schema and runtime
validation reject incomplete reviews, source-hash mismatches, future dates and
unregistered evidence. Removing the hold requires a separately reviewed source
change supported by resolving evidence; successful processing or a fresh legal
screen is not a resolution.

The source remains eligible for native depth selection. Terrain extraction still
computes the same polygons, identifiers, measurements and species fit. Its
candidates acquire `source-habitat-quality-review`, which the existing final
screen retains. Because roughness thresholds are calibrated across the reach's
selected grid group, every candidate in that group also receives
`habitat-threshold-quality-review` with the contributing quality-hold evidence.
A different source ID alone does not establish independence from a questionable
threshold contributor. Independently processed groups remain unaffected. Both
monolithic and tiled extraction use the same feature constructor.

The hashed candidate collection records `calibration_source_ids` from grids
actually selected for threshold calculation, including grids that produce no
candidates. Intersecting surveys that win no coverage cells are excluded. When
a current source hold exists, publication checks that verified inventory;
legacy or malformed inventories require recomputation. This avoids blocking
clear habitat merely because an unused coarser survey overlaps the reach.

Publication rejects a quality hold found in the feature, its hold reasons, or
the current source catalog, including shared calibration contributors, even if
a stale feature claims it passed screening.
Held candidate geometry does not enter public map tiles or fishing exports.
Current source-use, MPA and other spatial checks remain in force. The source
catalog is part of the cached input identity, so changing a review cannot reuse
an output whose source identity is obsolete.

This feature introduces no roughness thresholds, substrate classes, source
resolution changes, new surveys or automatic source approvals. The PGE source
qualification and its retained before/after receipts are a separate batch.

## Acceptance proof

Offline synthetic tests check that adding a hold leaves native depth, masks,
thresholds, geometry, IDs, metrics and species fit identical; tiled and ordinary
processing agree. A two-source fixture proves that a quality hold propagates to
indirectly affected candidates without changing their measurements. A current
and repeated legal pass keeps the quality hold; unrelated groups can still pass.
Publication rejects each stale-pass variant,
and manifest validation rejects mismatched or unsupported review metadata.

The independent review and exact-head CI are required before merge. Production
must rebuild with the current implementation before any new source batch is
claimed live. Until the PGE shared-threshold dependency has been separately
resolved, its new rows must remain `physical-only`, preserving private depth
work without changing the existing production source selection. The generic
control does not itself approve a PGE habitat release.

A quality correction and a measured-coverage increase are reported
separately from changes in published habitat counts.
