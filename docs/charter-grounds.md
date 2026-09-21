# Charter-reported grounds

Purple boat labels make reported charter fishing areas distinct from A/B/C terrain candidates. Tap a label for the boats, trip dates, reported species, source pages and location limits. The layer appears for lingcod and rockfish. **These are reported named grounds, not exact charter stops, AIS tracks or a prediction of today's bite.**

## Evidence obtained on September 21, 2026

The research read 173 daily pages covering April 1–September 20, 2026, from [SoCalFishReports](https://www.socalfishreports.com/dock_totals/boats.php?date=2026-09-17). The sample contains 601 trips attributed to Morro Bay or Avila Beach. [Patriot Sportfishing](https://www.patriotsportfishing.com/) links its fish counts to the same publisher network; [Virg's Landing](https://www.virgslanding.com/boats/ritag.php) explicitly credits SoCalFishReports. These are landing-reported facts, not independently observed catches.

| Named ground | Single-ground trips | Boats | Latest sampled report | Location evidence |
| --- | ---: | --- | --- | --- |
| Pecho Rock | 11 on 11 dates | Flying Fish, Sunny Day, Patriot (Avila Beach) | [September 17, 2026](https://www.socalfishreports.com/dock_totals/boats.php?date=2026-09-17) | Named landmark vicinity; no GPS or fishing depth |
| Diablo | 20 on 20 dates | Sunny Day | [September 2, 2026](https://www.socalfishreports.com/dock_totals/boats.php?date=2026-09-02) | Named coast; no exact stop or boundary |
| Morro Bay | 14 on 10 dates | Fiesta, Rita G | [May 18, 2026](https://www.socalfishreports.com/dock_totals/boats.php?date=2026-05-18) | Broad regional name; location confidence low |

The [public dataset](../dist/data/charter-grounds.json) contains each dated trip's boat, species and source link, plus per-page retrieval timestamps, integrity hashes and coverage. It records facts and concise original notes; raw HTML, article text, photos and audio stay outside the repository. The original publisher retains rights in its material. This is a dated snapshot, with no automatic refresh claim.

Of the other records, 344 have no ground label and 164 say only “Out Front.” Point Sal, Purisima Point and Shell Beach are outside the requested Avila–Cambria area. Nine multi-ground reports are not allocated to one place: catch totals do not reveal which ground produced the fish. Incidental salmon and halibut records do not support species-specific hotspot outlines. Reporting frequency is not fleet popularity, catch rate or standardized fishing effort.

## What the outline means

The reports do not supply boundaries. We construct **search water** around their named places, then apply the existing conservative depth and closure screens:

- Pecho Rock: a 1.25-nautical-mile window around the [CDFW geographic reference](https://nrm.dfg.ca.gov/FileHandler.ashx?DocumentID=170559), 35.17938° N, 120.81661° W. The rock is a landmark, not a waypoint to fish or navigate onto.
- Diablo: a two-nautical-mile window around the Diablo Canyon geographic reference in [33 CFR 165.1155, published 2025 edition](https://www.govinfo.gov/content/pkg/CFR-2025-title33-vol2/pdf/CFR-2025-title33-vol2-sec165-1155.pdf). The security area and MPAs are excluded, leaving southern search water. The chosen radius and interpretation are not reported charter positions.
- Morro Bay: the reviewed offshore Morro Bay survey between 35.30° and 35.43° N, within a broad construction box from 121.02° to 120.80° W. These boundaries are editorial limits on a regional reference, not a claimed fishing footprint.

The radii and box are planning choices, disclosed in each card. They must not be interpreted as uncertainty bounds with statistical confidence. Search areas may overlap. A reef inside an outline is a nearby habitat candidate, **not evidence of a charter visit to that reef**. The card offers up to four nearby candidates ordered by their unchanged terrain scores.

`scripts/build_charter_grounds.py` uses the reviewed USGS 2008 bathymetry, fully covered native pixels aggregated to the 10 m analysis grid, and minimum/maximum depths of 25–195 ft MLLW. It excludes the existing closure screen with a 505 m buffer, erodes eligible water by 20 m, applies a 12 m inward buffer and 8 m simplification, and keeps connected parts ≥0.1 km². It never bridges deep water, survey gaps or closures. It rechecks all cells touched by the final rounded outline. This depth screen applies to the displayed search water; **the original charter trips' fishing depths are unknown**. Actual water depth changes with tide.

The Point Buchon [CDFW MPA page](https://wildlife.ca.gov/Conservation/Marine/MPAs/Point-Buchon) was read on September 21. The published 2025 security rule was read that day; the direct current eCFR endpoint returned HTTP 406, so no successful current eCFR read is claimed. The stored geometry is dated September 16 and receives an extra planning margin, not a declaration of live legal access. Recheck current rules and boundaries before fishing.

## AIS remains separate

The previously obtained eight daily NOAA samples still contain zero independently verified local sportfishing-charter identities. This turn also checked the `TRY MAGIC` name lead: its reported 14 × 10 m dimensions and sailing type do not match the [26 × 9 ft Magic charter listing](https://sportfishingreport.com/charter_boats/magic-morrobay.php). It contributes no charter-track evidence. No raw individual vessel trajectory is published.

The older DS1091 interview-based fishing-ground layer remains excluded while reuse terms are unresolved. This new report layer does not reuse it or restore its annotations. See [source rights and AIS coverage](data-sources.md#ais-evidence).

## Reproduction and checks

Use `scripts/collect_charter_reports.py --start 2026-04-01 --end 2026-09-20 --output /path/outside-repository` to collect the public pages with two concurrent requests, cache raw responses and record failures. Then run `scripts/build_charter_grounds.py /path/to/report-research /path/to/waypoint-research` with the GIS dependencies documented in that script. The bathymetry and original closure inputs are deliberately not bundled; their source register is in [data sources](data-sources.md). No API key, paid archive or private captain log is used.

`node --test tests/test_charters.mjs` checks source/date consistency, unique trips versus dates, coverage totals, species safeguards and whole-outline depth filtering. Native-grid and closure validation runs in the builder. The static CI checks do not claim to re-fetch live rules or independently repeat raster validation.
