# Morro and Arguello spatial release screen — September 30, 2026

Expanded the permanent planning screen to Morro Bay r01–r08 and Conception r06.
Reconciled the geometry implementation/review proposed in #110 without editing
that branch. Current eCFR title 33 is up to date through September 28. Fresh
original section requests returned HTTP200 and exactly matched the reviewed
Diablo Canyon and Vandenberg Zone 4 hashes. Reviewed full parts 165/334 for local
applicability; hashes and specific findings are in the
[receipt](../../research/receipts/seafloor-regional-spatial-screen-review.json).

The Morro entrance [33CFR165.1196](https://www.ecfr.gov/current/title-33/section-165.1196)
RNA is a conditional navigation rule. Its published NAD83 closed polygon is
excluded from fishing/stopping recommendations with a 25 m outward planning
margin; this does not forbid permitted transit or claim the bar is closed.
[Diablo165.1155](https://www.ecfr.gov/current/title-33/section-165.1155)
uses its NAD83 2,000-yard circle plus 1 m. [Vandenberg334.1130](https://www.ecfr.gov/current/title-33/section-334.1130)
Zone 4 prohibits stopping/loitering without permission. Its unspecified-datum
coastal vertices are overcovered by the reviewed inland closure and 250 m margin.
This is deliberately conservative, not an exact surveyed regulatory boundary.
Other launch zones, mobile security zones and annual fireworks still require
trip-time notices. All CDFW MPAs and NOAA GEA/CCA/YRCA polygons remain excluded.
Season/depth/gear regulations and harbor permission are separate checks.

## Local result, not live publication

2,894 supported polygons pass across 41.143323 km², including 2,821 in Morro and 73
in Conception r06. Compared with the previous 1,014 screened polygons, this adds
1,880 spatially screened candidates and 25.564983km². No new measured survey
coverage is created by screening. Held polygons remain private.

Every passed polygon was independently rechecked against the union of every
current MPA, federal and security layer: zero overlaps or boundary touches.
102 focused tests and 2,980 subtests passed, including frozen original legal
sections, changed text/coordinates, datum ambiguity, coastal envelope, channel
vertices, outside candidates, whole-polygon overlap and expiry. Three cached
physical results were reused; six older identities differed and were rebuilt
once under current inputs. Legal snapshot remains outside the physical key.
No sounding resolution, native source checksum or ranking threshold changed.

## Deployment and next action

Merge only after current-head CI. Main changes trigger the existing seafloor
workflow to refresh current sources, rescreen saved candidates, publish scoped
PMTiles and verify public bytes. Local tippecanoe is unavailable; no local R2
upload or live polygon count is claimed. Inspect the resulting production
summary and ready public manifest/range response. The current app's seafloor
layer is opt-in: follow with a separate product PR to make the reef habitat
layer discoverable/default for lingcod/rockfish without enabling coverage-grid
clutter. Do not conflate its new polygons with the older manually curated dots.

Then review Monterey 334.1150 and mobile zones 165.1183 before expanding that
screen; continue Conception r07/r08 security review and Carmel/BigSur original
survey gaps. The full Monterey–Point Conception goal remains incomplete.
Private current snapshots/candidates/runs stay under `var/seafloor/`.
