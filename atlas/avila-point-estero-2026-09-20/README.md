# Avila–Point Estero public atlas

**132 habitat candidates · 107 partial reef outlines · 31 optional drift alignments**

Edition: `2026-09-20-public-1`. This is dated research for recreational rockfish and lingcod fishing within a 200-foot personal fishing limit. Locations are inferred from mapped terrain, not verified catches or AIS-confirmed charter hotspots.

## Download and inspect

| File | Use |
| --- | --- |
| [complete.gpx](exports/complete.gpx) | Import the full public edition once: points, outlines, and alignments |
| [spot-notes.html](exports/spot-notes.html) | Download and open locally for searchable notes on every target |
| [atlas.geojson](exports/atlas.geojson) | Inspect the interpreted features in GIS software |
| [waypoints.gpx](exports/waypoints.gpx) | Recovery option when an app did not import points |
| [reef-outlines.gpx](exports/reef-outlines.gpx) | Recovery option when an app did not import outline tracks |
| [drift-lines.gpx](exports/drift-lines.gpx) | Recovery option when an app did not import alignment routes |
| [manifest.json](exports/manifest.json) | Counts and SHA-256 checksums for the generated files |
| [atlas.json](data/atlas.json) | Reviewed, attributed input to the portable exporter |

Download the raw file rather than saving GitHub's preview page. Follow the [iNavX guide](../../docs/inavx.md). Do not import both the complete file and all component files: that creates duplicates.

## Coverage and evidence

The public edition contains 40 Point Buchon, 47 Morro Bay, and 45 Point Estero targets from USGS survey releases. Survey acquisition is dated 2008; included depths are relative to **MLLW**. Actual sounder depth can exceed a source-datum value as water level changes. Recheck the complete fishing footprint and current restrictions before a trip.

The original private research covered Avila–Cambria with 143 targets. This public edition omits its 11 Cambria targets, 10 Cambria outlines, and two Cambria alignments because those source terms are unresolved. It also excludes all sampled historical charter-ground annotations. The [source register](../../docs/data-sources.md) documents these decisions. The public edition does not replace an existing private iPad atlas.

Names such as `SC26-001-A` include a stable target number and a habitat grade. Missing numbers preserve the mapping to original IDs rather than pretending the omitted sites are present. Each target's `legacy_id` is recorded in the JSON and GPX note. Grades are **A: 35, B: 74, C: 23**; tied ranks compare only the 132 public targets. A higher score means more promising mapped structure to investigate, not more fish.

Outlines are partial, nearby footprints of mapped rough habitat. Holes are gaps in the selected habitat, not additional piles. Lines show structure alignment; measured wind and current determine whether and how to drift across them. Neither outlines nor lines are navigation routes. The notes distinguish these feature types and link points to associated outlines and lines.

## Validation and reproduction

The original research checked exact point positions, 100-m neighborhoods, complete area interiors, and 25-m corridors beside selected alignments against native survey grids and a dated closure screen. The included JSON preserves those recorded results. Running the public validator checks record consistency and thresholds; it does not repeat native-grid analysis or update law, tides, or the seabed.

The [quickstart](../../docs/quickstart.md#re-export-the-atlas) rebuilds all exports without a GIS dependency. The [methodology](../../docs/atlas-methodology.md) explains the terrain score and limits. Original native raster downloads and the complete original GIS pipeline are not included in this initial release.

The exporter writes coordinates to six decimal places, matching the recorded target positions; this precision does not imply centimeter-scale survey accuracy. Mixed GPX point/route/track import in the user's iNavX installation has not been verified for this public edition.

Underlying source rights remain unchanged; see [NOTICE.md](../../NOTICE.md). The source measurements, interpretations, and research layer are not current navigation or legal clearance.
