# Southern Monterey spatial release — September 30, 2026

Whole-polygon planning screens now cover Monterey/Carmel/PointSur r01–r04 and
the small northern BigSur r01 intersection. Original current CDFW and NOAA
inventories were refreshed successfully. All MPAs remain excluded, including
areas with species-specific permissions. Season/gear, harbor conditions,
notices and moving-vessel security remain trip-time decisions.

FortOrd334.1150 is still law: no claim it is inactive. Geodesic sampling of both
8,000yd307° boundaries puts their southernmost latitude at36.629722. With a
conservative500m south allowance the bound is36.625177. The entire reviewed
reference-cell envelopes lie below36.616142, and the policy stops at36.62.
The separate Navy mining area lies substantially farther north even using
nautical miles and a deliberately all-southward distance bound.

Monterey165.1183 establishes moving500yd/100yd vessel buffers. A new reusable
`reviewed_notice_sections` policy list hash-checks these reviewed out-of-scope
or trip-time rules at every refresh without inventing stationary polygons.
Any changed/missing section invalidates the screen for review. This extends the
existing boundary hash gate rather than bypassing it.

| Reach | Passing whole polygons | Screened habitat km² | Physical reused |
| --- | ---: | ---: | --- |
| Monterey r01 |258|3.440726954|No — new source intersects|
| Monterey r02 |14|0.153591020|No — new source intersects|
| Monterey r03 |91|2.069371195|Yes|
| Monterey r04 |541|3.906197847|Yes|
| BigSur r01 |0|0|Yes — metric support incomplete|

904 polygons /9.569887km² pass locally. Direct intersection against every
original exclusion Polygon component independently found zero overlaps.
370 held candidates overlap MPAs;87 have incomplete metrics/contracts, with
some overlapping reasons. Entire conflicted candidates are held, never clipped
into apparently safe remnants.

Refreshing r01/r02 with the newly qualified shelf sources additionally adds
3.840612km² selected valid survey footprint and4.3125km² Tier1 planning-cell
area. This is measured expansion in those existing reaches, not five new reaches.
Do not count it as independent survey confirmation.

Evidence: [review receipt](../../research/receipts/seafloor-monterey-spatial-screen-review.json).
Private logs: `var/seafloor/monterey-screen-refresh.log` and
`var/seafloor/monterey-release-*.log`. Ordinary refresh/run commands were used;
all candidates still need a successful current production publication and
actual live-map verification. Source ranking rules are unchanged.

Validation: screen regression tests exercise current original sections,
changed hashes, missing/wrong sections, invalid classification, whole-polygon
MPA overlap, source completeness and expiry. Next: merge after all CI passes,
verify published Monterey range bytes/outlines, then continue southern-coast
native-source gaps. Coastal mapping remains incomplete.
