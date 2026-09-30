# H11953 full native depth-band footprint — September 30, 2026

Qualifies the original 1 m shallow band and expands the reviewed 2/4/8 m
windows to include their full valid pixels. All four are NOAA's same 2008
acquisition, not independent evidence. No downsampling, invented uncertainty,
new thresholds or interpolation-mask claim.

The 1 m BAG has a 338-million-cell envelope but only 6,417,802 valid pixels.
A bounded full-grid scan found those inside a 20,789,118-cell native rectangle.
The reviewed geographic window includes every valid pixel and remains below
the existing normalization bound. No guard needed to be raised. Full-band
counts also match originals: 2 m 6,281,842; 4 m 4,666,652; 8 m 307,433.
[Receipt](../../research/receipts/seafloor-h11953-full-native-review.json)
contains hashes, geometry, metadata, scientific identities and counts.

Measured Tier 1 gains 14.415 km²; selected valid footprint gains 13.084122 km².
Screened habitat decreases 8.978501 km² under the existing relative extraction
method. New native pixels recalculate reach-wide roughness thresholds; we do
not alter those to keep prior dots. This does not prove greater biological
accuracy. The current pixel-weighted mixed-resolution thresholds are an
explicit methodological limitation for future versioned science review.
Each survey is still processed at its own native spacing; no coarse bathymetry
becomes invented fine detail. r05 remains a source gap.

Commands: `promote-survey` for the saved shallow draft; `ingest` plus reviewed
`qualify_row` for expanded cached band windows; `run --reach REACH --fetch`
for r06/r07/r08; regenerate receipts and run seafloor GIS/contract checks.
All physical polygons checked within nominal 0–300 ft and 1/2/4/8 m native
spacing. Current-head full CI and production/public bytes are publication gates.

Next: implement a reviewed ArcInfo GRID archive adapter for the original USGS
1998 SGF5G/SUR5G downloads. Metadata and real archives were retrieved at their
original publisher; these are 5 m acoustic depth grids, not shaded-relief TIFFs.
Actual shallow coverage, datum, rights and format still need native review.
This is a promising route into previously unmapped Carmel/Point Sur reaches.
Keep this source batch separate from the new-format implementation. Whole
Monterey–Point Conception goal remains active.
