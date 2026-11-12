# Rules check, November 2026: app rules text and data against official sources read on 2026-11-09

For the rules custodian. This is a checklist of where the app's rules text or rules data agree, disagree or are silent against official CDFW and NOAA statements. It changes nothing: no data, copy, hash, review record or test. It is not legal advice and not clearance for any trip.

## 1. Header and limits

| Item | Value |
|---|---|
| Official sources read on | **2026-11-09** (historical read; this report did not fetch any official page again) |
| Report written | 2026-11-10 |
| App checked | `Grahammmm/skippercast` main at `2e278b853ff36dd5285403774236992beecd32e9` (the spec was written against `3d13e7c0d7c375601b4eb4ba197d6ab77c31742d`; the rules files below were read in this clone) |
| Subjects | The nine queued: Southern groundfish by quarter, vermilion/sunset bag, no-retention species, sheephead boat dates, CCAs, Cordell Bank beside "eight GEAs", shore/spear exemption, abalone against MPA exceptions, salmon |
| Not covered | Other species, other regions' stoplight pages (only the Southern stoplight was read in full), Westlaw/eCFR full text, any live trip date |

Four separate clocks are in play and none is advanced here:

1. **Source-read date**: 2026-11-09 (this report).
2. **Agency page update date**: CDFW Southern stoplight 2026-11-02; CDFW groundfish summary 2026-06-23; NOAA GCA resource page 2026-06-23 (GEA CSV file `2026-06`, "updated 06-23-2026"); CDFW salmon sport PDF "Updated August 19"; CDFW in-season page, newest summary 2026-10-30.
3. **Registry review date** (`reviewed_at`): root `dist/data/regulations.json` (Central) 2026-09-25T08:09:03Z; Mendocino 2026-09-25T06:22:54Z; San Francisco 2026-09-25T13:10:13Z; Northern 2026-10-20T23:14:46Z; Southern `dist/regions/southern-california/regulations.json` 2026-09-24T21:30:56Z. Every one reads `rules_review_status: reviewed`, `valid_through: 2026-12-31`.
4. **Per-source check retrieval date** (`checks.<id>.data_retrieved_at`, compared with `approved_content_sha256`): not re-run. Because the registry predates the read by 20 to 46 days, any CDFW or NOAA page edited after those dates can differ from the approved hash without the app knowing until its daily check runs.

The app already carries a generic warning for that case: `web/regs.ts:133` shows "An official source changed after review. The saved limits below may have changed; check CDFW." when any dependent source check reads `changed`, and `web/regs.ts:75-82` / `:126-134` withhold "open" on missing, changed, unapproved or over-age checks (`docs/regulations.md:23,29`). That is a capability, not proof a check has changed: the committed root file lists only `access-vandenberg-maritime` (status `unavailable`) under `review_required`.

Vocabulary: **Result** is `agree`, `disagree` or `app silent`. **Confidence** is the read's, `confirmed` (full page read that day) or `uncertain` (gap, failed fetch, snippet only). They are independent. Where the read did not cover a region the row says so and is `uncertain`; that is not agreement.

## 2. Occurrence inventory (searched paths and terms)

Searched in the clone: `dist/data/regulations*.json` (5 jurisdiction registries), `dist/regions/*/regulations.json` (Southern only) and `dist/regions/*/regulations-startup.json` (16 startup forms), `jurisdictions/`, `regions/*/region.json` and generated `dist/regions/*/region.json` / `coverage.json`, `web/` (rules reader, rules card, map MPA layer), `scripts/collect_noaa_groundfish_areas.py`, `catalog/`, `docs/` (not `docs/archive`). Terms: vermilion, sunset, yelloweye, quillback, cowcod, bronzespotted, sheephead, CCA, Cowcod Conservation, GEA, "Groundfish Exclusion", eight, Cordell, abalone, spear, shore, diver, salmon, 50-fathom, nearshore.

Startup forms are byte-for-byte the same rule content as their full registry for rockfish, lingcod, sheephead (Southern) and salmon, checked by comparison of season, windows and details, with one exception: **the Southern startup form `dist/regions/southern-california/regulations-startup.json` has no `salmon` species at all** (the full Southern registry does, at `regulations.json:473`). This matters only for RC-09.

| Registry (jurisdiction) | Full file | Startup forms (`dist/regions/<id>/regulations-startup.json`) |
|---|---|---|
| Northern | `dist/data/regulations-northern.json` | crescent-city, humboldt-bay-cape-mendocino, trinidad-klamath |
| Mendocino | `dist/data/regulations-mendocino.json` | fort-bragg-point-arena, shelter-cove-north-mendocino |
| San Francisco | `dist/data/regulations-san-francisco.json` | bodega-point-reyes, point-arena-bodega, point-reyes-pigeon |
| Central | `dist/data/regulations.json` | big-sur-coast, cambria-san-simeon, monterey-point-sur, morro-bay, point-arguello-conception, santa-cruz-monterey-bay, south-big-sur-san-simeon |
| Southern | `dist/regions/southern-california/regulations.json` | southern-california |

Every reference to "all startup forms of X" below means every region id in that row. Real silence: no file in the search scope mentions the Cowcod Conservation Area as a recreational closure, and no rules text for shore or spear exemptions exists.

Official URLs used (all public):

- CDFW groundfish summary: https://wildlife.ca.gov/Fishing/Ocean/Regulations/Groundfish-Summary
- CDFW Southern stoplight: https://wildlife.ca.gov/Fishing/Ocean/Regulations/Fishing-Map/Southern
- CDFW salmon page: https://wildlife.ca.gov/Fishing/Ocean/Regulations/Salmon
- CDFW in-season changes: https://wildlife.ca.gov/Fishing/Ocean/Regulations/Inseason
- CDFW abalone page: https://wildlife.ca.gov/Conservation/Marine/Invertebrates/Abalone
- CDFW MPA rules (resolves to the Title 14 section 632 text): https://wildlife.ca.gov/CCR-T14-MPAs
- NOAA closed areas page: https://www.fisheries.noaa.gov/west-coast/sustainable-fisheries/west-coast-groundfish-closed-areas
- NOAA GCA maps and GIS resource: https://www.fisheries.noaa.gov/resource/map/groundfish-conservation-areas-maps-and-gis-data-west-coast-region
- NOAA GEA coordinate CSV: https://www.fisheries.noaa.gov/s3/2026-06/geas-updated-06-23-2026.csv

## 3. Comparison rows

Every row: read of the official source **2026-11-09**. "App location" gives file:line, or the JSON pointer for compact files and where the line is only the object's start.

### 3.1 Southern groundfish by quarter

Official (all rows): CDFW groundfish summary, updated 2026-06-23, https://wildlife.ca.gov/Fishing/Ocean/Regulations/Groundfish-Summary . Southern table: Jan 1 to Mar 31 closed all waters (both columns); Apr 1 to Jun 30 open all depths; Jul 1 to Sep 30 50-fathom inshore only (take prohibited seaward of the 50-fathom/300-foot RCA line); Oct 1 to Dec 31 nearshore RCG closed all waters, shelf/slope rockfish and lingcod open only seaward of the line. The summary says the line is waypoints in 50 CFR Part 660 Subpart C, not a bathymetry contour, and the content is subject to in-season change. Confidence: confirmed.

| Label | Scope | App text or value and location | Official statement | Result | Open question |
|---|---|---|---|---|---|
| RC-01a | Southern, Jan-Mar, rockfish and lingcod | `dist/regions/southern-california/regulations.json` `/species/rockfish/season` (line 393 object) and `/species/lingcod/season` (line 346 object): "Jan–Mar closed". `/windows` begin 2026-04-01, so Jan-Mar has no window. Same in the Southern startup form. | Closed all waters Jan 1 to Mar 31. | agree | none |
| RC-01b | Southern, Apr-Jun | Same pointers: "Apr–Jun all depths"; `/windows/0` 2026-04-01 to 2026-06-30, no restriction. | Open all depths. | agree | none |
| RC-01c | Southern, Jul-Sep | Same pointers: "shoreward of the legal 50-fathom RCA line"; `/windows/1` 2026-07-01 to 2026-09-30, `access: shoreward-50fm`, restriction "Only shoreward of the legal 50-fathom RCA line; exact position must be checked." | 50-fathom inshore only. | agree | none |
| RC-01d | Southern, Oct-Dec, shelf/slope rockfish and lingcod | Same pointers: "Oct–Dec offshore-only for lingcod and shelf/slope rockfish"; `/windows/2` 2026-10-01 to 2026-12-31, `access: seaward-50fm`. | Shelf/slope and lingcod open only seaward of the 50-fathom line. | agree | none |
| RC-01e | Southern, Oct-Dec, nearshore rockfish | Same pointers: "Nearshore rockfish closed Oct–Dec"; `/windows/2/restriction` "Nearshore rockfish closed." | Nearshore RCG closed all waters. | agree | none |
| RC-01f | Legal line against a sounder reading | `dist/regions/southern-california/regulations.json:1024` (`/common_notes/5`): "Seasonal groundfish access follows the legal 50-fathom RCA coordinate line, not a 300-ft reading on the sounder." `/windows/2/restriction`: "The 200-ft preset is not an access clearance." | The line is regulatory waypoints, not a bathymetric contour; NOAA says RCA lines "approximate particular depth contours" and can change in season. | agree | none |
| RC-01g | Other regions' seasons (Northern, Mendocino, San Francisco, Central) | Each full file `/species/rockfish/season` and `/species/lingcod/season`: "Apr 1–Dec 31, 2026 · boat fishing at all depths". Central `dist/data/regulations.json:295`; Mendocino `:483`; Northern `:476`; San Francisco `:612`. Windows 2026-04-01 to 2026-12-31. | Closed Jan 1 to Mar 31, open all depths Apr 1 to Dec 31 in those four areas. | agree | none |

The read recorded an in-season rule (10 days' news-release notice) that can change any of these after 2026-06-23; the read did not find a change on the in-season page (newest summary 2026-10-30 concerned crab). Result for this subject stays agree, at the confidence of the 2026-11-09 read.

### 3.2 Vermilion/sunset bag

Official: CDFW groundfish summary, bag limits, https://wildlife.ca.gov/Fishing/Ocean/Regulations/Groundfish-Summary (updated 2026-06-23). RCG complex 10 in combination, with copper 1, canary 2, vermilion/sunset **4 in the Northern area and 2 elsewhere**. Confidence: confirmed.

| Label | Scope | App text and location | Result | Open question |
|---|---|---|---|---|
| RC-02a | Northern | `dist/data/regulations-northern.json:488` (`/species/rockfish/details/0`): "at most 1 copper, 2 canary, and 4 vermilion/sunset rockfish combined." Startup forms: crescent-city, humboldt-bay-cape-mendocino, trinidad-klamath. | agree | none |
| RC-02b | Mendocino | `dist/data/regulations-mendocino.json:495`: "2 vermilion/sunset". Startup: fort-bragg-point-arena, shelter-cove-north-mendocino. | agree | none |
| RC-02c | San Francisco | `dist/data/regulations-san-francisco.json:624`: "2 vermilion/sunset". Startup: bodega-point-reyes, point-arena-bodega, point-reyes-pigeon. | agree | none |
| RC-02d | Central | `dist/data/regulations.json:307`: "2 vermilion/sunset". Startup: the seven Central ids in the table above. | agree | none |
| RC-02e | Southern | `dist/regions/southern-california/regulations.json:414` (`/species/rockfish/bag`) and `:417` (`/details/0`): "2 vermilion/sunset". Startup: southern-california. | agree | none |

### 3.3 No-retention species

Official: same summary: bronzespotted, cowcod, quillback and yelloweye rockfish, no retention at any time, all depths (14 CCR section 28.55). Confidence: confirmed.

| Label | Scope | App text and location | Result | Open question |
|---|---|---|---|---|
| RC-03a | Northern, Mendocino, Central, Southern (boat rod) | `/species/rockfish/details/1`: "No retention of yelloweye, quillback, cowcod or bronzespotted rockfish." Lines: Northern `:489`, Mendocino `:496`, Central `:308`, Southern `:418`. Startup forms identical. | agree | none |
| RC-03b | San Francisco | `dist/data/regulations-san-francisco.json:625`: "Do not retain bronzespotted, cowcod, quillback or yelloweye rockfish." Startup forms identical. | agree | none |
| RC-03c | Method scope (shore and spear take of these four) | No app text says whether the prohibition also covers shore or spear take. The registries describe boat rod-and-reel cards (see RC-07). | app silent | Official statement is that the four are excluded even from the diver and shore exemption (RC-07); no app text contradicts that. Custodian to decide whether a non-boat statement is wanted. |

### 3.4 Sheephead boat dates written as 2026 dates

Official: CDFW Southern stoplight, updated 2026-11-02, https://wildlife.ca.gov/Fishing/Ocean/Regulations/Fishing-Map/Southern . California sheephead: open year-round to divers and shore anglers; boat anglers March 1, 2026 through December 31, 2026; bag 2; minimum 12 inches total length. The boat dates are year-specific. Confidence: confirmed.

| Label | Scope | App text and location | Result | Open question |
|---|---|---|---|---|
| RC-04a | Southern, boat | `dist/regions/southern-california/regulations.json:619` object, `/species/sheephead/season`: "Boat rod-and-reel season March 1–December 31, 2026"; `/windows/0` 2026-03-01 to 2026-12-31 (explicit dated, not perpetual). Bag 2, size 12 in. Startup form identical. | agree | none |
| RC-04b | Southern, diver and shore | `:631` (`/details/0`): "Year-round diver/shore permission does not apply to rod fishing from the Parker." `/season` ends "Diver/shore exceptions are separate." | agree | The official wording defines divers as scuba or free divers with or without spear gear; the app says only "diver/shore". Left as is. |
| RC-04c | Southern, "closed January–February" | `/season`: "closed January–February." | app silent against the read | The read recorded the 2026 boat dates, not a stated January to February closure or a 2027 rule. Whether the wording is a 2026 statement or a perpetual one is not settled by the read. uncertain for this phrase. |

Windows end 2026-12-31 and registry `valid_through` is 2026-12-31, so the dates expire with the registry. After that, 2027 dates are not in the app (no statement is made here about what they should be).

### 3.5 CCAs not a recreational closure since 2024-01-01

Official: NOAA closed areas page, https://www.fisheries.noaa.gov/west-coast/sustainable-fisheries/west-coast-groundfish-closed-areas : as of January 1, 2024 CCA restrictions no longer apply to recreational and non-trawl groundfish; CCAs remain for trawl; the recreational function in the south is served by GEAs. The read says CDFW's Cowcod page says the same, but **that CDFW page's URL was not recorded in the read**, so only the NOAA citation is given here. Confidence: confirmed for the NOAA statement; the CDFW half is uncertain as a citation.

| Label | Scope | App text and location | Result | Open question |
|---|---|---|---|---|
| RC-05a | Data: CCA features | `dist/data/noaa-federal-areas.json`: 2 `CCA` features (layers `CCA_Eastern_20231201`, `CCA_Western_20231201`), each `groundfish_candidate_exclusion: false`, `exportable_as_fishing_spot: false`, retrieved 2026-09-23T22:56:33Z. The 10 `GEA` features carry `groundfish_candidate_exclusion: true`. | agree | none |
| RC-05b | Collector note | `scripts/collect_noaa_groundfish_areas.py:129`: "CCA and YRCA applicability depends on fishery, gear, date and location; no automatic fishing permission or prohibition is inferred." Same in `catalog/sources.json:443`. | agree | none |
| RC-05c | Map and registries | `web/map/habitat.ts:135`: only `Type === 'GEA'` is treated as the federal exclusion; no Southern registry text or `web/` file names the Cowcod Conservation Area as a closure (grep of the scope above). | app silent | The CCA geometry is stored but its effect on screening was only traced through the collector flag and `habitat.ts:135`, not through every consumer. uncertain on whether no other consumer uses the CCA layer. |
| RC-05d | Documentation | `docs/data-feed-readme.md:10`: lists Cowcod Conservation Areas among the GIS contents and says the 50 CFR text governs applicability; it does not call them a recreational closure. | agree | none |
| RC-05e | Not an app claim | `catalog/competitor-matrix.json:1093` records that a competitor lists the "Cowcod Conservation Area". | app silent (not an app statement) | none |

### 3.6 Cordell Bank (GEA of 2026-06-23) beside "eight GEAs"

Official: NOAA GCA resource page (last updated 2026-06-23) https://www.fisheries.noaa.gov/resource/map/groundfish-conservation-areas-maps-and-gis-data-west-coast-region and the GEA CSV https://www.fisheries.noaa.gov/s3/2026-06/geas-updated-06-23-2026.csv . The CDFW groundfish summary (https://wildlife.ca.gov/Fishing/Ocean/Regulations/Groundfish-Summary) and the NOAA resource page still say GEAs are **eight areas south of Point Conception**, while the NOAA table, the CSV and the MapServer layer `GEA_Cordell_Bank_20260623` include Cordell Bank. The CDFW summary also separately prohibits all groundfish fishing at Cordell Bank in the San Francisco area. The read records a name difference: CDFW's Cowcod page says "107/118 Bank", the NOAA CSV says "108/117 Bank" for the same first coordinate. Confidence: confirmed for each statement; the count mismatch is the read's finding, left unresolved.

| Label | Scope | App text and location | Result | Open question |
|---|---|---|---|---|
| RC-06a | Southern region, "eight" wording | `regions/southern-california/region.json:753` (`protected-areas.reason`): "NOAA’s eight Groundfish Exclusion Areas." Generated copies: `dist/regions/southern-california/region.json` and `dist/regions/southern-california/coverage.json` (compact, same sentence). | agree for "eight south of Point Conception"; open against the later Cordell addition | The word "eight" is scoped to the Southern region, where the data file `dist/regions/southern-california/groundfish-exclusions.geojson` holds exactly 8 polygons from the 2026-06-23 CSV (`source_url` and `source_sha256` `5ee1dd67…9260`). Whether "eight" should be read as a region count or as the stale total is the custodian's question; the read did not decide it. Result stays `agree` only for that regional reading. uncertain |
| RC-06b | Southern polygon name | `dist/regions/southern-california/groundfish-exclusions.geojson` feature name "108/117 Bank". | agree with NOAA CSV; differs from CDFW's "107/118 Bank" | Join on coordinates, not names. No change suggested. |
| RC-06c | Cordell Bank, San Francisco | `dist/data/regulations-san-francisco.json:592` (`/species/lingcod/details/3`), `:627` (`/species/rockfish/details/3`), `/area_notices/1` (line 818-819): "Cordell Bank groundfish fishing is prohibited"; notice says the exact boundary needs current federal rule review. Same text in `jurisdictions/california-san-francisco.json:140`, the three San Francisco startup forms and `jurisdictions/reviews/2026-09-2*` records. | agree | none |
| RC-06d | NOAA layers in the app's own data | `dist/data/noaa-federal-areas.json` includes `GEA_Cordell_Bank_20260623` and `GEA_Sur_Ridge_20251212` among 10 GEA features; `scripts/collect_noaa_groundfish_areas.py:73` refuses a run without Cordell. `dist/regions/southern-california/regulations.json:144` (`/sources/rules-gea/review_note`): "The RCA update referenced Cordell Bank outside Southern California." | agree | The read does not mention Sur Ridge; no comparison made. |
| RC-06e | Map basis wording | `web/map/mpa.ts:45` and `:289`: "NOAA Southern California groundfish exclusion areas, coordinates as published; the federal regulations control." | agree (scope is Southern) | none |
| RC-06f | San Francisco: is a Cordell polygon drawn | No `groundfish-exclusions.geojson` exists for a San Francisco region in the clone; whether the federal-areas file reaches the San Francisco map was not traced. | app silent | uncertain |

### 3.7 Shore and spear exemption from season and depth

Official: CDFW groundfish summary footnote 2, https://wildlife.ca.gov/Fishing/Ocean/Regulations/Groundfish-Summary (updated 2026-06-23): divers (spear fishermen entering from shore or boat) are exempt from RCG and other federal-groundfish **season and depth** limits, except no-retention species in section 28.55(b)(1); during a boat closure only spearfishing gear may be aboard; no vessel may assist shore-based take. The Southern stoplight (https://wildlife.ca.gov/Fishing/Ocean/Regulations/Fishing-Map/Southern, 2026-11-02) defines divers as scuba or free divers with or without spear gear, wider than the summary's wording. Confidence: confirmed for the footnote and the stoplight wording; the Title 14 section 28.90 detail (finfish a diver may take, 100 yards from stream mouths north of Ventura County) was a **search snippet only: uncertain**.

| Label | Scope | App text and location | Result | Open question |
|---|---|---|---|---|
| RC-07a | Groundfish cards are boat cards | Rockfish and lingcod `/species/*/methods/rod/note` in all five registries: "This profile is for recreational rod-and-reel fishing from a boat." San Francisco: "One line and at most two hooks when rockfish or lingcod are aboard." Central `dist/data/regulations.json:295` onward. | agree (no contradiction; scope is boat) | Boat-only cards are not wrong for omitting a shore/spear exemption. |
| RC-07b | Southern non-groundfish cards | Southern `:647`, `:679`, `:711` and ten further lines (e.g. `/species/whitefish/methods/rod/note`): "this is not a spearfishing or shore-access card." | agree | none |
| RC-07c | Shore and Spear profiles in the rules card | `web/app/RulesCard.tsx:25` picks the target's registry card from `PROFILE_TABLE[profile.value].defaultTarget`; `web/profile.ts:12` has Boat, Shore, Spear, Kayak. No separate rules text for Shore or Spear. | app silent | Whether the boat season/depth state is shown to a Shore or Spear user was not traced to its display. The official exemption is from season and depth only (not MPAs, not no-retention species, not the "spear gear only aboard" rule). uncertain. |
| RC-07d | Exceptions that are not exempted | Spearfishing salmon is prohibited (salmon only by angling, section 27.80 / 1.05; section 28.90 snippet): Southern lobster card `/species/lobster/details/0` mentions spears for lobster only. No app text on salmon by spear. | app silent | uncertain (section 28.90 snippet-only) |
| RC-07e | Diver wording | Southern `:631` "diver/shore"; official stoplight wording "scuba or free divers with or without spearfishing gear", summary wording "spear fishermen". | the two official wordings differ; app silent on which governs | Left unresolved. |

### 3.8 Abalone closed despite MPA exceptions

Official: CDFW Southern stoplight (2026-11-02): abalone closed year-round south of the mouth of San Francisco Bay, "no species of abalone may be taken at any time in Southern California". CDFW abalone page https://wildlife.ca.gov/Conservation/Marine/Invertebrates/Abalone : the recreational red abalone fishery closed in 2018, later extended; its FAQ heading says "closed until at least 2036" but the sentence locking that date was not in the extracted window. MPA rules page https://wildlife.ca.gov/CCR-T14-MPAs : Salt Point SMCA allows recreational take of abalone and finfish under section 632(b); that exception does not reopen a closed fishery. Confidence: closed fishery **confirmed**; the **exact end date is uncertain**.

| Label | Scope | App text and location | Result | Open question |
|---|---|---|---|---|
| RC-08a | Salt Point and Gerstle Cove | `dist/data/regulations-san-francisco.json:565` (`/sources/mpa-salt-gerstle/review_note`): "Salt Point SMCA permits recreational finfish and abalone subject to fishery closure. Both polygons remain excluded." Same in `jurisdictions/reviews/2026-09-25-california-san-francisco-point-arena-bodega.json:160`. | agree | none |
| RC-08b | Whole-MPA exclusion | `dist/regions/southern-california/regulations.json` `/sources/rules-mpa/review_note`: "App exclusion of all mapped MPAs is conservative and does not assert that every SMCA is legally no-take." `web/map/habitat.ts:285`: "withholds fishing targets in all mapped protected areas, including conservation areas that allow some activities." | agree | none (conservative exclusion kept; not a legal no-take assertion) |
| RC-08c | Abalone fishery status | No registry species card for abalone in any of the five registries; the word appears only in the Salt Point note above. | app silent | The app states no abalone season, open or closed. |
| RC-08d | Closure end date | No app text states a closure end date. | app silent | uncertain (the "2036" date is not confirmed) |

### 3.9 Salmon page against the 2026-11-02 Southern stoplight

Official, two CDFW pages read 2026-11-09 that the read found in conflict: the salmon page https://wildlife.ca.gov/Fishing/Ocean/Regulations/Salmon (sport PDF "Updated August 19") still lists a fall season: 38°02′ N to Pigeon Point, September 1 to October 31; Pigeon Point to the Mexico border, September 1 to 30. The Southern stoplight (updated 2026-11-02) says ocean salmon is **closed for the rest of the year**, with 2027 dates "beginning in April, 2027". The in-season page https://wildlife.ca.gov/Fishing/Ocean/Regulations/Inseason records August 2026 federal in-season salmon actions (including a San Francisco recreational closure moved to August 24, 2026). No winner is chosen here. September and October windows have passed as of 2026-11-09, so the app's text and a November closure can both be true; the conflict is the agency's own. The salmon page and the stoplight cover different regions; the stoplight read is Southern only. Confidence: the contradiction is **confirmed** as between those two pages; whether either governs a given region is **uncertain**.

| Label | Scope | App text and location | Result | Open question |
|---|---|---|---|---|
| RC-09a | Central (Pigeon Point to Point Conception), startup forms of Central | `dist/data/regulations.json:359` (`/species/salmon/season`): "2026 fall season: Sep 1–30, Pigeon Point to the U.S.–Mexico border, unless closed early."; `/windows` 2026-09-01 to 2026-09-30; details: "can close before Sep 30. Check CDFW immediately before the trip." | agree with the salmon page; not compared with a Central stoplight (the read did not open it) | uncertain. Whether Central should now read closed is not answered. The window has ended, so no open state is derived after 2026-09-30. |
| RC-09b | Southern | `dist/regions/southern-california/regulations.json:473` (`/species/salmon/season`): same wording and window. **The Southern startup form has no `salmon` species.** | agree with the salmon page; the stoplight's "closed for the rest of the year" is not stated in the app | The app's Southern salmon text describes only the September season; the stoplight states a closure for the remainder of 2026. No claim is made that the app shows salmon open on 2026-11-09 (window ended 2026-09-30). The custodian must decide whether the Sept 1-30 copy should be reviewed against the stoplight. uncertain which page wins. |
| RC-09c | San Francisco | `dist/data/regulations-san-francisco.json:682` (`/species/salmon/season`): "Sep 1–Oct 31, 2026 only from 38°02′ N near Point Reyes south to Pigeon Point; may close earlier at the 20,000-Chinook harvest guideline." `/windows/0` 2026-09-01 to 2026-10-31 with latitude band. | agree with the salmon page | The in-season August San Francisco closure date change was not compared with `details/1` ("In-season action can close the fishery before Oct 31"). uncertain |
| RC-09d | Mendocino and Northern | Mendocino `:553` and Northern `:545`: "Ocean salmon is closed in the … Management Area for the remainder of 2026." `windows: []`. | no comparison: the read did not cover the Fort Bragg or Klamath pages | uncertain; this is not agreement. |
| RC-09e | Salmon not by spear | No app text. | app silent | see RC-07d |

## 4. Custodian handoff

Rows that need a human look. Each lists the exact place; nothing here is a patch, replacement wording or approval, and nothing is approved automatically.

| Row | Exact app location | Why it is open |
|---|---|---|
| RC-09b | `dist/regions/southern-california/regulations.json:473` and `/species/salmon/windows`; Southern startup form lacks `salmon` | The Southern stoplight (2026-11-02) says closed for the rest of the year; the app carries the September copy and the startup form omits the species. |
| RC-09a, RC-09c | `dist/data/regulations.json:359`; `dist/data/regulations-san-francisco.json:682` and `/species/salmon/details/1` | The read compared only the Southern stoplight; Central and San Francisco stoplight pages and the in-season August actions were not compared with the app. |
| RC-09d | `dist/data/regulations-mendocino.json:553`; `dist/data/regulations-northern.json:545` | Not covered by the read. |
| RC-06a | `regions/southern-california/region.json:753` and the two generated `dist/regions/southern-california/` copies | "eight" is accurate for the Southern region but stale as a count against the 2026-06-23 NOAA table, which includes Cordell Bank. |
| RC-06f | San Francisco map data; `dist/data/noaa-federal-areas.json` | Not traced: whether the Cordell polygon reaches any map. |
| RC-05c | `web/map/habitat.ts:135`; `dist/data/noaa-federal-areas.json` (2 CCA features) | Consumers of the CCA layer were traced only through the collector flag and `habitat.ts`. The CDFW Cowcod page URL is not on file. |
| RC-04c | `dist/regions/southern-california/regulations.json` `/species/sheephead/season` ("closed January–February") | Not stated in the read; the 2026 boat dates themselves agree. |
| RC-07c, RC-07d, RC-07e | `web/app/RulesCard.tsx:25`; `web/profile.ts:12` | Shore and Spear profiles use boat cards; the diver wording and the section 28.90 details are snippet-level or differ between pages. |
| RC-08d | none in the app | The abalone closure end date ("2036") is unconfirmed. |
| Header clock | all `reviewed_at` values in section 1 | Registries were reviewed 2026-09-24 to 2026-10-20; sources dated after that (stoplight 2026-11-02, in-season 2026-10-30, salmon PDF August 19) have not been put through a reviewed check. |

Rows that agree (RC-01a to RC-01g, RC-02a to RC-02e, RC-03a, RC-03b, RC-04a, RC-04b, RC-05a, RC-05b, RC-05d, RC-06b to RC-06e, RC-07a, RC-07b, RC-08a, RC-08b) need no action from this check. They are agreement at the confidence of the 2026-11-09 read, not a review approval.
