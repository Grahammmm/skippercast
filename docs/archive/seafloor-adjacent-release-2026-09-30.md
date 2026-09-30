# Adjacent Cambria and Conception release — September 30, 2026

Extends the reviewed permanent planning scope to Cambria r02 and Conception
r07/r08. The three physical caches were hash-verified and reused; screening
adds no measured area. Fresh complete CDFW/NOAA/eCFR snapshots passed.
The [review receipt](../../research/receipts/seafloor-adjacent-spatial-screen-review.json)
records the geographic and conditional-rule findings and exact original hashes.

[33 CFR 334.1130](https://www.ecfr.gov/current/title-33/section-334.1130)
permits fishing outside its restrictions: Zone 4 remains excluded; launches can
close other zones at irregular intervals. Current notices/radio/harbor checks
are required, and this planning screen does not claim those zones are clear.
San Miguel 334.1140 is geographically south of these mainland reaches; moving
Santa Barbara cruise security 165.1157 remains a trip-time requirement.
All MPA-overlap areas remain excluded regardless of possible permitted take.

Local result: 47 Cambria, 763 Conception r07 and 302 r08 polygons pass, adding
1,112 screened candidates / 13.244605 km². Every passing whole polygon was
independently checked against each projected exclusion-layer union: zero
overlap or boundary touch. Incomplete metrics and MPA-overlap candidates remain
held. No source bytes, native spacing or ranking thresholds changed.

Commands: `refresh-screen`, then `run --reach REACH --fetch` for the three
listed reaches; repeat physics was not required. GIS/contract tests, receipt
manifest, product regeneration and repository/web checks precede current-head
CI. Merge triggers production publication; verify ready manifest and exact
HTTP Range bytes before claiming live.

The full geographic goal remains active. Prior merged #127 public archives
were verified ready September 30: Morro 2,821 and Conception 73 polygons, exact
PMTiles HTTP206 range/header checks passed. #128 adds 475 more screened
Conception candidates but its newer production run was not yet verified.
Next expose the reef survey layer by default and replace its stale hardcoded
3-of-46 count; separately review Monterey 334.1150 and resolve original native
Carmel/BigSur/northern Arguello survey gaps. Zero-valid-data r05 remains unmapped.
