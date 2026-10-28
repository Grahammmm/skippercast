# Native inverse-projection portability

The committed native coastal-segment-v1 fixture remains byte-for-byte pinned.
Its EPSG:3310 bbox, ID, region, schema and CRS are checked exactly against the
native lattice producer. Plan-to-record coordinates, hashes and grid definitions
also remain exact. No fixture is regenerated to hide an invalid binding.

A source-free reproduction using pyproj 3.8.0 / PROJ 9.8.1 on Ubuntu 24.04
and Ubuntu 26.04 found the same inverse California Albers operation but different
last bits in latitude (densify_pts=41). This accounts for the twelve initial
survey failures: both versions produced identical longitude bounds; southern
latitude differed by one representable double, northern latitude by two.

For projected bbox [-55000,-400000,-50000,-395000]:

- Ubuntu 24.04 latitude bounds: 34.41455257638639, 34.459879190790716
- Ubuntu 26.04 latitude bounds: 34.4145525763864, 34.45987919079073
- Differences in degrees: 7.105427357601002e-15, 1.4210854715202004e-14

The adapter therefore accepts at most two adjacent representable doubles in
EITHER direction, ONLY when recomputing geographic inverse bounds. It uses
math.nextafter twice, not an absolute or relative geographic epsilon. Three
representable steps refuse; malformed and nonfinite bounds refuse. The same
comparison is used when matching a campaign's regenerated lattice record,
without changing the exact comparison of every other field. Scientific
acceptance is still not implied by graph validation.

GIS-dependent graph tests now live under tests/gis, including the transitive
materialize/populate_admission/segments.from_bbox and committed graph validation
paths. The 35 real-admission cases are unchanged. Pure schema-source imports,
reference namespaces, sampling, adjacency, routing and write-once tests remain
in core; no missing-dependency importorskip or GIS dependency was added to core.
