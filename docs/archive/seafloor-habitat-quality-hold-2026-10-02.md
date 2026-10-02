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
screen retains. Other sources can pass normally. Both monolithic and tiled
extraction use the same feature constructor.

Publication rejects a quality hold found in the feature, its hold reasons, or
the current source catalog, even if a stale feature claims it passed screening.
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
processing agree. A current and repeated legal pass keeps the quality hold while
another source remains eligible. Publication rejects each stale-pass variant,
and manifest validation rejects mismatched or unsupported review metadata.

The independent review and exact-head CI are required before merge. Production
must rebuild with the current implementation before any new source batch is
claimed live. A quality correction and a measured-coverage increase are reported
separately from changes in published habitat counts.
