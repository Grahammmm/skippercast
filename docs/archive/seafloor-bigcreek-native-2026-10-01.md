# Big Creek and Lopez Point native survey qualification

Qualify six existing original grids from the CSUMB Big Creek archive: north,
south and Lopez Point, each at 2 m and 5 m. Replace their catalog rows in place,
preserving original archive/COG hashes, native resolution, masks, reviewed
windows and ordering. The original and normalized data were already present
in private processing: **zero new measured coverage is claimed**.

The [original NOAA report](https://www.ngdc.noaa.gov/ships/ventresca/BigCreek_mb.html)
and archive byte range were checked against the complete 364,945,509-byte
archive, SHA-256 `5e688dae2eca47844cf9727f70d212b0492e0d28e0aa5b261acbd8911dd2ada1`.
Original XML identifies CSUMB for all six grids. Five previously unknown
publisher/year fields are corrected using that evidence; these are scientific
input changes and require ordinary processing, not unchanged-science adoption.
The remaining north 2 m row changes release fields only.

## Source limits

The survey includes May 2010 work and an August 2009 versus August 2010 metadata
conflict, retained in the registered source receipt. Latest acquisition year
2010 is distinct from metadata or distribution dates. The producer documents
NAVD88/Geoid09 and NAD83/UTM 10N; no conversion to a navigation-chart datum is
claimed. Specifications call for 2 m grids at 0–85 m and 5 m grids at 80–250 m.
Actual valid native pixels within nominal 0–91.44 m were checked, rather than
inferring coverage from these design ranges.

The original grids are sonar-derived, producer-interpolated surfaces. Quoted
approximate ±2 m horizontal and ±0.20 m vertical accuracy varies with depth and
has no separately verified confidence statement. Per-cell uncertainty and
measured-versus-filled masks remain unknown. Six products and multiple
resolutions do not represent six independent acquisitions.

The deduplicated existing shallow footprint is 26.735756 km², across Big Sur
r03/r04/r05. This is source coverage, not habitat area or fishing permission.
Credited noncommercial use follows the
[CSUMB SFML terms](https://csumb.edu/undersea/sfml-data-library/), with the existing
for-profit gate and not-for-navigation notice retained. Raw files and held
habitat geometry remain private.

## Physical processing and spatial screening

Ordinary processing completes before spatial eligibility. Big Sur r04 was
missing from the reviewed reach list, so the first pass retained its candidates
privately. All 337 reference cells were then checked: their whole envelope is
longitude −121.654465 to −121.583524, latitude 36.030496 to 36.122423. It lies
inside the unchanged screen bounds and the already reviewed Big Sur latitude
band, north of Diablo Canyon/Vandenberg and south of Fort Ord.

Add only that reach ID and its scope explanation. The CDFW/NOAA exclusions,
fixed security coordinates, safety margins and trip-time notice requirements
are unchanged. A fresh original-source refresh completed October 2 at
05:30:46 UTC. Rescreening reused all three unchanged physical computations;
it did not recompute terrain or bypass any restriction.

| Reach | Eligible selected support, before → after | Physical candidates | Screened candidates | Screened habitat, before → after |
| --- | ---: | ---: | ---: | ---: |
| Big Sur r03 | 14.111440 → 15.695354 km² | 151 → 160 | 131 → 131 | 0.887380 → 0.926533 km² |
| Big Sur r04 | 0 → 15.061897 km² | 0 → 138 | 0 → 4 | 0 → 0.054782 km² |
| Big Sur r05 | 23.761611 → 31.383398 km² | 203 → 170 | 164 → 149 | 4.058198 → 5.921956 km² |

This is a comparison against the previous *usable-source* path, including
Slate Rock for r03, not against all earlier private computations. Eligible
selected support increases 24.267598 km². The final 468 physical candidates
split into **284 passing and 184 held**. Net screened count decreases by 11
while screened habitat increases 1.957694 km² as source selection and terrain
thresholds change. No thresholds were relaxed to increase counts.

All 284 passing polygons have zero intersections or boundary touches with the
checked CDFW, NOAA and security exclusions. Of r04's 138 physical candidates,
134 remain held. A survey of a marine reserve is not a fishing recommendation.
Existing 1–3 species-fit rankings remain habitat assessments, without asserting
fish presence or providing season/gear clearance.

## Reproduction and release

Use the canonical mapping skill and checked source recovery. Preserve row order,
perform normal runs for `big-sur-coast-r03`, `big-sur-coast-r04` and
`big-sur-coast-r05`, refresh the original spatial feeds and rescreen. Save the
before/after coverage, physical, screened and held measurements separately.

Validation passed 53 habitat, tiled-processing, manifest, source-rights, receipt
and screen tests with 3,514 subtests. Output hashes, nominal depth/rank limits
and independent full-polygon exclusion checks passed. Production must still
complete its protected merge and serialized publication, then verify the public
ready manifest and archive. Local success is not a live-publication claim.
