# Changelog

## Unreleased

- SC1407-07: the Aerial base asks USGS for 512 px tiles (about a quarter of the requests for the same view, at the same sharpness and over the same zoom range) as JPEG where a tile is fully opaque and PNG where it holds transparency, so open water still shows the map below; if that format fails, the base retries once in the previous PNG-only form. The map page also opens its connection to the USGS imagery host while it loads. The imagery, its dated credit and the NaturalColor rendering are unchanged.

- RF0854-8: the admin fleet operator list ranks every matching operator (do-not-contact last, then lead score, then name, then id) before applying its 500-row cap, so a high-scoring operator outside the first 500 by name is no longer left out. Matching operators are read in bounded pages by id with every filter applied to each page; `truncated` still means more than 500 matched, and the endpoint, filters, response fields and score model are unchanged.

- RF0844-8: fleet trip labels (admin form and agent label import) refuse a start or end time written on a day that is not on the calendar, such as February 30, 2026-02-29 or April 31, with the existing "must be ISO UTC times" error, instead of silently rolling it into the next month and saving it against the trip; a refused admin label saves nothing and a refused agent import keeps every existing label. Valid days, leap days and accepted time precision are unchanged.

- RF0844-7: the GEFS wind-ensemble build now checks each decoded wind-component and gust field's latitude and longitude axes against the GFS land mask before sampling any sea-cell index, and fails the build when a field sits on displaced cells even if its dimensions match (it previously published that wind under the mask's coordinates with a false zero-distance receipt). A failed build keeps the previous generation as before; matching grids, receipts and missing-member handling are unchanged.

- RF0834-9: the forecast build keeps missing or nonfinite accumulated precipitation (ECMWF IFS) missing through its conversion to mm/hour instead of publishing dry zeros. An absent, bitmap-missing, rejected-sentinel or infinite first accumulation is no longer stored as 0 mm/h, and an interval whose start or end accumulation is not finite (including either infinity) is stored as missing rather than as no rain; only intervals that depend on the bad value are affected. Valid initial zeros, finite decreases (clamped to zero) and uneven step intervals are unchanged. No forecast data is rebuilt or republished by this change.

- RF0814-8: a depth-contour file whose review expiry is an impossible calendar date (such as 2026-11-31 or 2027-02-29) now fails the existing contour check instead of drawing and exporting; real dates keep drawing through their last day and are withheld the next day.

- RF0834-6: the USCG PSIX registry adapter no longer builds an official number by deleting the non-digits from a workbook value. Only a value that is already 5 to 8 plain digits becomes the document-number key and fact; anything else (letters, signs, decimals, exponent forms) leaves that one key out so it cannot attach facts to the wrong vessel, while the name, call sign and other facts are kept.

- RF0844-6: SST front extraction preserves native grid origins and coordinates, so half-offset grids no longer falsely conflict; true overlapping-measurement conflicts still refuse publication.

- RF0814-9: the admin fleet map's Activity type filter now also narrows the returned track segments, so a mixed-mode trip no longer draws fishing modes that were not selected; trip eligibility, paging, events and heat are unchanged.

- RF0834-5: the AIS matcher keeps an established watched row (and its entry in the listener's `watch.json`) when the processor has no statics for an MMSI the same single active registry vessel still holds, whether positions remain or the processor state was rebuilt. Retention needs the stored row's vessel to be that owner, no rejection and a row that passes the watched gate; no row, fact or review is invented, and an unheard, candidate, rejected, reassigned, duplicated or excluded binding gains nothing.

- RF0854-9: AIS validation sync refuses a malformed or non-progressing labels response (wrong region, missing trips or next, a non-object or badly-identified trip, an out-of-order, repeated, backward or skipping cursor) with a one-line error naming only the page number, before anything is written. The last labels snapshot, the raw-position copies (which may be the only positions left after retention) and earlier reports are kept; a valid, complete, empty response still removes unlabelled copies.

- RF0814-7: the trip planner's GPX, offline notes and planning-route exports now refuse, with "Included launch ramp is unavailable", when the included launch ramp is no longer in the published list (list replaced, empty, unavailable or for another region) instead of silently exporting the first listed ramp or leaving the checked launch out. The ramp checkbox stays visible, checked and enabled (showing "—") so it can be unchecked; a valid current ramp choice is still followed exactly and nothing saved is changed.

- RF0804-7: the trip planner's position check forgets its reading when the region changes while the dialog is open, and a slow answer for the old region no longer appears in the new one; closing or leaving the dialog also drops a pending answer. Nothing new is read, sent or stored (`web/app/PositionCheck.tsx`).

- RF0824-5: saved trip plans enforce the 16,384-byte plan cap in UTF-8 bytes on create and edit, so names and notes in non-ASCII text can no longer slip a larger plan past the limit; over-cap plans are refused with "plan too large" and nothing is saved.

- RF0844-9: the advisor rules editor refuses a species label or source name that is empty once control characters are removed (it was saved as an active, reviewed rule with blank text); a refused create or edit changes no rule and does not bump the pages version. Visible text with embedded controls is still accepted, cleaned as before.

- RF0854-5: the WCOFS surface-current reader refuses a forecast frame whose latitude, longitude, mask, U or V array does not hold exactly the requested grid's cell count, or whose time array is not one value, even when every array is equally short, long or empty. The source reports failed (or retained, keeping the prior data and its original clocks) instead of ok or missing; a complete all-dry grid still reports missing.

- RF0854-6: regular-grid GRIB decoding preserves longitude/value identity for westward-scanned columns, normalizing coordinates and columns together; positive-i grids and latitude handling are unchanged.

- Forecast build: wave directions resampled onto the reference grid are now interpolated as circular bearings, so 359° and 1° average to north instead of south (180°). Non-finite or out-of-range source bearings and exactly opposite bearings stay missing; scalar fields, the sea mask and already-aligned grids are unchanged (`src/skippercast/forecast/build.py`).

- RF0804-8: the "Check my position" answer no longer reads "outside" for a closure inside a wide reported position accuracy. When the position accuracy plus the 70 m planning margin reaches the planner screen's 20 km search bound, the nearest held closure is measured again without that bound, so a closure within the accuracy radius is "near" (with the low-accuracy warning) instead of being skipped. A precise position far from every closure, inside-a-closure, missing-layer, stale-data and not-covered answers are unchanged. Nothing is sent or stored. NOT FOR NAVIGATION.

- RF0824-7: CDIP nearshore ingestion refuses changed or malformed numeric quality-flag mappings, retaining only eligible recent last-good records with their original clocks; canonical quality masks remain unchanged.

- SCFEAT-BATHY2M-EXPAND-1: private Del Norte bathymetry test page uses the retained NOAA F00562 1 m survey with medium relief, survey dates and nominal MLLW provenance. No public tiles, hard-bottom inference or navigation-qualified depths.

- SC-TIDAL-1: the Boat brief at the four regulated bars (Morro Bay, Humboldt Bay, Noyo River, Crescent City) gains an entrance current line, labelled an estimate: flooding, ebbing or near slack now, when it turns (slack shown as a 30-minute window either side of each predicted high or low), the day's turns, and a bar caution that puts the swell forecast on the ebb. It uses only the NOAA tide predictions and the NOAA WCOFS surface forecast the app already loads; WCOFS is a second opinion offshore of the entrance, so when it runs out of the entrance while the tide says flood or slack the hour is read as an ebb. The caution is read at the tide phase of the instant itself (with the hour's wind against the ebb), near slack it is also read as an ebb, and a WCOFS forecast that is old or missing at Morro Bay reads as a possible ebb rather than as no hazard, so an aging source never makes the caution calmer. Old or missing tide or swell data reads unknown and never calmer (a hazardous reading stays hazardous in words, beside the stale warning), and the line says it is not for navigation. Humboldt, Noyo and Crescent City show tide timing only: their entrances have no vetted seaward bearing, so WCOFS is shown but not compared. No data file, feed or caching header changes (`packages/coast/src/entrance-current.ts`, `web/brief/entrance-current.ts`, `web/brief/EntranceCurrent.tsx`).

- SC-GPSOFFLINE-1: the trip planner has a "Check my position" button. Only when tapped it reads the device position once with the browser's location feature (no tracking, no background use, no notifications) and says "You are inside / near / outside <area name>" with the distance to the nearest closure and the position accuracy, using the planner's own protected-area check and the boundary files the offline legal pack saved, so it works with no signal. It says plainly when no legal files are saved, when the position is unavailable, denied or low accuracy, and that official CDFW rules govern. The position is never sent or stored. NOT FOR NAVIGATION.

- SCFEAT-LEGALPACK-1: the trip planner now links directly to the offline save dialog. Each saved region has a cache-checked legal checklist with included/missing files, saved and source dates, rule effective windows, official source links and stale/unknown-date warnings (the protected-area boundary file's own source check date is shown and warns when old, unknown or in the future, however recently the file was saved). Presence is not legal clearance; NOT FOR NAVIGATION.

- MAPLIVE-1: the real app map has a "Private previews" group in its Layers rail with one switch each for seafloor medium relief (with 2 m shallow bathymetry), wind particle trails, HF-radar surface currents, sea-surface temperature and chlorophyll. It appears only for the owner/admin session (`/api/session` `is_admin`), every layer is off at start, and each layer's code and private `var/` data file are requested only when its switch turns on (nothing at first paint). Each shows the data's own time and is withheld past its age limit; a missing file reads unavailable. The legend gets a row per layer that is on. Tile output stays private and nothing changes for visitors. Tide (PR 1755) is not included yet: it merged into the unmerged MAPSTYLE-2 branch, not main. TODO: add each layer's update-cadence line once SCFEAT-FRESH-1 (PR 1759) lands.

- SCFEAT-CATCH-1: selected map marks with a visible position offer one-tap catch or blank (no catch) entries in a separate private device log. Entries keep the selected position, capture time and already-loaded model conditions with sources, clocks and explicit gaps. Nothing is uploaded or added to an account; clearing browser site data loses the log. No live GPS, species/count inference or export. NOT FOR NAVIGATION.

- SCFEAT-ROUTE-1: the trip planner can download a separate GPX route through 2–12 selected stops, avoiding current protected-area polygons and their 70 m planning margin on the existing shoreline water screen. The route carries boundary-check time, sources and NOT FOR NAVIGATION warnings; a missing route is withheld, never replaced by a straight line. No live position or passage clearance.

- MAPSTYLE-1: `scripts/build_bathy_tiles.py` turns the 10 m Morro Bay survey raster into styled "Deep" seafloor base tiles (cmocean deep colours, nonlinear depth stretch, four-direction hillshade) as a local PMTiles archive, zooms 8-13, with no-survey cells fully transparent; `research/scripts/map_style/bathy-deep-test.html` shows it as the base layer of a MapLibre test page. Nothing in the app map changes and the archive is not committed.

- SC1352-08: the shore-run, ranked trip-spot and shoreline-segment cards read Spanish where they are shown: the status and every Blocked and Hold reason, the review clocks (in the region's zone), the guidance with its "fish presence is unverified" and check-current-rules statements, the ranked spot's habitat, evidence-confidence and rules lines, and the shoreline accuracy lines. Area, run, alert and source names stay as published; the status, priority, access pins and counters still decide on the English values, and English output is unchanged.

- SC1352-06: the map's Chart / 2D / 3D toggle, its group labels, the terrain zoom, reset and top-view buttons, the waypoint prompt and refusal, the terrain-unavailable reasons and the private saved-spots row and cards read Spanish. The saved-spot card keeps its "not a recommendation" and "check current rules" statements and its protected-area wording, a person's own spot names stay as typed, and no card shows the private note in either language; the English text is unchanged.

- SC1352-05: the map's buoy and tide-station cards, the Stations layer note and the nearshore model rings' card, basis and summary read Spanish. Heights use a decimal comma, times show a date and clock in the region's zone, and the fresh, stale and last-good states, the region-default and chosen tide-station labels, and the 90-minute, 48-hour and 3-hour model caveats are all kept; station and site names, ids, datum names and provider notes stay as published, and the English text and stale decisions are unchanged.

- SC1352-04: the Protected areas row and a clicked area's card read Spanish. The loading, map-unavailable, partial, incomplete, failed-load, failed-completeness-check and wrong-region lines keep every "an area without an outline may still be protected" and failed-check statement, and a designation shows a Spanish label with the official English designation beside it; area names, legal citations and the CDFW rules link are unchanged, and the English text, status and Try again decisions are unchanged.

- AISLIVE-01: the fleet-ais run summary gains a counts-only "AIS coverage by port" block (`python -m skippercast.fleet.ais port-coverage`): per region port the distinct MMSIs and MMSI-days heard in the last 30 days, and the ports never heard; it reads the processor state read-only and prints no MMSI or position.
- Landing Spanish keeps custom boat names literal even when named “your boat” or “your 19 ft boat”. Its first-paint catalogue slice shares the app's language runtime; readings load after mount so the original install budget stays unchanged.
- RF1600-6: a non-finite optional number (inf, -inf, Infinity or 1e999 in heading, status, length, width, IMO or vessel type) in a MarineCadastre AIS CSV row is now treated as unavailable, like NaN, instead of aborting the whole day; the row's other fields and the following rows are still read.
- RF1600-5: the aisstream AIS normaliser no longer emits a position whose latitude or longitude is NaN or infinite, and reads a NaN or infinite speed, course or heading as not available while keeping the otherwise valid fix; ordinary values, unavailable markers and static records are unchanged.

- SC0452-10: Where to look and the Boat run line read Spanish. The list's heading, its by-water and straight-line distances, the protected-area screen lines (not checked, inside, metres from), the range and dive controls and the search-plan labels, and the run line's speed and window prompts, fishing-time sentences, method note and the entrance's leave-by and be-back-by line come from `catalog/app/strings.json`, and both files join the copy lint's covered list. Place, harbor and closure names are shown as published, rule wording stays the registry's English and is marked as such, a sentence the catalogue does not know is shown as it came, and the English text, ranking and run arithmetic are unchanged.

- SC0452-11: seven caveats the copy lint used to excuse now read plainly and keep every limit they carried (the regulation-page check and harbor clearance, charter ground positions and depths, commercial AIS coverage, tuna habitat, the dated charter report, adult-Chinook temperatures, and the offline trip notes' date label); their seven `consecutive-not` entries are gone from `scripts/copy-lint-baseline.json`, which keeps only the five `method-name` entries for published model, survey and datum labels. No other copy, data or behaviour changes.

- SC0237-03: the trip-alert form for the Boat profile starts from your own Boat limits when you have saved them in Your limits (wind, gust and sea, kept to the ranges the server accepts), and its note says so; they are your absolute settings, so the boat's wind and sea factors are not applied to them again, while alerts still judge wind chop for a saved custom boat. Without your own Boat limits the form and its notes are unchanged, still scaled by the boat; the other profiles are unchanged.

- Deleting a saved trip, or the 90-day clean-up of old trips, now clears the trip from your private catch-log entries instead of leaving them (and the privacy export) naming a trip that no longer exists; the entries and their other fields are kept (#1549).

- Search discovery now lists the Coverage and Forecast skill pages at the addresses the site serves (/coverage and /skill), and the Coverage page's canonical address is /coverage, not /coverage.html (#1550).

- Reports view: reopening it reads its sections again when one failed last time or the loaded data is 30 minutes old or more, so a dropped read or a tab left open for a day no longer pins “unavailable” or old evidence; what is shown stays until the new read arrives (#1544).

- SC0237-04: the trip planner refuses what the Chart and the GPX check refuse. Saving a waypoint from a Chart tap and Add to trip on a habitat or survey place now decline a place that is not checked, inside a protected area or within the 70 m planning margin of one, with the same one-line reason ("Not saved: 40 m from …"), and add nothing; a place already in the plan is checked again each time it is added. A clear place is added as before, and adding it twice still adds it once.

- The Kayak launch list is asked for again after its response body fails in transit; only a malformed file stays remembered as the answer (#1540).

- The Text Advisor now holds a Comfortable day at Bumpy, and says why, when some listed hours have no forecast or the marine alert check is incomplete, as the brief holds those days at Marginal; days that were already Bumpy, Rough or Unknown read as before, and an advisory still makes a day Rough (#1547).

- Saved-trip alert updates now name long-period swell (2.5 ft or more at 15 s or longer, from the same wave model, point and hour), which used to read “within limits”: the alert carries a hazard note, says surge and entrance conditions need a separate check, and sends an update when the note appears, changes or clears; limits and status are unchanged (#1545).

- BF-og-cards: shared map links carry the landing preview image and name a known region and its listed port in Open Graph previews; no forecast or date enters the preview, and the app remains noindex.

- Tide predictions with an impossible date or hour (such as Feb 30 or 24:00) are now ignored instead of being rolled into the next day, where they hid the real row and could let an unusable answer load or qualify an offline pack (#1534).

- A signed-in planner offers your private saved spots as stops (“Your saved spots”): Add to plan copies a spot's name and position into the plan in this browser as an ordinary waypoint. A spot that is inside, within 70 m of or not checked against a protected area shows its reading and cannot be added, and a spot's note is never copied into the plan, a trip, a link or an export (#1541).

- The selected-hour Conditions value and the hourly table's tide cell now use the nearest eligible reading when there is none at the exact time, instead of the first listed one, so they no longer depend on the feed's order; an exact reading still wins (#1542).

- The GPX check reads each waypoint and track point's own coordinates only: a look-alike such as data-lat, x:lat, LAT or coordinate text inside another attribute no longer counts, and a duplicated, missing or unreadable lat or lon fails the file as before (#1537).

- Boat lookup sources: a link longer than 500 characters is skipped instead of being cut short into a different address; links that are kept are stored unchanged (#1530).

- The private catch log's form offers your own saved trips as an optional Trip choice (stored date and area), and the list shows the chosen trip's saved date (#1526).

- BF-spanish-app: the map app reads Spanish. The first answer, the brief's labels and the rules card come from one string catalogue (`catalog/app/strings.json`, English and Spanish, read by `web/i18n.ts`); the language is the visitor's own choice (`?lang=es`, remembered on the device), else the browser's Accept-Language, else English, and the page `lang` follows it. Rule wording from the reviewed registry stays English and the card says so; regulation numbers, species, port and source names are never translated. `scripts/check_copy.mjs` now fails on a catalogue id with no Spanish value, an unknown id and a bare literal in a covered file.

- The Text Advisor now holds a Comfortable boat day at Bumpy, and names the hour, when the Morro Bay harbour-bar estimate reads hazardous in the window, as the brief holds it at Marginal (#1533).

- Kayak's Where to look now measures distance and range by water from the chosen launch where a water route is computed; otherwise the straight line stays, labelled, with a short reason. Boat, Shore and Spear are unchanged, and Kayak still shows no run time (#1509).

- Save for offline now also stores a region's published land-water and depth-contour files, when the region lists them, so offline Where to look, ranked marks and planner spots can tell land from water and the Boat run can use its water route (#1524).

- A saved spot outside the area the loaded protected-area file covers now reads “not checked” and is held back from the GPX, instead of reading clear (#1525).

- The Trip dialog shows, for each saved pack, a Water temp line and a Currents line saying what its ocean record holds; older packs show no line (#1523).

- The privacy page now says that private catch-log entries and saved spots are kept until you delete them and are included in the data export and in account deletion (#1521).

- The first answer on the desktop app is styled with the app's own colours and spacing instead of showing as bare rows (#1515).

- The Text Advisor no longer reads a forecast hour after a model's published end as a value: such an hour is unknown, as in the app, so it cannot make a day read Comfortable (#1522).

- Shore selections on the Chart show their access, rules and source review times in the loaded region's own time zone; a missing or other region's zone keeps the default (#1518).

- Save for offline now runs an ocean step: for Morro Bay and Cambria, whose water readings come from the coastal report, it records only that report's saved time and saves no extra files; for other regions it saves the water-temperature and current layers whole or not at all, and the pack records what was saved or failed and until when it can be drawn (#1508).

- The Text Advisor now calls a day Rough, and names the advisory, when the daily feed lists a boating advisory (small craft, gale, hazardous seas and the like) that overlaps the fishing window, as the brief does; the measured numbers are unchanged (#1496).

- The Boat run line now names and times the place that Where to look lists, so it can no longer name a pick the list dropped for a water route beyond your range (#1504).

- SC2207-04: the trip planner's Best available applies its maximum one-way distance from the selected port to the water route where one is computed (as Where to look does), so a reef 13 nm round a headland no longer fits a 10 nm plan; a reef without a route keeps its straight line, labelled, and each ranked spot says which. Habitat order, the 0.15 nm separation, the protected-area screen, saved plans, exports and the stops-in-order legs are unchanged.

- Search-plan source links now show: each reviewed source on a plan is listed on the Plan page and in the brief's search-plan block (https links only, opening in a new tab); before, no plan showed a source (#1501).

- Forecast skill is served at /skill (the /skill.html address still works), and the status page links to it (#1506).

- Chart placement now screens your tap: with a waypoint placement armed, a tap that is not checked, inside a protected area or within the 70 m planning margin of one is refused with the reason (“Protected areas not checked”, “Inside …”, “40 m from …”), the placement stays armed, and an unchecked tap is no longer accepted. Trip-plan legs now say when their line is inside or near a protected area, or not checked (#1497).

- SC1952-04: the landing's tomorrow verdict for a returning visitor rates with the boat and Boat comfort limits saved on this device (the same two stored values /map rates with) and names that boat in its heading, with the model note for a boat outside the reference range; with no boat saved, or one that cannot be read, it is still the reference 23 ft boat. It reads only those two stored values, stores nothing and sends neither in any request.

- Season strip: a month with more than one open run now lists them (“Part open: 1–15, 20–25”, or “Part open: 1–5, 10–12 and 1 more”), where it used to name only the first run and read as if the season shut on the 15th (#1488).

- The Text Advisor holds a Comfortable day at Bumpy when a rated hour in the window has long-period swell (2.5 ft at 15 s or longer), and names the earliest such hour, as the brief does; it used to say comfortable (#1494).

- The phone's rules line starts the registry read and the daily rules read together instead of one after the other, so it can appear after one round-trip; the rule state shown is unchanged (#1480).

- The boat name in the brief's “Comfort rating for …” line is shown cleaned: invisible and control characters are dropped, spaces collapsed and the name cut at 40 characters on a whole character; the stored boat is untouched (#1491).

- The desktop app now leads with one answer line above the map: whether tomorrow is fishable for your profile, one reason sentence, the rules state (reviewed, due for review or unavailable) with the official link, and a control that scrolls to the map and the measured detail. On a phone the map and sheet peek still lead (#1456).

- A Temp fronts map layer (off until you turn it on) draws offshore temperature fronts as lines with a width for their uncertainty, says each front's age in words, and shows nothing once the data passes the feed's age limit (at most 72 hours); a missing file reads “no current front data” (#1472).

- Private saved spots: signed in, you can save a place with an optional private note, see your list, remove a spot and download your spots as GPX. A spot inside or within the 70 m planning margin of a protected area is shown with the boundary's name and left out of the file; a missing or old (over 36 h) screen exports nothing, and the note is never put in the GPX. Spots are private to the account, included in the data export and account deletion, and shown on no public page, feed or preview (#1482).

- The map's rules line reads a small per-region copy of the regulations at startup instead of the whole multi-region file (about 25 KB less on first load for Morro Bay); the full file and the daily part are still used when the copy is missing or not valid, and the rule state shown is unchanged (#1476).

- Where to look's by-water distance for the Boat brief is now smoothed along straight water-only shortcuts, so a route is no longer overstated by up to about 8 %; it stays at or above the straight line and never crosses land (#1477).

- Printed seas maxima now round up, so a printed maximum is never below the value the window rule used (a window the 4 ft limit rejected can no longer read “seas to 4 ft”); the advisor's ranges follow the same rule (#1474).

- A public /skill page shows each active port's forecast skill, built from the port's own verification record; a port without enough verified days, runs or valid times is not scored (#1470).

- Protected-area screening now covers every output: each Where to look pick, trip leg, ranked area, waypoint save, Chart placement and GPX export reads one shared verdict (inside, within the 70 m margin, or not checked) and refuses or says so; a screen that is missing or not current counts as not checked, never clear (#1461).

- A private catch log in the signed-in account sheet: record a catch, a blank (no catch, stored with a count of 0) or an unknown outcome with optional time, method, species, count, position and note; list and delete your entries. A position needs both latitude and longitude inside the poles and the antimeridian. Entries are visible only to you, are not scored, shared or put in a feed, and are in the data export (/my-data also serves signed-in accounts) and account deletion (#1458).

- Selecting a ranked area now shows up to three short, dated reasons for it, each naming its source; ranking, scores and sources are unchanged (#1460).

- Trip planner rows no longer repeat “90% confidence” when every ranked place has the same confidence: it is said once above the list (“All ranked places: N% evidence confidence.”) and rows read “#1 · Strong” (#1467).

- BF-advisor-beta: the region/language pilot switches now reach the deployed Worker. Contacts outside the pilot can still opt out, confirm data deletion and request their data; only those control replies bypass the pilot scope.

- The brief's tide sparkline says “No tide curve for this place. The times below are the day’s predicted highs and lows.” when only the highs and lows are listed, instead of “Tide series unavailable” beside a tide height (#1468).

- The Boat brief says when to leave and be back at the harbour entrance: the longest stretch of daylight hours the bar estimate does not call hazardous (at least one hour, earlier on ties), with caution hours named; with no such stretch it says so, and it gives no times when the tide or swell drivers or the entrance bearing are missing. It is not clearance to cross (#1457).

- Comfort ratings with some data missing never read calmer than the full rating on the same values: a limited hour now charges the chop, crossing and short-chop it does carry, so 1.5 ft at 5 s chop no longer rates as the cap (#1465).

- GPX waypoint names are cleaned before being made unique: control and other XML-forbidden characters are removed, names trimmed, an empty name becomes “Waypoint”, and duplicate names still get a suffix (#1453).

- Changing a saved trip whose area is no longer offered now answers that the area is no longer offered and the plan cannot be changed (save a new trip), instead of a generic retryable-looking error (#1455).

- A GPX export refused for a protected area now names it (“Inside or within 70 m of <name> …”) instead of a bare refusal (#1440).

- The Conditions hourly table rates each hour for your saved boat, as the brief does, instead of the reference boat (#1449).

- Boat picks in Where to look show distance and run time by water (“x nm by water”) where a water route is computed, otherwise a labelled straight line with a “run ≥” lower bound; your range to consider is judged on the same distance (#1444).

- The landing shows the saved-copies notice when live data is paused, and prefixes its verdict “From saved copies, not live:”; otherwise it is unchanged (#1438).

- The status page gives the coast-feed sources (ocean, nearshore, water quality and history) their own freshness rows, with the same age limits the Worker applies (#1443).

- First-use setup asks the profile first and the boat details after it, on the landing and in the map's card, instead of the boat questions above the four choices (#1448).

- Each rules card now says in words when the daily source check last confirmed the row (“Checked today”, “Checked Sep 20”, “Check date unknown” or “Check overdue - open the official page”), beside the official link (#1441).

- The trip plan's legs use the water route where one is computed (labelled by water) and otherwise the labelled straight line with the reason; run minutes and totals follow the chosen distance (#1445).

- Trip check: an unreadable marine-alert entry fails closed, treated as an advisory with unknown timing, so the trip stays unverified instead of the check breaking (#1435).

- Trip alerts: a day-before assessment left pending (a failed send still retrying) is now retried on the trip date or reported as missed, instead of the trip going silent (#1434).

- The brief's day verdict, worst-hour score, limit sentence and Comfortable/Marginal/Rough word are rated for your saved boat, and the basis names it; with no saved boat nothing changes (#1429).

- Text Advisor rules replies now name a half-listed season (“opens Apr 1; closing date not listed”) instead of reading as unrestricted (#1431).

- For a target the picker labels “search plan only”, Where to look shows that target's search plan instead of an empty reef list (#1430).

- The brief reads the smaller /api/daily brief part first and the whole daily feed only as a fallback, and the offline pack saves that part (#1424).

- Text Advisor rules replies show real calendar days only: dates such as Feb 31, Apr 31 or 2026-02-29 are no longer printed as if they existed (#1428).

- The first-use “How do you fish?” step asks boat length (8–70 ft) and comfort limits once, saved on this device only; a blank or invalid length saves nothing and the hint says “Boat length 8-70 ft” (#1427).

- The Boat brief's run time, turn-back and fishing time use the water route from where the distances run to the chosen place (“x nm by water”); with no route the straight line stays, labelled with the reason (#1408).

- Addresses with a trailing dot on the host (https://skippercast.com./…) redirect once to the bare host (#1403).

- Share links carry the target and each view setting only when the address has it once, in plain form; anything else is left out of the link (#1396).

- SC-POPOVER: the desktop map legend's basis popovers (Seafloor, Currents, Depth contours, Protected areas) are placed against their own button by CSS anchor positioning, so the legend that now shrinks and scrolls no longer cuts off the part of a popover beyond its box; a browser without anchor positioning keeps the previous in-flow popover.

- On the landing, choosing another port cancels the first port's region warm-up, so it stops fetching that region's files (#1417).

- The layer rail has five one-tap presets (Reef drift, Halibut, Crab, Offshore, Transit), the one for the current target's family first, and a Helm view switch that makes every control at least 48 px, raises the base text size one step and hides rail notes and legend detail; the switch is kept on this device, not in the link (#1388).

- Every fishable place the app shows can go to the chartplotter, not only rocky reefs: a picked survey place saves its own point as a waypoint (reef for hard or mixed bottom, other otherwise), cards that cannot be exported say why, and the GPX file is checked and screened at export (#1389).

- A capped Text Advisor reply never ends in half an emoji (#1372).

- Text Advisor rules for an unknown species link the general regulations card instead of a species page that does not exist (#1375).

- The brief no longer breaks on a tide event with no readable time: such events are left out instead of throwing an error in the tide sparkline and Conditions (#1376).

- A signed-in “This weekend” preview above saved trips shows this Saturday and Sunday's enabled trips in plain text, ordered by start hour; unknown spots read “a saved spot”. Nothing is emailed or pushed (#1377).

- Interactive controls across the app views meet the 24 px minimum target size (fleet rail checkboxes, the brand link, brief footer links, the plan's official-rules link and panel text links), checked by a new accessibility test over the app views (#1384).

- A public /coverage page draws every published region on one California coast strip, active or preview, each linking to its map, with the same facts as a list (#1391).

- Share links keep the terrain grade filter (?grade=) (#1360).

- Tide trend reads no trend from a height that is not a number, or from a next point that is unreadable or not after the matched one, instead of a false “Falling” (#1369).

- Shore runs may now be on rocky shore, named as rocky with their own guidance; sand shore guidance is unchanged (#1359).

- Tide station names in the chooser are cleaned (blank, multi-line or over 80 characters falls back to the station id) and a duplicated prediction row is skipped (#1350).

- Saving a tide pack checks every prediction answer before storing any; a damaged one stops it with “Chosen tide predictions are unavailable. Saved regions are unchanged.” (#1337).

- A stale forecast can no longer wear a calmer label: past 18 hours a day's calmer word becomes unknown, in the brief and in the Text Advisor (#1334).

- A layer-rail toggle the current view cannot draw (“Chart only”) stays reachable by keyboard and reads its reason, instead of dropping out of the tab order (#1245).

- Saved trips are split into Upcoming (soonest first, including today) and Past (newest first, by Pacific date); each past trip opens to its final assessment (or missed-final, or a fixed no-assessment sentence) and the same day's private comfort reports. Forecast records are not observed sea conditions (#1287).

- Trip planner: selected stops are listed in order with leg and total distances and at-least run minutes from the home port, with notes for a missing port, skipped invalid coordinates and what is not modelled (sea state, bar, fuel, per-stop conditions); straight-line only, no export change (#1286).

- Target plan page (?view=plan): the selected target's reviewed search plan, with its methods, confirmation and evidence, review date and dock-day rules; numeric-model plans are withheld, unresearched coverage is explained, and Conditions and the legend link to it and follow the selector (#1276).

- Protected-area screening is one check with a 70 m planning margin at every output (map reef marks and the ?spot= card, Where to look, GPX and notes export, charter grounds): whole boundaries and shapes are screened, not only points, and the margin is measured in metres (#1268).

- The map app counts one anonymous map_viewed event per region per page load (at most ten regions) in the existing usage statistics; nothing under Do Not Track or Global Privacy Control, no identifier or cookie, and the privacy notice says so (#1285).

- Live data degrades instead of billing: past a daily R2-read ceiling the Worker answers from saved copies (kept 7 days) or free fallbacks, with a notice “Live data is paused for today to keep SkipperCast free; some readings are saved copies”; private routes also have per-address and per-account rate limits (#1267).

- Landing: a failed port list now offers Try again beside “Explore the coast” (#1271).

- Conditions shows the target's season across the current year as a twelve-month strip under “Before you go”, from the reviewed registry windows only (open, limits, closed, opener unconfirmed, location needed, part open, not reviewed), with the registry revision, the official link and a not-legal-advice note (#1275).

- At fishing zoom the Chart ramps the survey habitat fill, outlines the reef footprint and shows a screened mark's valid nearby depth band beside it; pick targets, card wording and screening are unchanged (#1274).

- Marks: when a region's file fails to load, the protected-area check now reads unavailable (“Protected-area check unavailable · fishing spots withheld”) instead of leaving spots showing (#1273).

- Desktop mark card: Add to trip, GPX / Review & export and Regulations stay visible at the bottom of the card while it scrolls (#1247).

- The export sheet shows “Planning aid · not a navigation chart.” and “You are responsible for your boat, crew and decisions at sea.” before Download GPX (#1269).

- Fishing time: set the hours you want (kept on this device, no default) and the Boat brief compares the run remainder with them, the legal opening and daylight; a closed target shows the registry reason and official link, and unchecked rules cannot yield enough (#1260).

- The brief footer says “Planning aid · not a navigation chart.” with a Terms link, and the landing carries the same line (#1270).

- Closing the mark card (Clear selection or Escape) returns focus to the map you are looking at in 2D, 3D or after a Chart failure, never to the page body (#1238).

- A Share this view control beside the port control builds one link to the port, day and profile (and hour, target, view, layers, base, presentation, current, habitat or spot when set), and hands it to the share sheet, copies it or shows it to copy (#1265).

- A panel that fails to render now fails alone: the rest of the desktop or phone shell stays, with a status message and a Retry for that panel (#1254).

- The landing leads with tomorrow's verdict from the brief (#1252).

- Saved-trip alerts cover the planned departure and return hours of a same-day plan, not only the fishing hours, and append the clock time when that leg exceeds your wind, gust, sea or boat-scaled chop limit; a malformed or overnight plan keeps the original window (#1259).

- Trip alerts start from the active Kayak, Shore or Spear profile's saved limits (or that mode's defaults), clamped to supported ranges, and say alerts assess offshore seas, not launch or beach surf (#1256).

- Conditions says in words when the two models disagree about wind or seas on the next days' mornings (a gap of 6 kt or 2 ft in at least two hours), without changing any score (#1250).

- Conditions has one hourly table below the chart, a row for every local hour of the dock's day: time, wind, gust, seas, swell, chop, tide, visibility and comfort score (#1251).

- The brief lead shows model agreement beside the comfort score as measured wind and seas gaps, never as an input to the score; missing or stale models cannot give a reassuring line, and differing hours show both readings in Details (#1249).

- Clouds frames are no longer re-requested about every four minutes while the layer is on, since each frame is pinned to one time and never changes (#1248).

- The brief's daily and live buoy feeds refresh when you return to the page, as the forecast does (#1246).

- Protected areas: after a failed boundary load, the layer offers Try again instead of saying unavailable until the page is reloaded (#1229).

- The brief measures distances from the planner's home port rather than always from the region's harbor (#1241).

- A mistyped or stale region link now says there is no region by that name and links the port list, instead of “Region details unavailable. Retry” (#1224).

- On the Chart, access pins of a Hold shore run draw muted like the run (#1244).

- Your limits and cruise speed follow a change made in another tab of the same browser (#1239).

- Shared reads: a response whose body fails mid-transfer is not kept, so the next request fetches again (#1240).

- The brief's Where to look admits places through the same protected-area screen as the trip planner (#1242).

- Your limits form names a gust limit below the wind limit in one plain line (“Your gust limit is below your wind limit, so gusts decide every window.”); values are saved as typed (#1237).

- The brief holds a Comfortable day at Marginal when a window hour has long-period swell (2.5 ft at 15 s or longer), and names the hour (#1230).

- The trip planner opens with the best places chosen and today's date, instead of an empty plan whose date moved a week out (#1232).

- The phone's bottom bar is Coast, Conditions, History and Reports: Fleet comes off the bar for now; the desktop masthead, ?view=fleet and the charter-grounds layer are unchanged (#1225).

- The brief's “Where to look” reef list for lingcod, rockfish and “all” now ranks the same seafloor reef publication as the trip planner, so a reef shows the planner's depth band instead of a different one from the older terrain release; the list reads “Loading ranked reef places…” while it loads, an expired or unavailable publication falls back to the previous list, and clicking a reef row moves the Chart to the place instead of opening a mark card. Gopher rockfish and shallow-reef cabezon keep the labelled atlas list (#1219).

- Ranked reef waypoints in a GPX export get a short plotter name such as “01 Reef 200-278ft” and a one-line description (a habitat estimate, not a sounding or catch forecast; check rules, closures and your chart) in place of the long method text, which stays on the website and the offline notes; other waypoints and tracks export as before (#1222).

- Bar and shore readings treat a tide, sunrise or sunset time written without a time-zone offset as unknown, instead of reading it in the device's own time zone, so the same report no longer gives a different ebb or flood, tide phase or twilight on a phone in another zone (#1227).

- The coast report keeps a marine alert whose event name is missing or unreadable (shown as “NWS alert (type not given)”) instead of dropping it, so such an alert still shows “Marine alert in effect” and hides windows (#1228).

- On a phone, opening the History view raises the bottom sheet to full height so the recorded series is in view without dragging; you can still drag it down, and other views and desktop are unchanged (#1220).

- Habitat cards from the brief's recommended places now work with the trip: Add to trip saves the place into the plan (adding the same place again adds nothing), GPX saves it and opens the plan, and Regulations links the official CDFW page, instead of three disabled buttons (#1221).

- On a mark card, a rules line that is not confirmed for your fishing date now reads “Not confirmed for your fishing date - open the official rules before you go.” instead of “Needs recheck · last check <date>”; the last-check date no longer shows on that line (#1223).

- With no time chosen, the brief's lead answers for tomorrow and names its day (for example “Marginal tomorrow, 7 am–noon”); an hour chosen in the dock, or a link's day, still wins. The lead also says whether the selected target is legal that day, from the reviewed rules with their official link (#1214).

- New public /status page: for each data source, its last successful publish, its expected interval and whether it is inside it, read in your browser from the published feeds; sources the freshness check does not watch yet are listed as not watched rather than given a state (#1212).

- The brief's verdict names the limit that actually cost the score (the charge the model took, not a raw ranking of comfort costs), and marks provisional forecast days with “Provisional” on the verdict line, in the basis popover and on the Wind and Swell tiles (#1216).

- The rules card also links the species' own CDFW page when the reviewed registry lists one, and treats a source check as stale after the registry's maximum age for it (never more than 36 hours) instead of a fixed 36 hours (#1210).

- Charter-grounds, commercial AIS and shore layers: a read that dropped (network error, timeout, HTTP 429 or a server error) is asked again when you turn the layer back on, instead of staying failed for the visit; a 404 or an invalid file is still not re-requested (#1203).

- After a dropped read of the rules files, the next mark card asks for the rules again instead of saying “Check rules” for the rest of the session; a clean read is not repeated (#1197).

- Bar and shore readings treat a wave or swell period that is zero, negative or not a number as missing: it no longer appears in a reason line, counts as the long-period swell, or changes a band (#1205).

- A dropped read of the Kayak launch list or of Spear's distance from shore is asked again on the next request instead of hiding it for the whole visit; a 404 or an invalid file is still remembered (#1201).

- Depth contours: after a dropped read the Chart asks again on a later camera move, at most once a minute, instead of showing “Depth contours did not load” for the whole visit; a 404 or an unlisted file is not retried (#1202).

- Saved trips: the limit of 20 active trips now holds when several saves arrive at once; the extra ones get the same “Limit of 20 active trips” answer (#1198).

- The trip alerts form's default date is tomorrow by calendar day in the region's time zone, including on the nights the clocks change (before, it could be today or two days ahead) (#1199).

- Trip planner: a failed port-list read is asked again on the next Best available click and a note says when it could not be read (ranking then has no distance limit), and depth-contour tracks that failed to load are asked again when you turn them on (#1206).

- Bar check: a crossing window with no reading at departure or at return now shows the existing “bar caution or unknown at departure or return” reason instead of passing silently (#1195).

- Shore tide phase ignores malformed tide events and curve points, and reads unknown when the same time is listed as both high and low, instead of guessing a rising or falling tide (#1196).

- Saved trips: the seven-day booking window and “tomorrow” are counted by calendar day in the region's time zone, so around a clock change a valid trip is no longer refused (or one day too many accepted) and a next-day trip is still treated as day-before (#1189).

- Trip alerts: on the days the clocks change, a saved window counts the real local hours, so it is no longer always reported as not fully populated and unverified (#1187).

- The trip alerts form says in plain words, before saving, when the date is outside today to seven days ahead, the window ends at or before it starts, or the gust limit is below the wind limit; its date picker offers only that range (#1186).

- The privacy export now lists your notification devices: the push service host and the date each was added, never the full address or keys (#1177).

- The forecast data requests (/api/om) apply the per-address rate limit only to answers not already cached, so people on shared connections (phone carrier, club Wi-Fi) are no longer limited for cached answers (#1176).

- Trip alert notifications that fail with HTTP 429 or a server error are sent again on later checks, at most three tries in all; other failures are final and not resent (#1175).

- Cambria's forecast lattice grows from 2 × 2 to a 3 × 3 grid of offshore points with one corner left out (it fails the water rule), so the Swell field covers more of the Cambria shelf (#1172).

- Tapping a trip-alert notification opens the saved-trip alerts dialog on the map (the account panel when no port is in view) instead of landing on a page with no alert in view (#1169).

- The trip alerts dialog names a saved trip's area and species, and an alert's kind and status, in plain words instead of internal ids (#1170).

- Trip alerts: a marine advisory whose time cannot be read is treated as applicable, so the trip stays unverified, instead of the advisory being silently dropped (#1173).

- Trip alerts raise “Missed day-before assessment” only when the trip was saved before its date and its day-before assessment did not go out; a same-day trip, or one whose day-before assessment was delivered, no longer gets a false one (#1174).

- Cambria and San Simeon now have a NOAA coastline and a land-water index in their Chart files, so the Chart can draw that coast and tell land from water; where NOAA served no tile, a point is treated as unknown, never as certified water (#1162).

- The Text Advisor now names target species it did not recognise (and asks what you meant) while still saving the ones it did, instead of silently dropping them (#1164).

- In the map's Terrain 2D and 3D views, the Seafloor entry's Terrain options now say why there are no reefs (the habitat status sentence), list the ranked reefs (up to 12) so you can select one, and add an “Explore a ranked reef” button (#1165).

- Trip alerts' reads of National Weather Service alerts now identify SkipperCast (a User-Agent) and ask for geo+json, so an NWS refusal for lacking one no longer turns trips into “Marine advisories unavailable” (#1166).

- Morro Bay's forecast lattice gains two water-only shoreward points (longitude −121.00, at latitudes 35.05 and 35.30), so the Swell field draws the complete cell toward Estero Bay (#1158).

- Text Advisor display names are cleaned in one place: invisible and direction-control characters are removed, and the 60-character cut never splits a character such as an emoji (#1151).

- The Text Advisor's trip list says how many more verified boats the port page has when a port has more than the 12 it lists (#1152).

- The Text Advisor no longer moves a report date that carries an explicit year back a year: 12/30/2026 typed in January is now outside the correction window instead of being saved as 2025-12-30; dates typed without a year roll back as before (#1142).

- The Text Advisor refuses impossible calendar days such as 2026-02-30 as a trip date or a week start, instead of reading them as 2 March (#1144).

- The Text Advisor recognises Spanish from an upper-case or decomposed Ñ (for example “MAÑANA PESCA”), not only a lower-case ñ (#1138).

- Text Advisor uploads: an empty file input is skipped, so an upload with no real file answers “no file in the upload” (400) instead of a zero-byte “file type not supported” (415) (#1139).

- RF0905-1: on a phone (below 1024 px) the Chart opens with the region centre (the Morro Bay harbor) in the open band between the top card and the sheet, not under the top card; the padding follows a resize, not a sheet drag. `?view=` and desktop are unchanged.

- RF0935-1: Spear's distance from shore and the trip export's depth contour tracks no longer request a shoreline overview or contour file the loaded region's `chart_files` lacks; no distance is claimed and no contour tracks are added, as for a missing file (Cambria: fewer 404s). Without the list they ask as before.

- RF0935-2: the web client's fallback time zone (`America/Los_Angeles`) is defined once in `web/zone.ts` and imported wherever a default is needed; nothing renders differently.

- RF0850-2: the Chart no longer requests a shoreline or depth-contour file the loaded `region.json` does not list: with neither shoreline listed the coastline draws nothing and reads unavailable, and unlisted contours settle as none (Cambria: no shoreline or contour 404s). It waits for the region's `region.json` before asking, so switching to such a region requests neither. Listed or unknown, it asks as before.

- RF1058-2: the fleet AIS health answer and its `fleet-ais-stale` issue name the likely cause of a stale check (`processor-not-delivered` when all three clocks are equally old, else `listener-stale`, `no-messages` or `no-data`), so a dropped processor schedule no longer reads as a dead listener. Thresholds are unchanged.
- The region-build golden case is now a checked script: `golden_compare.py` compares a run's candidate with the committed depth-contour file in features and provenance, so a provenance-only difference is caught at build instead of at publish (Morro Bay SG-1).

- RF0850-7: the landing night map draws its basemap and currents without a coastline when a region's `region.json` lists neither shoreline file (Cambria: no shoreline 404, no torn-down map), and the full shoreline when only that is listed. Without the list it draws as before.

- RF0850-1: once a region's `region.json` has loaded, the app no longer requests a land-water index, poster or shoreline form its `chart_files` lacks, and the offline pack no longer counts them as missing (Cambria: fewer 404s). Without the list it asks as before.

- RF0835-2: each compiled `region.json` lists the Chart side files the build wrote for it (`chart_files`), and the landing warm-up no longer requests a shoreline overview or poster a region does not publish (Cambria: two fewer 404s). Without the list it warms as before.

- The `noaa-bag` source (NOAA hydrographic survey grids) is now approved in the source catalog as a source family, on G's 2026-10-30 acceptance. Individual tiles still need their own screening and review, datums are carried as declared, and nothing is published or for navigation by this change.

- The target picker says what the region has for each target beside its name: ranked by mapped habitat, search plan only, or not researched in this region. Targets the region names as unresearched are listed but cannot be selected.
- The mark card shows the forecast for a reef mark or ranked trip spot at the selected hour. NOAA and ECMWF wind and seas each get their own row, labelled with model and grid spacing. The forecast feed only has those at a few named points, so the card says so and shows the regional point's values, naming the point. The NOAA WCOFS surface current comes from the sampled ocean cell nearest the mark, with that cell's distance, when one is within 1.5 grid lengths.
- SP61-SPEAR-DAYLIGHT: Withhold the daily spear best hour, surge range and clarity estimate when known daylight has no fully covered forecast hour. Nighttime readings remain available per hour; unknown sunrise or sunset keeps the existing all-hour fallback.

- Add an opt-in local coast terrain-RGB / contour-MVT preview with synthetic fixtures, a persistent not-for-navigation banner and manifest-derived source rights. The public coast route is unchanged; measured-source integration and publication remain held.
- SP-MAP-NOW: Withhold cloud tiles and native current frames when an explicitly supplied decision clock is not a valid Date. Omitted clocks still use the current time; source ages, forecast and observation selection, publisher hosts and tile queries are unchanged.

- Save up to three NOAA tide prediction stations per region in this browser and switch between them; existing choices migrate, the region default is unchanged, and offline packs still include only the active station.
- SP-BAR-EVENTS: The harbour bar tide estimate ignores malformed event rows and stays unknown when either selected tide timestamp has conflicting high/low tags. Ordinary ebb/flood timing, bar hazard rules and the Coast Guard check reminder are unchanged; this is not clearance to cross.

- SP-RULES-STATUS: The rules line on a mark card no longer says "Verified" when the rules state is "Check rules" or "Choose fishing location". That covers a trip date outside the reviewed rule period, a review time later than allowed, and a season that applies only within a geographic area, even when every source check is fresh. These now read "Needs recheck · last check <date>". Seasons, limits, source checks and their wording are unchanged. A verified date only records when the sources were checked; it is not clearance to fish.

- The Swell layer's selector switches between the primary swell, wind sea and secondary swell from the NOAA GFS-Wave wcoast.0p16 forecast, each drawn with height in feet, period and direction and named with its run time; the nearshore (CDIP MOP) rings are unchanged.
- Chlorophyll feed limitations identify the current NOAA merged VIIRS product and its native grid spacing instead of the historical MODIS description; cloud gaps and freshness limits are unchanged.
- Place a named waypoint on the Chart with a reef, wreck, bait, hazard or other category; save it in the browser’s region draft and export the category in GPX. User labels do not qualify habitat or depth, and current protected-area checks still apply.
- The Chart's Stations layer shows configured buoy and tide stations, with provider links and timestamped readings labelled stale when old; bound CDIP MOP model sites are available without enabling the Swell field.
- The Chart draws Morro Bay's shelf depth contours at every zoom: a line every 30 ft (heavier and labelled every 150 ft) to 480 ft, traced from the reviewed USGS/CSUMB 2 m survey grids (2008). A dashed survey edge marks where the reviewed grid stops; past it, a missing line means no reviewed data, not shallow water. Each line opens a card with its survey, date and vertical datum; the datum is unverified (the grids declare none), so these are not chart depths and not for navigation. The NOAA chart base is unchanged.
- Trinidad–Klamath is a browse preview with reviewed Northern ocean rules, not qualified fishing spots or launch clearance. Reading Rock MPAs remain excluded, Klamath salmon remains closed and the November crab opener is unconfirmed. Northern California-halibut guidance now correctly prohibits on-boat filleting and landing fillets north of Point Arena.
- Choose a NOAA tide prediction station within the region, or the nearest listed station to the port. The browser remembers each region's choice and offline chart packs include its predictions; bar and shore assessments keep their reviewed reference station.
- Ranked places (Where to look, the trip planner's Best available and its pins on the Chart) are now checked against the NOAA shoreline: only places confirmed on water are ranked. A place on land, within 25 m of the shoreline, or outside the shoreline's coverage is withheld, and the basis counts it ("N spots withheld: land/water not confirmed"). Regions without a shoreline rank no places until one is imported. This is a planning screen, not a navigation boundary.
- Coastal discovery keeps plain `.nc` file links from THREDDS listings (HTTPServer only, never OPeNDAP or subset services), and the bridge-lane acquire and qualify stages read a local netCDF grid such as a NOAA CRM subset. Geographic grids are held at the map stage instead of being resampled.
- Temp contrast, a new map layer that is off by default: it shows the change in sea-surface temperature per nautical mile in the region's published daily analysis. It draws only cells whose change exceeds the summed analysis error and is withheld past 72 hours (CI6-03).
- Offline packs now remind you to check before leaving coverage and explain missing water-temperature and current data instead of leaving the layer blank without an offline reason.
- Replay a short, skippable controls tour from the account menu on desktop or phone: time dock, layers, offline saving and evidence limits. Profile setup and the first-visit Chart flyover are unchanged.
- Choose decimal degrees, degrees and decimal minutes, or degrees minutes seconds in the account menu for mark positions, trip plans and downloaded notes. GPX coordinates remain decimal degrees.
- Deploys no longer stall while merges land faster than CI. Each deploy ships the newest `main` commit whose Offline checks passed, even when newer merges are still being checked. It never ships a commit with failed or pending checks, nor one older than the commit production already serves, and it holds when the commit production serves cannot be traced. A run that ships nothing reports "held", with the reason, through a neutral **Cloudflare deploy** check run and the job summary, instead of a plain success.
- Add an optional surface chlorophyll map layer with native observed cells, a logarithmic mg/m³ legend and the feed's strict sample-age limit; cloud gaps stay empty.
- The Chart's Swell + wind control adds NOAA GFS wind arrows and knot labels at the selected forecast hour, with grid, run and age in the basis; stale wind is withheld independently of swell.
- The deploy gate now traces Worker versions Cloudflare labels `version_upload` (what `wrangler deploy` 4.142.0 records) as code uploads, alongside `upload`, so an automatic deploy is no longer held when production serves the workflow's own deploy.
- Trip plans name protected-area boundaries containing selected spots and link the agency rules; blocked plans can download context-only notes while GPX remains withheld.
- The Chart can open a surveyed coverage cell's basis and credits; year and vertical datum stay explicit when they are not recorded.
- The Text Advisor upload, my-data and admin pages use the app's dark visual system instead of the retired v1 palette.
- The admin labelling view draws a trip's track map and speed strip again, each kind in a colour from the app's visual system.
- The species research and commercial AIS pages use the app's visual system, like the sources page. Their text is unchanged, except the species research page's chart paragraph, which now names the NOAA chart layer groups the map requests.
- The terms, privacy and licences pages use the app's visual system, like the sources page, with the draft notice kept prominent.
- The Seafloor legend summarises its surveys ("4 surveys, 2006–2010") instead of listing raw source file names; every survey is still listed in its basis.
- After a brief nautical-chart (ENC) tile failure the Chart drops its "chart detail unavailable" note as soon as a fresh chart tile loads for the same region, instead of keeping it until the page is reloaded. Other layer failures stay reported.
- While a ranked trip plan's numbered pins show on the Chart, the legend keys them and links their basis.
- Shore runs on the Chart go on Hold, with the reason on the card, while a marine alert covers the area, the marine alert check is not current, or the county posts a beach-health advisory, closure or warning there.
- A seafloor mark's basis links its source publisher's terms page again, as the classic map did.
- The admin fleet activity status line counts one stop, trip or heat cell in the singular ("1 stop").
- The admin fleet trip detail fits a phone screen without widening the page; its label and segment tables' hidden headers stay inside their scroll area.
- The licences page and NOTICE name the MapLibre GL JS version the app ships (6.14.0), and a check keeps them in step with future updates.
- "Where to look" distances always run from the region's harbor, never from your device's location; where a region has no published harbor position, each place shows a dash and the basis says no distance is shown.

- The first Chart view of a visit now takes a slow look around: over about 20 seconds the map tilts and turns toward the region's harbor, then settles back north up and flat exactly where it started, so the link and the shared camera are unchanged. Any touch, click, scroll or key stops it at once and returns the map north up. It runs once per browser session, only on the region's opening view (never for a link to a view, spot or habitat), and never when your device asks for reduced motion or to save data. Gestures still cannot tilt or rotate the Chart. The desktop 3D orbit is planned separately (#646).
### Coastal readiness inspection

- Add coastal queue status and imported-code identity commands with explicit hold, attempt, dependency and schema receipts. Document the separate installed, native, science and operational readiness gates with synthetic unit coverage.

- Refine report and advisor contrast surfaces while preserving fail-closed contrast checks through the CI adoption test.

- Guard region details and target plans across delayed reads and retries; reserve terrain controls and let desktop layer explanations scroll within the rail.

- Explain why a selected current grid cannot be drawn in the layer rail, while retaining source and time labels for supported frames.

- Refresh conditional coastal jobs when the CDIP, beach-health or GOES collector adapters change.

- Preserve Fish enrichment failure provenance and use configured coastal feed context for readable reports and RSS, retaining reviewed fallback and privacy behavior.

- Apply one-second pacing to default National Weather Service coast-report requests while preserving injected sessions and other provider limits.

- Use target-specific atlas explanations only for supported lingcod and rockfish screens; keep neutral terrain descriptions for other admitted targets. Add terrain-type and age-formatting regression coverage.

- Check static client dependencies for terrain libraries; add offline regression fixtures for unavailable coastal-source rights and the historical regulations wrapper.

- Remove the retired offline-pack card adapter while retaining saved-pack storage and the current trip interface.
- Remove the unused legacy boat-button bootstrap while preserving the account menu's exact-boat sheet.
- Verify saved shore-source receipts against their selected region and recognize only the reviewed nowCOAST satellite endpoint in commercial-source checks.

- Link charter-trip summaries to their existing published fishing-report sources.

- Recheck Fleet access when the signed-in session changes, including while an earlier check is pending.
- Keep the nearshore rings explanation visible when the swell field is unavailable.

- Withhold terrain waypoints when the current protected-area or closure screen is unavailable or rejects them; clarify that Chart reef density limits do not apply to reviewed terrain.

- Use the daily-selected water observation in the brief, share overlapping Fleet directory probes without caching settled results, and format charter research dates consistently in the legend.

- Collect Chart rendered-feature counts only when diagnostics are explicitly enabled.

- Reuse settled session state across account-menu remounts while explicit refreshes still fetch the session.
- Preserve exact `#account` intent through port and home URL resolution.

- Show “age unavailable (future timestamp)” for cloud acquisitions ahead of the clock, retaining their acquisition time and existing past-age formatting.

- Carry the existing local-calendar provisional flag through the brief model, independently of confidence wording.

- Keep a selected swell card open when only the other swell source refreshes; still clear it when its own data changes or disappears.

- Validate the nearshore sample label’s site prefix before removing it; add regression coverage for sampling time/cadence and legacy home-profile and port URL behavior.

- Restore each fishing profile’s chosen Currents source when switching profiles, including observed HFR and explicit Off choices.

- Stop forwarding the retired `ui` switch from home-page navigation links; legacy links continue to open the same pages.

- Add the private California schedule-evidence collector and opt-in timer installer, preserving source revisions and distinguishing incomplete AIS reception coverage from readable empty windows. Source integration does not activate collection or change the existing AIS listener (#599, #624).

- Add the current coastal source-discovery, mapping and 3D-rendering skills, with bounded source preparation and separate private terrain, habitat and publication acceptance. Keep the older coastal rendering name as a compatibility entry point.
- Show the protected-area legend swatch only when boundary geometry is drawn, retaining warnings and official rules links while it is unavailable.

- Reject impossible aerial acquisition dates and future coverage-check dates when validating regional configuration.

- Keep first-run profile choices inside the mobile sheet so small-screen visitors can reach every choice and the sheet handle.
- Disable Play and Next hour at the forecast horizon's end while keeping earlier hours selectable.

- Keep the mobile sheet at its previous height when a drag is cancelled, and preserve the next tap.

- Search engines and link previews can read the site again. The home page has a canonical address, the share card (title, description and boat image) that went missing with the classic map, and WebSite structured data so Google can show the SkipperCast name; its title and description now say it is for fishing on the Central Coast. `robots.txt` and a new `sitemap.xml` list the public pages, and `/sources` and `/privacy` name their canonical addresses.
- A first visit to the home page is now one guided path: pick where you launch, then how you fish (Boat, Shore, Spear or Kayak, each with what it changes), then the map opens. While you pick the profile, the home page fetches that region's map files and forecast in the background, so the map opens on cached or revalidated copies; only the chosen region is fetched, nothing when your browser asks to save data, and "Change port" goes back a step. The port is saved as home once you choose the profile. The profile choices no longer sit beside the port search, and the map no longer asks "How do you fish?" after the home page did; links straight into the map, and returning visitors with a saved home, skip the guided path as before (#622).
- Move fleet AIS half-hour scheduling to off-hour slots and record trigger, run kind and source revision for cadence verification.

- Forecast queries reuse each model/tile within the request and share timezone formatting across points, preserving values, units and duplicate-model field names while reducing repeated storage reads and computation.

- Production deploys require current main and successful Offline checks for the exact selected commit. Eligibility is checked before checkout, dependencies and production writes; obsolete automatic CI results are held, while explicit Worker rollback remains available.

- Feed publication commits one verified immutable R2 snapshot so failed uploads cannot mix old manifests with new forecast tiles. Forecast queries pin one release; existing URLs and prior data remain available through migration.

- The layer rail has a terrain grade filter beside the base, All, A and B, or A only, kept in the link as `?grade=`; on a phone the Layers panel also opens with the target species ("Look for", the same list as the command bar). The filter narrows the reef marks and the seafloor candidates together; unranked search areas show only with All, and the seafloor note counts what the grade left out. Zoomed out below view zoom 10, where the water used to be empty, the target's reef marks now draw as a soft density weighted by terrain grade and habitat fit, labelled "<Target> habitat candidates, denser here", which fades into the individual marks as you zoom in. It is drawn only around surveyed marks that passed the protected-area check, is withheld with them when that check is stale, and is off for Shore. A grade ranks search priority from surveys, not catch (#620).
- The brief now leads with a one-word day verdict for the morning, Comfortable, Marginal or Rough, and one sentence naming what limits it, for example "Marginal · 7 am–noon. 20 kt wind gusting 26 at 10 am." For Boat it is the existing comfort score for the reference 23 ft boat (the same one the Tomorrow card and the advisor use), worst hour from sunrise to noon; Shore, Spear and Kayak use their own hourly grade. It is a comfort rating, not a bite forecast or a safety clearance. A marine alert makes the day Rough; partial forecast detail, an old model run, a missing alert check or a hazardous bar estimate hold it at Marginal and say why; no forecast reads Unknown. The summary, the readings line, what is missing and the caveat fold under Details, which shows how many sources are missing or stale. On a computer the brief column is 300 px instead of 332 px with the four tiles on one row (#616).
- The map at `/map` reads about 1.8 MB less data before its first view settles (2.50 MB to 0.66 MB for Morro Bay): it now opens on light copies of the reef atlas (the marks, without the habitat outline geometry the map draws from tiles), the species search plans (the target list, without the plans' geometry) and the shoreline (simplified to 10 m, single rocks under 20 m across left out until you zoom in). The full shoreline loads once you zoom in close, and every mark, target and shoreline card reads the same fields as before. The region build writes each copy beside its original with the original's checksum; the landing's night map uses the light shoreline too (#617).
- The map shows the coast outline sooner: until the map engine has drawn its first full frame, the region's shoreline is drawn over the empty map, lined up with the opening view (on a throttled phone about 2.5 s after opening instead of about 7 s). It goes as soon as the map has drawn or you move it. The home page also fetches the map's own scripts and styles in the background once it has painted, unless your browser asks to save data, so choosing a port opens the map faster (#617).
- The 2D and 3D terrain is easier to read: depth colours now span the depths in the current view (a Fixed depth colours option restores the old ramp), contour spacing adapts to that range with heavier index lines, and the seabed and land get hillshade and slope shading lit from a Sun direction you can turn. A Land slider blends the aerial photo against shaded relief, a sky gradient sits behind the 3D view, and a chip on the terrain always names the seabed exaggeration (for example "Seabed ×5 · land true scale"). The panel names the ramp's depth range and contour interval; measured depths and click inspection are unchanged.
- The Morro Bay map now opens on aerial imagery instead of the dark chart, drawn at full strength with a light desaturation so the shore, harbor and reefs read at a glance. The dated USDA NAIP imagery still shows its flown dates and credit, open water still has no imagery, and Night or Chart detail is one tap away in the layer rail; a link with `?base=` or a base you chose before still wins. A region's package opts in with `basemap.default: "aerial"` (only valid where it offers aerial), so other regions open as before. On a slow phone the imagery arrives several seconds after the chart underneath it.
- The brief now says what is missing and why instead of going quiet. A buoy, tide or marine alert source that is not current is listed by name with its own status: stale with the reading's age, the last good reading after a failed check, failed with nothing on hand, or not published. When a feed cannot be read the brief says which one, and with neither feed it reads "Readings unavailable." instead of waiting forever. What the day's model could not check (forecast hours with gaps, harbor entrance, local surf) folds into "Not checked in this brief". Shore run cards now say an access or rules review "expired" on its date instead of showing a past "review until" date.
- Morro Bay's offshore wind and wave reading now falls back to NDBC 46011 Santa Maria when Cape San Martin (46028) ages out or fails, labelled "46011 (backup for 46028)" with its own NOAA link. The Diablo Canyon wave buoy (46215) and the Port San Luis tide (9412110) stay single-station: the only nearby candidates, Avila Beach Nearshore and San Simeon, have sheltered exposure or share Port San Luis's predictions. The review is in `catalog/station-failover.json`, and a contract test now fails if any region names a backup without a reviewed entry there.
- The fleet processor no longer stops when its state mirror still holds trips classified before the fishing modes were renamed: those events stay out of the heat cells, are counted in the run log, and are replaced by the next reprocess (fleet-ais run 38194870723).
- The trip plan and saved-trip alerts in the map are now built into the app instead of the classic map's planner and alerts modules (#602). Saved plans, ranked selections, GPX files, offline notes and saved alerts carry over unchanged. Signed out, the alerts dialog shows only the sign-in prompt, without the species list it could not use; deleting your account still asks first, now with focus on Cancel.
- The Boat brief now shows fishing time and when to turn back: the run from the harbor to the selected place to look (or the top pick) at the cruise speed you set, and the latest turn-back time to be in by the end of the lower-exposure window. The cruise speed is kept on this device, set in Your limits for Boat, and has no default: until you set one the brief asks for it. Distances are straight-line, so the run is at least that long; with no window (a marine alert, a stale forecast, or none inside your limits) the brief says why there is no return time.
- The classic map is gone: `/` is always the landing (or the app when a link names an area), `/map` the app, and `/coast` opens the app's 3D view; `?ui=v1` and the `UI_V2` switch no longer change anything. The v1 shell, its coastal page and modules, Leaflet and the vendored map-test copies are deleted, and stylesheets are now minified (FE-61, part 1 of 3).
- When no configured buoy or tide station is fresh, the feed now serves the newest reading it has: a station that just returned a 3 h old reading shows it as stale with its own name, instead of an older retained reading from another station. A station removed from the chain no longer keeps serving under the new chain (#565).
- Configured buoy and tide roles can serve a reviewed fresh backup when their primary ages out. Source entries name the station used and its primary; feed health reports backup service as degraded without declaring an outage (#553). Legacy single-station feeds keep their existing format.

- When a backup station serves a buoy or tide reading, the landing, brief and daily evidence name that station as "backup for" the primary (for example "NDBC 46054 (backup for 46053)") and link to its own NOAA page, instead of showing it under the primary's name. Where the backup is also the other role's buoy, the reading says it is the same station rather than a separate measurement. Retained readings stay marked stale, and feeds without the new station fields read as before.
- The new home page and map can be added to a home screen with the SkipperCast name, icon and colour.
- The map at `/map` downloads about 2.2 MB less data when it opens: the region's shoreline, its region file and its protected areas were each fetched twice and now load once (#473).
- The map at `/map` downloads about 1.25 MB less when it opens: the published Morro Bay shoreline is 0.61 MB instead of 1.87 MB, with the same lines and the same source date, method and stated accuracy on every segment's card.
- The new home page and map now send the site's anonymous usage statistics: uncaught error reports (scrubbed message, script file name, line and column, build, hashed request id) and three visit steps, each with the region, build and `s` visit source: `port_selected` (a port chosen in the map's port chooser), `spot_saved` (a spot added to the trip) and `offline_saved` (a region saved for offline). The new home page sends error reports only. No cookies or identifiers, and nothing under Do Not Track or Global Privacy Control. The privacy notice now describes exactly what is collected, where it is stored (Cloudflare Workers Analytics Engine, kept three months) and that the daily operations report copies step counts and the top scrubbed errors into public GitHub Actions run summaries. The v1 About text no longer says there is no analytics.

### Internal

- RF0824-6: a published R2 feed that is asked for with `If-Match` or `If-Unmodified-Since` and fails that condition now answers 412 (no body, `no-store`, never cached) instead of 304, so a caller pinning an old object is not told its copy is current. These two conditions skip the edge cache and judge the current object's ETag (strong comparison) or whole-second upload time; an `If-Unmodified-Since` that is not an HTTP-date (for example `2020-01-01`) is ignored, and an `If-Match` list with an illegal tag (for example one holding a space) fails with 412; ordinary `If-None-Match`, `If-Modified-Since` and Range requests, and the cache-first path, are unchanged (`server/feeds.ts`, `tests/test_feed_preconditions.mjs`).

- Design only, no app change: `docs/plans/pelagic-context/design.md` sets what albacore and bluefin pelagic context may show at a selected hour (separate dated evidence lines, only WCOFS lines change with the hour, bluefin keeps no temperature range, no score, rank or probability), the held-out validation test a search priority must pass first (not evaluable on the data held today, so priority stays off), and records that the species-search-plans search strips were retired with the v1 map (#561).

- SP-FLEET-DATES: the public fleet heat route (`/api/fleet/public/heat`, still off by default) withholds a cell whose `last_date` is not an exact `YYYY-MM-DD` calendar day. The code re-check now rejects empty, padded, partial, timestamp-shaped and impossible dates such as 2021-02-29 before the 72-hour delay comparison, which the text comparison in SQL let through. The delay, vessel floor, rights allowlist, whole-season filter and paging are unchanged (`tests/test_sp_fleet_dates.mjs`, `scripts/accept_sp_fleet_dates.py`).

- The research-daily NOAA ENC hazard step retries NOAA's transient "Could not find service" 500 (bounded, capped backoff) on the same reviewed host; if NOAA stays down it writes an explicit `upstream_unavailable` receipt and the inventory report warns instead of failing, while a missing, corrupt or incomplete snapshot still fails closed. Each run attempt has its own identity (`github:<run id>:<attempt>`, or `ENC_INVOCATION_ID` locally), so output from an earlier run or attempt, or a status naming the wrong artifact, never counts. No new hosts were added. See [research-daily ENC unavailable](docs/operations/runbooks/research-daily-enc-unavailable.md).

- Add regression coverage for perspective-mode isolation and camera behavior.

- The AIS processor retains an unfinished full aggregate rebuild that was already authorized to prune. After a restart it replays the complete season with one timestamp before pruning and acknowledges that rebuild only after every chunk succeeds, so interruption cannot silently leave stale remote cells. Incremental uploads and fresh partial-state uploads keep their existing deletion tracking and prune protection (#624, A04).
- Historical AIS reruns and MarineCadastre backfills now read eligible registry MMSIs plus already approved strong watch mappings, preserving registry precedence, exclusions and ambiguous-MMSI holds. Unresolved explicit targets fail before ingestion, and a changed selected mapping stops derivation while preserving acquired raw rows. Current bindings do not prove past MMSI ownership; NOAA-derived rows retain their planning-only rights (#624, A01).
- `dist/export-ui.js` and `dist/trip-alerts.js` are retired: the planner's state is `web/planner.ts` (signals) drawn by `web/app/Planner.tsx`, and the alerts are `web/alerts.ts` and `web/app/TripAlerts.tsx`, both loaded on first open. `tests/test_planner.mjs` pins the draft key and shape, ranking, restore and the loading races; `tests/test_alerts.mjs` pins the API bodies; a new signed-in alerts case runs in `e2e/v2-account.spec.ts`.
- `/api/health` reads its version from `package.json` at build time instead of a literal that had to be bumped by hand with each release.
- `e2e/d1.ts` is the one `d1()` helper for `e2e/admin.spec.ts` and `e2e/fleet-admin.spec.ts`: it retries `wrangler d1 execute --local` up to five attempts with a growing pause when the running Worker holds the SQLite file (`SQLITE_BUSY` or "database is locked") and rethrows any other failure at once, with wrangler's stdout appended (#579).
- One conditions model: the text advisor's comfort word and the brief's lower-exposure windows now read `web/score.ts` instead of their own copies of its numbers, with no change to any rating. `docs/conditions-model.md` records why the graded score and the window rule stay separate and the four golden hours where they disagree (#542 C7).
- A deploy now fails, before anything is written, when the `CLOUDFLARE_SITE_URL` repository variable is unset, and the smoke-test steps of a deploy or manual rollback fail instead of passing with a warning: a green run no longer means a site nobody checked.
- Charter fleet (dark): AIS matching can watch a boat by `schedule-correlation`, when an MMSI broadcasting its name was at sea on at least 5 days, spanning 14, on which a landing report named the boat at its home port and no other boat of that port reported on those days (`thresholds.match.schedule`). The Worker and the matcher now refuse a watched row with a candidate-only method (`call-sign`, `ais-static-name`) or confidence under 0.85; `python -m skippercast.fleet.ais watch-check` checks stored rows and `schedule-precision` measures the method on a supplied report history (N4, #570).
- N7a: the charter-fleet classifier's validation (admin only) now also requires fishing precision 0.8 and recall 0.7 for each mode (drift, slow troll, pelagic troll), and reports the labelled fishing minutes it called transit and the scored trips by dominant mode, port and month, as counts only. `python -m skippercast.fleet.ais label export` writes a minute-by-minute summary of each unlabelled trip on the data runner, and `label import` checks an agent's proposed labels and posts them for the owner's approval to the job route added by #581 (`docs/operations/runbooks/fleet-labelling.md`, #570).
- Browser tests run one Worker process: `e2e/serve.mjs` now starts the Worker through Wrangler's programmatic API (`e2e/worker.mjs`, same `wrangler@4.142.0` pin, no file watching), and `e2e/d1.ts` sends the admin specs' SQL to a test-only endpoint in that Node process (127.0.0.1, ephemeral port, per-run token) that runs it on the running Worker's own D1 binding. Before, each `d1()` call started a second workerd (`wrangler d1 execute --local`) on the same SQLite state, which raced the dev server (`SQLITE_BUSY`, "Network connection lost") and broke later page loads. The admin specs' seeded ids are now unique per retry, so a retry no longer fails on the first attempt's rows, and their sign-in waits for the account dialog's passkey-autofill request before creating the passkey (#571, #579). This replaces the `wrangler d1 execute` retry above (#584).
- FE-62 part a: the retired `fish` repository's docs and research receipts are archived read-only in `docs/archive/fish/`, with the design § 15 retirement checklist and the Cloudflare resources the owner deletes; two identifiers were redacted and Fish's data, code and configuration were not copied.
- `verifyJobToken` caches GitHub's OIDC key set in memory for an hour (successful fetches only), refetching at most once a minute when a token names an unknown key id, so each job call no longer fetches the JWKS.
- `scripts/smoke_test.sh` reads the deployed build id from any stamped page in `dist/client`, since FE-61 removed `index.html`. Before this, `ls` failing under `pipefail` exited the script with code 2, which failed the smoke test for the dabb9c24 deploy even though the site was healthy.
- Charter-fleet heat map (N6, off by default): offshore pelagic trolling is aggregated in 3 km cells and the other fishing modes in 1 km cells (`resolution_by_kind` in `regions/<id>/fleet.json`). A public `GET /api/fleet/public/heat` returns cells only (mode, season, dwell, distinct-vessel count) with at least 3 vessels, at least 72 h old and only allowlisted rights; it answers 404 unless `FLEET_ENABLED` and the new `FLEET_PUBLIC_HEAT_ENABLED` are on, and is empty while aisstream data stays internal-only. The admin tracks layer now draws fishing segments only (#570).
- Charter-fleet labelling (admin only, N7): a labelling agent's proposed labels for a trip reach D1 through a new job route (`POST /api/fleet/jobs/labels`, run by the `fleet-ais.yml` `label_import` input) and replace that agent's earlier labels on the trip. The admin labelling list marks trips awaiting approval and filters them. On a trip, *Approve agent labels* records the approving admin as labeller and keeps the agent's name in the basis; rejecting a label is its delete (#570).
- Remove the dead `UI_V2` front-end switch configuration: the `UI_V2` and `ui_v2` settings in the Worker types, `deployments/production.json`, the deploy workflow and `scripts/wrangler_config.mjs`, with a test that it stays out of the deploy config.
- The charter-fleet activity classifier (admin only) labels fishing as drift or anchor, slow troll (salmon speeds) or offshore pelagic troll. Paddy stops inside a pelagic search join it into one run. Stretches it cannot decide are marked uncertain and never count as fishing. Transit keeps only statistics (minutes, points, mean and p90 speed, distance) and no track. All thresholds live in `regions/<id>/fleet.json`, and `classifier_version` moves to `c2`. The rules and their public sources are in `docs/plans/charter-fleet/references/classification.md`. A D1 migration adds `fleet_segments.p90_sog` and `distance_nm` (#570).
- A rollback is now confirmed by the Worker version Cloudflare reports live (`wrangler deployments list`), not by the build id `/api/health` serves: a commit that changed no client files has the same build id as the version it replaced, so the check wrongly reported a successful rollback as failed (follow-up to #568 / #569). The build id is only reported.
- A deploy whose smoke test fails now rolls the Worker back to the version that was live before it (recorded by `scripts/cloudflare_deploy.sh`) and, when `CLOUDFLARE_SITE_URL` is set, checks `/api/health` no longer serves the failed build. A bare `wrangler rollback` had landed on the failed commit's own code version, because the secrets upload makes a second deployment (#568). The manual rollback takes an optional version id and otherwise picks the version live before the current commit's deploy (`scripts/worker_versions.mjs`).
- FE-61: MapLibre and PMTiles build into their own chunk, tests of deleted v1 code are removed (v1 parity oracles pinned by digest), and `tests/test_no_v1_map_library.mjs` keeps the retired map library out.
- The startup measurement (`scripts/measure_startup.mjs`) counts `/coast-data/*` (the Worker bridge to the live Fish upstream) as live and stubs it, so the offline budget test no longer reaches the network or sometimes counts the habitat GeoJSON; `/coast.html` now redirects like `/coast`.
- `web/station-label.ts` holds the shared backup-station label logic, with unit tests and phone and laptop browser tests for primary, backup, retained-backup, missing-field and shared-station feeds.
- Test the v2 pages' head tags (`tests/test_v2_head.mjs`) so removing the v1 shell cannot drop them.
- `e2e/startup.spec.ts` now measures the v2 app at `/map` (`node scripts/measure_startup.mjs`; FE-61 removed the v1 measurement and its `--v2` flag): each committed startup file is requested once. Its total is printed and now budgeted (see the shoreline bullet below).
- `dist/regions/<id>/shoreline.geojson` is schema_version 2: the platform build merges import features with identical source properties into one MultiLineString each and rounds coordinates to 5 decimals (under half a zoom-12 CUSP tile unit, so every tile vertex keeps its grid position). The v2 `/map` startup test now holds its static JSON to the unchanged budget (2,529,983 of 2,795,531 bytes).

- Boat and Kayak can set a range to consider under Your limits (nautical miles, one way, kept on this device, no default). The Chart then draws a dashed ring that far from the harbor, labelled as a straight line, not a route; "Where to look" lists only places inside it and says so; Boat picks show their one-way run time at your cruise speed; and the trip planner's distance filter starts from your Boat range. Nothing is derived from a boat model, fuel or horsepower (#644).
- Spear sets its own deepest dive (10 to 100 ft, 60 by default), whether it dives from shore or a boat, and from shore the farthest swim; "Where to look" keeps to them, measuring the swim to the mapped shoreline as an approximate straight line. Kayak can start its range and distances from one of the region's listed public launches instead of the harbor (#644).

## 0.8.0 — 2026-10-11

- Suggested windows in the brief no longer run through an hour that a hazard rule flags or that the profile grades Rough, for every profile and whatever your limits say: a hazardous harbour bar at any hour of a boat window (not only departure and return), sneaker-wave swell for Shore when the surf is the offshore estimate, long-period swell under a kayak, and Rough Shore or Spear hours. Some windows are shorter or gone as a result. Occasionally a boat window the brief used to drop because its departure or return crossed a hazardous bar now appears as its clean remaining hours (#551).
- "Your limits": set your own highest wind, gust and seas (surf for Shore, plus the highest surge for Spear) for each profile, from beside the profile switch. They stay on this device. The brief's suggested windows use them, a stricter limit marks an otherwise calmer hour marginal and says which limit did it, and when a limit is looser than the default the brief says it is using your limits. Marine alerts, long-period swell, a hazardous bar, kayak offshore wind and launch surf, and daylight still rule hours out whatever you set. Reset to defaults clears them (#542).
- The Boat profile now checks the harbour bar at the four bars the Coast Guard regulates on this coast (Morro Bay, Humboldt Bay, Noyo River and Crescent City): each hour reads No bar flag, Caution, Hazardous or Unknown from the tide stage (the middle of the ebb counts most), swell height and period (the nearshore model where fresh, else a labelled offshore estimate) and, at Morro Bay only (using a shoreline bearing as a proxy), wind blowing in against the ebb. A hazardous hour sets the brief to Caution and leads the headline, windows that leave or return then are not suggested, the Tide tile shows the hour's ebb and bar band, and the brief always says this is an estimate rather than an official bar report and to check the Coast Guard bar status or harbor patrol (#542).
- New Kayak profile alongside Boat, Shore and Spear (chooser, `?profile=kayak`, first run and landing pills). Its brief puts wind first, with a Calmer limit of 10 kt sustained and 15 kt gusts, stricter than the boat rule; offshore wind (from the forecast direction against the vetted shoreline bearings for Morro Bay, Cambria and San Simeon; speed only elsewhere, and the brief says so) carries a caution and caps the hour at Marginal, so it is never the calmest hour, with a strong penalty above light wind; combined seas with short-period chop; surf at the launch beach from the shore surf estimate; hours outside daylight and under a fog or visibility marine alert are capped at Rough. Each hour reads Calmer, Marginal, Rough or Unknown with its reasons; the headline, summary, status, Wind and Swell tiles and the lower wind and seas windows use it, and the missing inputs are listed. At Morro Bay the deck adds that the harbour bar is not scored for a kayak and points to the Coast Guard bar status. Reef marks are limited to 120 ft. Kayak is client-only: saved /coast homes and the legacy coast page keep boat, shore and spear (#542).

- The Shore profile now gives a shore-fishing reading: surf from the fresh nearshore model where one covers the hour (Morro Bay), otherwise an offshore estimate labelled as such and judged on its own scale; a sneaker-wave caution for long-period swell, offshore or nearshore, that lowers the verdict; tide phase (the rising tide and the two hours around high scored mildly better, as an angler rule of thumb) with very low tides flagged for rock access; onshore or offshore wind where the forecast gives a direction and the stretch of coast has a vetted shoreline bearing (Morro Bay, Cambria and San Simeon; speed only elsewhere, and the brief says so); and a mild dawn and dusk bonus. Each hour reads Calmer, Marginal, Rough or Unknown with its reasons; the brief's headline, summary, status, Swell and Wind tiles and lower-exposure windows use it, and the missing inputs are listed (#542).

- The Spear profile now gives a spearfishing reading instead of always reading Unknown: surge from swell height and period (long-period swell counts more; a fresh nearshore model is preferred over offshore swell), a clarity estimate (likely good, fair or likely poor) from satellite chlorophyll, recent rain chance, recent swell and wind, with its drivers named and the missing inputs said when it cannot be estimated, and chop from wind. The brief's headline, summary, status, lower-exposure windows and Swell tile use it; clarity is always labelled an estimate, never a visibility measurement (#542).

- Preserve original classified-habitat source files in per-reach recovery so a clean publishing worker can verify them; report publication failures with code locations without logging data or exception payloads.

- Extend the reviewed San Simeon bedrock outlines across the remaining eligible native SCC03 footprint, retaining uncertain terrain and nonexportable area labels.

- Separate measured reef trip exports from research-coordinate references with explicit session opt-in and per-point evidence labels; preserve saved selections and all spatial/publication checks.

- Brief fixes on the map: a beach notice shows only for a beach under an advisory, closure or warning (no longer for open beaches whose county line says there are no advisory notes); where a coast report covers the area (Morro Bay, Cambria) the brief loads it whichever layers are on, so the tide curve and local-report line appear on first load; and the fleet line ("2 boats reported from Morro Bay & Avila Beach in the last 7 days") now appears, read from the daily feed's landing reports at the region's own landings.
- Choosing Chart while the map shows 2D now opens the Chart; it used to switch to 3D because the terrain's report of its own camera change was written back over the choice.
- The brief's Water and Tide tiles now read a source that served its last good data after a failed check as stale and say so ("last good 5 h old") instead of showing it as current. The hourly feed check now also lists each degraded source by name with its age in the live, daily and every region's live feed, fails when every source of one critical kind (buoys, alerts, tides or forecast models) in a feed has been degraded past its limit (a single buoy outage is reported in an issue without failing the run), and checks the daily data feed against its own 36-hour schedule.
- Import owner-supplied fleet scout CSV leads with public-page provenance and safe website handoff; preserve licence imports and keep unverified classes out of registry claims.

### Release notes: the new map is the default (FE-60)

- skippercast.com now opens the rebuilt app: `/` is the landing (the day's readings with their station and age, the profile choice and the layer links), `/map` is the map with the brief, Conditions, History, Reports, Fleet and Trip views, and `/coast` opens the map's 3D terrain. The entries below that say "In the new map preview (`?ui=v2`)" describe what is now the default; `?ui=v2` is no longer needed.
- Shared links keep working: a link to `/` that names a region, spot, coast, view, target, Fish place or coast key opens the map there, and `/coast` links keep their query.
- The classic map stays one more release at `/?ui=v1` (and offline at `/?ui=v1` once the service worker has installed); the next release removes it (FE-61). The site-wide switch back is the `UI_V2=false` repository variable, without a rebuild.
- The deploy's smoke test now also opens `/map` and `/coast`.
- The brief's Wind and Swell tiles now read the regional NOAA forecast (GFS wind, GFS-Wave seas) at the forecast point nearest the region centre in every region, not only Morro Bay and Cambria, with the model run's age; a run older than 18 hours is marked stale, and a missing forecast still reads unavailable. The brief and the Conditions view share one forecast request.

- In the new map preview (`?ui=v2`), the brief shows the day's tide curve as a small chart with night shaded and the high and low predictions under it, with their reference level (MLLW). Where a local coast report covers the area, the curve is that report's station prediction and the Tide tile says whether the tide is rising, falling or turning; elsewhere the brief says the tide series is unavailable and still lists the day's highs and lows. Dragging the curve moves the hour.
- In the new map preview (`?ui=v2`), the History view shows the recorded buoy history for Morro Bay and Cambria (NOAA NDBC 46028 and 46215): recent hourly means over the monthly 10th–90th percentile bands, with sample counts and coverage. The station, measurement and day-range choices are in the address, so Back and Forward and shared links keep them; other regions say recorded history is unavailable there.
- In the new map preview (`?ui=v2`), a Reports page (`?view=reports`, from the masthead, the landing's Reports link or the phone sheet's footer) gathers the dated evidence: the fleet's recent trip cards with their reported, retained and released counts (eight at most), recent fishing evidence, recent discussion links, the seasonal watch and the charter-reported grounds, each with its date and source link, plus the coast report feed.
- In the new map preview (`?ui=v2`), the Conditions view shows the seven-day forecast as one stacked chart (wind, gusts, offshore seas, air and cloud from the NOAA or ECMWF models, plus nearshore waves and the tide curve where a local coast report covers the area), a summary for the selected hour, each source's clock, the day's tide events and the profile's before-you-go notes with the CDFW rules link. Dragging the chart moves the hour the map and the time dock show; on a phone the chart scrolls sideways.
- In the new map preview (`?ui=v2`), the Fleet view holds the fleet controls beside the map: the charter grounds with their status and basis, the Commercial AIS 2024 option, and a link to the port pages' boat lists while those pages are on. For a signed-in admin the server admits, it also holds the fleet activity filter form (boat, port, class, trip type, activity type, dates, season), the three activity layers and the planning-only switch; every reading says the activity is inferred from movement.
- In the new map preview (`?ui=v2`), a reef mark, habitat outline or charter ground card shows the chosen target's rules at a glance from the reviewed CDFW registry (season state, bag and size as the registry words them, the date the official sources were last checked) with a link to the official CDFW page; an unchecked or changed source reads "Check rules". The target menu groups the profile's own species, the search plans for its method and the coast habitat targets, with a search field. Every layer basis links to the sources page, which now uses the new visual system.
- In the new map preview (`?ui=v2`), the brief's "Where to look" lists the top four places inside the profile's depth limit, with distance from the harbor, nominal depth range, habitat fit and one terrain reason: the reviewed coastal terrain habitat where it covers the region, else the survey reef atlas marks that pass the protected-area check, each list labelled by its source and never mixed. Tapping a place selects it on the map and opens its card. A ranked place is a place to look; fish presence is unverified.
- In the new map preview (`?ui=v2`), the brief column and the phone sheet now show the day's brief from the region's daily feed: the headline and summary, the Wind, Swell, Water and Tide tiles with their source and age (a reading past its limit is marked stale and says how old it is; a missing one reads unavailable), the lower-exposure window, the profile's caveat, a beach notice and fleet line when there is one, and whether a local coast report covers the area.

- In the new map preview (`?ui=v2`), the Shore profile draws Morro Bay's NOAA ESI 2006 sandy-shore runs on the Chart with their public access points. Each run is ranked by the protected-area check and whether a fresh nearshore model sample covers its area; an unavailable protected-area check holds it, an expired source review hides it, a run inside a protected area is blocked, and its card shows the review dates, method guidance and the official CDFW rules link. Access, rules and source review dates no longer set guidance priority; the original dates remain visible. Closed/nonpublic approaches are still rejected at import. The ranking orders places to check and does not establish legal permission; fish presence is unverified.
- In the new map preview (`?ui=v2`), Terrain 2D and 3D no longer show the classic terrain panels: seabed relief, water, depth contours, source coverage and reefs and pins are options of the Seafloor layer, a tapped terrain reading or reef opens the shared card with its measured or modelled label and source date and a link to the terrain sources, and zoom, reset and top view sit with the map's zoom buttons.
- Charter fleet admin: the outreach lead score's landing-report volume and reporting-frequency inputs now fill in, because each AIS processing run pairs a boat's trips with its published skipper reports and with the daily landing reports for the same boat, port and day (#345).
- In the new map preview (`?ui=v2`), an admin whose fleet flags are on gets the classic map's fleet activity layers under Charter fleet (activity stops, trip tracks and heat cells, each off by default and loaded for the map's view); every card and the legend's status line say the activity is inferred from movement. Nobody else sees the options.
- In the new map preview (`?ui=v2`), Terrain 2D and 3D now show the marine protected areas, the screened reef marks and, with Charter fleet on, the charter-reported grounds, in the same colours as the Chart: tapping an area or ground opens the same card as on the Chart, and tapping a reef mark selects it. Charter fleet no longer reads "Chart only" there; commercial AIS still draws on the Chart only.
- In the new map preview (`?ui=v2`), Charter fleet draws the Morro Bay charter-reported grounds (Pecho Rock and Diablo coast) as hatched outlines, with the classic map's rules: lingcod and rockfish only, within the profile's depth, and only while the protected-area check is current; a ground's card gives its reported trips, latest report and survey depths. Its option adds the 2024 commercial AIS cells (Global Fishing Watch, July and September 2024) as a heat fill, off by default, with the same wording as the classic map: apparent activity, depth and species unknown.
- In the new map preview (`?ui=v2`), "Show ranked spots on map" now draws the trip plan's ranked reefs on the Chart as numbered pins in the planner's order, as the classic map does: nearby spots share one pin ("1 +4") that zooms in when tapped, a pin opens its card with the rank, habitat fit and evidence confidence and "Review & export", and the pins go when the plan is cleared, the protected-area check is stale or the reef data changes (#495).
- In the new map preview (`?ui=v2`), the target menu lists the profile's species, the region's species search plans that fit Boat, Shore or Spear, and, where the region has coastal terrain, the terrain's own targets, each under its own name; a target the link names that the profile does not list stays chosen.
- In the new map preview (`?ui=v2`), Swell also draws the bound coast report's nearshore model sites (CDIP MOP, Morro Bay and Cambria) as rings sized by modelled wave height, only while each site's model run is under 48 hours old and its retrieval under 3 hours, at the sample nearest the dock's hour; a ring opens the site's card with height, period, direction, the sample time and the run's age, labelled as model output, not a buoy observation.
- In the new map preview (`?ui=v2`), each profile keeps its own map layers: switching between Boat, Shore and Spear restores that profile's last choice or its defaults, and the Boat default now draws Currents (the WCOFS forecast) when a link names no source; the landing's Currents dot opens with Currents on. The rail gains one Base choice (Night, Chart detail, and Aerial where offered), so a link's chart base can be chosen again; in 2D and 3D the entries that draw only on the Chart read "Chart only" and cannot be switched, and the legend shows a colour key only while its layer draws, saying why otherwise.
- In the new map preview (`?ui=v2`), reef marks are checked again in the browser against the current protected-area boundaries and the region's closures, as the current map does: a mark inside one, or every mark while that check is unavailable or more than 36 hours old, is withheld; a linked withheld mark's card and the legend say why and link the official CDFW or NOAA page.
- A region opened on the Guide, Conditions or Export tab now shows its opening view when you choose Map. Before, the map moved by half its size, and on a wide screen near Morro Bay that could send you to the Central Coast overview instead (#496).
- In the new map preview (`?ui=v2`), Swell on the Chart draws NOAA GFS-Wave's primary swell for the dock's hour as a colour field of height (one fixed 0–15 ft scale at every hour) with dashed period lines and short strokes showing the way it travels, on Morro Bay's and Cambria's offshore forecast grid: the legend gives the hour's height, period and direction, the model run, its age and the valid hour, as a model forecast and not a buoy observation; a click reads the model there; outside the grid stays blank, and a run over 36 hours old, an hour outside the run or a region without a grid draws nothing and says why.
- In the new map preview (`?ui=v2`), a reef mark's card adds it to the trip, and the account menu opens the trip plan and GPX (the classic map's day planner, the same draft, checks and GPX bytes) and "Save for offline": the region's pack now also keeps this app and its base map at zoom 8–12, and the coastal readings save with each source's own time. The offline shell no longer stores the new map's files for classic-map visitors.
- In the new landing (`?ui=v2`), a live night map loads once the page has painted: the Morro Bay CUSP coastline glow and the latest fresh surface-current frame as animated streamlines, with the footer crediting the basemap and giving the currents' source and age. The Currents dot previews them, they stand still under reduced motion, and without WebGL the static shoreline stays. The readings strip now names the area it reads ("Morro Bay & Avila area").
- In the new map preview (`?ui=v2`), Water temp on the Chart draws the coast report's daily sea-surface temperature analysis for Morro Bay and Cambria as a colour field with half-degree Fahrenheit contours labelled at whole degrees: the legend gives the range in °F, the product (NASA JPL MUR or NOAA Geo-Polar Blended, as the report names it), the analysis date and age and the analysis error; a click reads the temperature and its error; land and missing cells stay blank, and an analysis over 72 hours old, or one whose grid cannot be drawn, draws nothing and says why.
- In the new map preview (`?ui=v2`), the Chart offers an Aerial base where the region's package lists one (Morro Bay): the USDA NAIP natural-colour mosaic served by USGS, labelled in the rail and the map credit with the dates it was flown (13–29 May 2022), never as current conditions; its tiles are requested from USGS only while Aerial is on.
- In the new map preview (`?ui=v2`), the Chart draws the atlas reef marks with their habitat fit ("fits lingcod habitat 3 of 3"), survey habitat and geology outlines; one card shows the selected mark, outline or coastal habitat with its source, age and what its build screened, and a shared `?spot=` or `?habitat=` stays the one selection across Chart, 2D and 3D.
- In the new map preview (`?ui=v2`), the Seafloor layer draws the region's screened seafloor candidates and surveyed cells on the Chart, coloured by terrain grade or the target's species fit, with a legend naming the surveys and years; a held, updating or expired publication draws nothing and says why, and a click opens a candidate's nominal depth, survey, basis and source credits.
- In the new map preview (`?ui=v2`), the Chart always outlines the region's marine protected areas from CDFW ds582 (and southern California's NOAA groundfish exclusion areas) with a faint fill and dashed edge, names them from zoom 11, and credits ds582 (CC BY 4.0). A clicked area shows its name, designation, regulation section and snapshot date, with Regulations linking the official CDFW or NOAA page. The legend gives the snapshot date, or says the boundaries are partial, incomplete or did not load, so an area without an outline is never presented as unprotected.
- In the new map preview (`?ui=v2`), Currents on the Chart draws the chosen surface-current source as dashed, animated streamlines for Morro Bay and Cambria (the local WCOFS forecast or HF radar packet): the rail's source select sets `?current=`, a click reads speed and direction with the frame's time and age, land and gaps stay blank, a missing frame draws nothing and says why with the last valid time, and the motion stops when the page is hidden and stands still under reduced motion.
- Publish the Morro Bay region's ESI 2006 sandy-shore runs and Coastal Commission beach approaches as a candidate region file (reviews pending owner confirmation), with dated source, access and rules reviews that no import renews.
- The sources page now also answers at `/sources` (`/sources.html` keeps working), and the new landing, the readable report, methods and about pages and the new map's brief link there; the landing's “How it’s built” link no longer returns “Not found”.
- The readable coastal report, methods and about pages (`/report`, `/methodology`, `/about`) use the new dark visual system with self-hosted fonts and add a "How it’s built" link to the sources page; their text is unchanged.
- In the new map preview (`?ui=v2`), the masthead's sign in opens an account menu: passkey sign in, boat presets and the exact-boat sheet, saved-trip alerts, and the offline notes, GPX and offline pack entries.
- In the new map preview (`?ui=v2`), the time dock covers the full seven-day forecast: eight day chips, the chosen day's hours as exact UTC times, play that stops at the last hour and pauses when the page is hidden, and under reduced motion a "Next hour" step instead of play; the terrain follows the dock's hour.
- In the new map preview (`?ui=v2`), Clouds loops over observed GOES infrared frames on the Chart: only times NOAA nowCOAST lists, at most 90 minutes old and only on today's date (other days show none), each frame labelled in the legend with when it was observed and how long ago, with a toggle that holds the loop; it stops while the page is hidden and never plays under reduced motion.
- In the new map preview (`?ui=v2`), the Chart is a MapLibre map over the self-hosted basemap with the region's NOAA CUSP coastline, a nautical scale and north-up controls; `?base=chart` adds the NOAA ENC chart from zoom 10, a failing source is named in the legend while the rest keeps drawing, and a clicked shoreline segment opens the mark card with its source date. The MapLibre test page `/map-test.html` is removed.
- In the new map preview (`?ui=v2`), the map stage switches between Chart, 2D and 3D: the reviewed coastal terrain loads on the first 2D or 3D choice and follows the profile's depth limit, the target, the hour, the surface-current source and the selected habitat; a region without terrain, or a browser without graphics, stays on the chart and says why.
- Add the new landing page behind `UI_V2`: the Morro Bay shoreline drawn from NOAA CUSP, live wind, swell, water and tide with each source, age and stale state, the port question with Boat / Shore / Spear, links into the map's layers, and a saved port opening the map directly.

- Mapping batches can hand off one completed terrain/imagery slice for website 3D rendering, with exact display acceptance and explicit blocked prerequisites.

- Add stopped-run audits and skill learning between bounded mapping experiment rounds.

- Add bounded preflight and progress checks for coastal mapping runs.

- Text Advisor pages and the web chat use the new dark visual system, and the new app's masthead links to the chat while the advisor is on (both stay off until enabled).

### Internal

- Publish the GOES longwave frame times from nowCOAST's WMS capabilities each live cycle (`conditions/goes-times.json`, a `packages/coast` `CloudImage`: acquisition times only, newest frame at most 90 minutes old) for the v2 cloud loop (FE-44).

- Collect the CDIP nearshore model for five SLO sites (Pismo Beach Pier to San Simeon Beach) each live cycle into `conditions/regions/morro-bay/nearshore.json`, with site identity and coordinate checks, native three-hour times and publisher quality masks, in the coast report's `NearshoreSite` shape (FE-40).

- Collect SLO County beach water-contact statuses (status text, advisory text and the county link; no sample date invented) into the conditions feed about hourly, in the shape the coast report reads (FE-41).

- Collect NDBC 46215 and 46028 recorded history (SHA-checked annual archives, monthly p10/median/p90 with counts and coverage, 45-day hourly means) into the data feed for the History view (FE-42).

- Bound mapping investigation by a shared operating allowance, downstream readiness and verified public progress; preserve scientific and release gates.

- Finish moving `packages/coast/panel.css` onto the token bridge (FE-77b): its last 95 colour literals become `var(--coast-…, v1 value)`, so the file has no token-lint baseline entry left, and v2's `CoastMarkup` host drops `web/app/coast-markup.css`, which no longer changed anything. The v1 report dialog computes the same colours on every tab (browser check against values recorded from `main`).

- Move the first half of `packages/coast/panel.css` onto the token bridge (FE-77a): its colour aliases become `var(--coast-…, v1 value)` and lines 1–1,472 follow, so the rules they hold read `web/tokens.css` under `data-coast-theme="tokens"` (FE-77b converts the rest). The v1 report dialog computes the same colours on every tab (browser check against values recorded from `main`).

- Bridge `packages/coast` to the v2 tokens (FE-76): `coast.css` and the series chart write colours as `var(--coast-…, v1 literal)`, `tokens-bridge.css` maps them to `web/tokens.css` only under `data-coast-theme="tokens"`, the 3D viewer reads `DEFAULT_COAST_PALETTE`, and the token lint now covers `packages/coast` with its own shrink-only baseline. v1 pages compute the same colours (browser check against values recorded from `main`).

- Add an overlay API to the coast embed (FE-81): `setOverlay` drapes GeoJSON fills, lines and points on the terrain in draw order with colours named by role from a host `overlayPalette`, `removeOverlay` frees them, and `onOverlayPick` reports the overlay and feature ids of a click. v1 passes no overlays and is unchanged.

## 0.7.0 — 2026-10-07

- Explicitly save and delete public coastal report, current and measured-history snapshots for offline use, with saved time and original source clocks.

- Add an opt-in bounded reader for authenticated original regular BAG cells.

### Internal

- Bound explicit coastal snapshot storage and preserve publication/private exclusions, source expiry and completed-pack replacement semantics.

- Preserve original BAG cell values, uncertainty and source registration; keep the reader private-only and separate from EPSG:3310 production processing.

## 0.6.0 — 2026-10-07

- Add isolated reference-grid routing for explicitly selected scope configs while keeping the Central Coast pipeline as the default.

- Share one explicit surface-current source choice across the coastal chart, native 2D/3D and Conditions. Off clears vectors; missing coverage or source hours remain gaps without provider substitution.

### Internal

- Preserve retained Central Coast grid and physical-cache identities; keep noncentral screening, processing and publication held until their scope contracts are complete.

- Validate exact current-product identity, original frame and source clocks, finite wet-cell values and source expiry; suppress delayed replies and preserve readable return state.

## 0.5.0 — 2026-10-07

- Record verified NOAA reuse terms and original coordinate/depth references for two southern survey candidates.

- Connect the Central Coast overview to shared terrain presentation, profile, target and UTC time. Preserve independent model forecasts, original source expiry, explicit package handoffs and geographic gaps in local readings.

### Internal

- Preserve candidate status, source IDs and hashes, unknown acquisition lineage and source-specific terrain, regional, camera and hazard-review gates for the H11879 2 m and H11880 1 m records.

- Verify exact restored source identities, earliest publication expiry, unsupported UTC selections, stale replies and malformed model cache admission.

## 0.4.0 — 2026-10-07

- Prevent early confidence UI imports from capturing another region’s forecast coordinates. Keep unit helpers independent of regional data; withhold current readings when the selected sample is absent.

- Normalize legacy Fish place/species/profile/hour links before startup, retain unsupported selections explicitly, and share saved-home save/forget behavior with native coast preferences. Keep exact public geography and profile through port handoffs and browser history.

- Add a readable coastal source report without JavaScript, original-clock SLO RSS, and canonical methods/about/privacy entry routes. Retain shared public selection and private request boundaries; fix profile-only changes after lazy local report loading.

- Bring original local Boat/Shore/Spear readings, buoy history, dated fleet facts and source receipts into Conditions with the shared place and UTC hour. Preserve distinct native species and source horizons; unsupported methods and regions remain explicit gaps.

- Expand one unranked SCC06 bedrock outline into a reviewed adjoining native window, with a new geometry-derived identifier; retain unknown terrain grades and species fits and exclude precise exports.

- Added the native coastal 2D/3D terrain as a presentation in the working chart workspace, sharing target, location and seven-day forecast time while retaining chart, planning, legal and account tools.

- Add four unranked SCC06 bedrock interpretations from one reviewed native window, with an explicitly reidentified SCC05 boundary after source-priority exclusion; retain unknown terrain grades and species fits and exclude precise exports.

- Add a reusable coastal-map skill with bounded subagents, tested model-setting records, honest visual enhancement, desktop/mobile acceptance and protected live-release checks.

- Keep coastal zoom controls clear of the species selector at medium phone and narrow tablet widths.

- Add an explicit conservative canonical occupied-subtraction option for reviewed original bedrock: remove bounded reprojection residuals without tolerating retained overlap, modifying prior geometry or activating a source.
- Bring the shared Monterey–Point Conception 2D/3D coast renderer and SLO daily report into SkipperCast at `/coast`, reachable from map options. Preserve original terrain evidence, habitat expiry, source clocks, existing chart/trip/account tools and shared location/target/hour links. Keep the existing homepage until full workspace parity. Fix coastal subrequests for the actual Cloudflare redirect API while continuing to reject every redirect.

- Add Fish link compatibility to the shared v2 state: preserve the fishing profile, target, place and whole-hour timestamps while giving explicit SkipperCast choices precedence. Legacy UI remains the live default until feature integration is verified.

- Define a bounded overnight mapping contract with exclusive worker claims, compact model briefs, release preflight and outcome-based checkpoints; distinguish the documented protocol from automated enforcement.
- Add a bounded read-only coastal data bridge for the Fish integration. Preserve public snapshot clocks and habitat release checks, isolate private storage and accounts, and reject foreign-region bindings, unsafe paths and inexact byte ranges. The current homepage remains active.

- Recognize one authenticated legacy San Simeon physical inventory in private window planning across screen-only refreshes, without fabricating a quarantine audit or changing publication checks.

- Document recovery of replaced scoped seafloor publication runs: retain unverified region scopes, inspect actual prepare matrices, refresh omitted regions with the existing workflow and verify each regional live readback.

- Extend reviewed San Simeon geology over 17 depth-qualified native SCC05 windows, preserving prior habitat, uncertain lithology, current spatial holds and private projection conflicts. Interpreted outlines remain unranked and nonexportable.

- Add reviewed exposed-bedrock outlines from two native SCC06 depth windows near Cambria, retaining prior habitat, current whole-polygon spatial exclusions and separate producer rights. These interpreted areas remain unranked and nonexportable.

- Enable reviewed Offshore Monterey exposed-bedrock outlines over existing native Monastery/Cypress depth at nominal25–300ft. Preserve original geology units, prior native areas, current whole-polygon exclusions and separate CSUMB noncommercial terms; leave uncertain terrain unranked and precise exports disabled.

- Add an explicit audited San Simeon geology profile for additional native survey pairs. Keep existing profile behavior unchanged, retain original PolygonZ geometry and invalid-source holds, and use strict unrepaired representations with private recovery. This code change activates no source.

- Support an explicit reviewed Monterey original-geology profile for unranked bedrock habitat. Preserve prior native features and source units; retain invalid derived representations privately with authenticated recovery and publication reconstruction. This code change enables no source, new ranks or precise exports.

- Enable reviewed original San Simeon exposed-bedrock habitat from two disjoint native depth windows, retaining source units, current habitat exclusions and whole-polygon spatial screens. These areas are unranked and receive no new measurement or precise fishing export.

- Extend reviewed SCC06 exposed-bedrock habitat to one additional disjoint native depth window, preserving prior features and current whole-polygon screens. The interpreted area remains unranked and nonexportable.

- Add explicit reviewed original-geology admission for unranked bedrock habitat, using bounded native depth windows, current canonical habitat exclusions, retained source units and separate producer rights. Preserve legacy rugose-rock outputs; bedrock map details keep rugosity, boulder size and species fit unknown. No source is enabled by this code change.

- Add the v2 port chooser and first run behind `UI_V2` (`web/ports.ts`, `web/landing/PortInput.tsx`, `web/app/FirstRun.tsx`): the command bar's area group gains a port button and "Use my location", which open the chooser as a dialog (search over the home ports by name, the featured ports first, Enter for the top match, the 75 nm nearest-port rule with v1's privacy line, "Explore the coast"); a choice saves the port under the key v1 reads and swaps the region without a reload; `/map` with no area opens the saved port or the landing. First run is now the Boat / Shore / Spear choice only, shown once over the map (never modal, never when the link names a profile); the home-port modal does not return in v2. Nothing changes without the flag or `?ui=v2`.
- Add the v2 mobile app shell at `/map` behind `UI_V2` (under 1,024 px, `web/app/Mobile.tsx`): the map fills the screen under a top strip with the brand and location card, a layers button and the full-width Boat / Shore / Spear switch; one bottom sheet with peek, half and full detents moved by drag and keyboard holds the time window, freshness, headline, four tiles in a row, "where to look", the tide curve slot, the day, target and area menus and the disclaimer line, with the hour slider at its top edge; the layers button swaps the sheet to the rail with the legend; a selected mark's card takes the sheet's peek; a four-tab nav (Coast / Conditions / History / Fleet) sits under the sheet. No horizontal scroll from 320 px; 44 px targets. Nothing changes without the flag or `?ui=v2`.
- Add the v2 desktop app shell at `/map` behind `UI_V2` (`web/app/`, concept A · Bridge): masthead with the region's name and centre, the Coast / Conditions / History / Fleet views as `?view=` links, the freshness dot and sign in (the v1 passkey dialog); a command bar with the Boat / Shore / Spear switch, target, area and a read-only time-window readout (the dock sets it; FE-12 brings the forecast horizon); a 332 px brief column in its empty state (headline, four tiles reading "—" with their source line and basis, tide curve slot, "where to look", the profile's caveat, one disclaimer line); and a map stage with the layer rail, one legend (hidden under 1,024 px until FE-06), the time dock and the selected-mark card, every control writing the address. The map itself and the readings arrive with later tasks; nothing changes without the flag or `?ui=v2`.
- Fix the fleet OSINT run (`fleet-osint.yml`) so that when some batches fail, the finished batches' profiles are still ingested before the job fails; previously the research step aborted on the runner's exit 1 and skipped Ingest, leaving finished profiles out of the registry.
- Start the front-end rebuild behind `UI_V2` (off; [plan](docs/plans/front-end/README.md), ADR 0009 and ADR 0005 accepted): with the Worker variable on or `?ui=v2` on the request, `/` serves the new landing page (or the new app when the link names an area) and `/map` the new app, both placeholders for now; `?ui=v1` forces the current shell. With the flag off and no switch nothing changes: `/` is the current site and `/map` is 404.
- Add the v2 icon set and UI primitives (`web/ui/`: 40 stroke icons, 31 ported from `fish`; Button, Chip and Segmented, Tile, Popover, Rail, Dock with Range, and the three-detent Sheet), styled from tokens only with 44 px targets and keyboard operation. Nothing visible changes until a v2 page uses them behind `UI_V2`.
- Add the v2 design tokens (`web/tokens.css`: dark default, light set, DM Sans and JetBrains Mono self-hosted under `web/fonts/`), extend the contrast check to both token files and add `scripts/check_tokens.mjs`, which fails CI on colour or font literals under `web/`. Nothing visible changes until a v2 page loads the tokens behind `UI_V2`.
- Add the charter fleet's weekly OSINT run (`fleet-osint.yml`, dark behind `ENABLE_FLEET`): batch manifests are researched by a pinned, headless Claude Code session with the `charter-osint` agent on the owner's runner, using the Claude subscription only (the run stops if an API key is set), with fetches to off-limits hosts refused, then validated and ingested; boats whose operator asked for removal are never researched or updated.
- Add the charter fleet's Labelling view to the admin behind `FLEET_ENABLED` (off): pick a trip (`#fleet-labels`), see its segments on a small track map and a speed strip, all marked inferred from movement, and label time ranges as in port, transit, fishing drift or fishing troll with a basis; each label records its labeller. `python -m skippercast.fleet.ais validate` copies labelled trips' raw positions to `validation/` (exempt from retention while labelled) and reports fishing and per-label precision and recall with a confusion table.
- Add fleet admin Coverage (`#fleet-coverage`: boats by port and class, % with MMSI, AIS seen or not seen in 30 days, single-source boats, completeness by field group, recent runs) and AIS health (`#fleet-ais`: last message age, 24 h reconnects and drops, gaps over 10 minutes, 7- and 30-day uptime, processor and watch list) views, admin only behind `FLEET_ENABLED` (off).
- Limit verified classified-policy updates to complete affected regions, including previous scopes and neighbors; uncertain changes retain the full-coast planner.
- Bind every coastal region's charter identity coverage to the new charter fleet registry (`fleet-registry`, superseding `operator-identities`) and show it as registry counts only; with the registry still empty, each region now reads "missing". Add the fleet pipeline's `discover`, `resolve`, `ingest`, `refresh` and `run` steps and `coverage-status` (all dark behind `FLEET_ENABLED`).
- Add the fleet pipeline's `plan-agent` step, which writes OSINT batch manifests of at most 20 boats from registry data only (new, stale or incomplete boats), and `ingest --profiles`, which validates each OSINT profile, refuses and lists invalid ones, and stores the rest as `osint` facts, trips and conflict reviews; a value missing from a newer profile never replaces an older one, and Google ratings are never stored.
- Add admin-only charter fleet activity layers to the map behind `FLEET_MAP_ENABLED` (off): activity stops sized by dwell, trip tracks coloured by segment and a heat layer, with boat, port, class, trip type, activity, date and season filters; every card says the activity is inferred from movement.
- Add the charter fleet's Fleet review and Vessels views to the admin behind `FLEET_ENABLED` (off): decide registry reviews, browse vessels by port, class, status, profile, AIS and completeness, and open a vessel's fields, facts, offerings, changes and trips; a field edit is recorded as an admin fact and pinned, and a removal request shows as keeping the boat off public pages.
- Add the charter fleet's Operators view to the admin behind `FLEET_ENABLED` (off): operators ranked by a 0-100 lead score shown with its parts and missing inputs, consent recorded with who, when and how, notes and outreach drafts that are never sent from SkipperCast (approve, discard, or log as sent by the owner), and do-not-contact blocking new drafts.
- Enable reviewed, unranked original 5 m Monterey rock habitat in r01 with prior-survey native exclusions, neighboring planning holds and fresh spatial screens; no new measurement, ranking or precise fishing export.

- Deduplicate interpreted habitat from overlapping survey pairs in reviewed source order, preserving earlier native outlines and rejecting stale publication receipts after a priority change.

- Enable reviewed, unranked Point Conception rock habitat in r08 with original NOAA/USGS attribution and fresh whole-polygon spatial holds; no new measurement, ranking or precise fishing export.

- Enable reviewed, unranked Point Estero rock habitat in Cambria r02, with fresh whole-polygon spatial holds and no new measurement, ranking or precise fishing export.

- Bound nonlinear map-coordinate conversion with collinear native-edge vertices when needed; preserve measured boundaries, original legal screens and existing fidelity limits.

- Add opt-in whole-polygon holds against verified neighboring planning footprints for classified habitat releases; preserve original native boundaries and recheck holds before publication.

- Verify current native dependencies and retain producer rights for survey footprints used by the opt-in classified habitat mode; keep original depth and rock interpretation authoritative.

- Scope classified habitat processing to reviewed reaches and add an opt-in paired-survey footprint mode, preserving original depth/class masks, existing rankings and publication checks.

- Show charter fleet boats on `/boats/<slug>` behind `FLEET_ENABLED` (off): class, landing, size, trips with prices as listed and the date, booking and website links through `/go/`, the business phone, photo links with credit, the Google rating with its link while under 30 days old, and dated sources; nothing from AIS, NOAA planning data or low-confidence facts, and out of search until the operator agrees. Advisor boat pages are unchanged while the flag is off.

- Preserve original native classified habitat boundaries while validating bounded shell/hole map representations; keep original areas and current spatial screening authoritative.

- Add a separate screened, unranked publisher-interpreted rugose-rock habitat area layer. These Tier1 areas receive no terrain/species rank or precise fishing export; original source pairs require explicit reviewed opt-in.

- Add a bounded private probe for reviewed rugose-rock habitat beyond existing terrain outlines; distinguish habitat expansion from new survey coverage in the coastal mapping skill.

- Harden the Text Advisor before launch: crew join only after replying YES (and only verified boats can invite), texts to numbers that never wrote to us are capped per number, per sender, per address and per day, the web chat has its own AI budget, unconfirmed boats' pages show no links, morning Stories trust only iMessage or upload-link photos from the owner or confirmed crew, upload and data links keep their token out of URLs and logs, the relay keeps messages at most 30 days and off iCloud, and every advisor secret has a rotation procedure (with a phone-number re-key script).

- Let the Text Advisor read photos with the owner's own Hermes vision service when it is set up, falling back to Claude whenever Hermes is slow or down, with a conformance script the Hermes side runs first; admin Health shows each vision provider's setup, skips and last answer.

- Get the Text Advisor ready to launch: a preflight script that checks a deployment against the launch checklist, a live prompt eval that also covers the daily answers and post captions, a runbook for unanswered messages, and the owner's launch to-do with the exact switch-on order.

- Delete Text Advisor data on schedule, every Sunday: message text after 180 days, photos nobody approved or posted after 90 days, team review notes 90 days after the decision, unlinked web chats 90 days after their last message, and data copies after 7 days; the privacy notice now says so.

- Read each published post's Instagram and Facebook numbers every night (Stories hourly while they are up) and show them on the post's card with the chats its link started; the admin Funnel gains a social section.

- Answer Instagram direct messages and comment keywords (RIG, REPORT, ID, BOATS, in English and Spanish) once Meta approves the app: one private reply per keyword comment, DM answers within Meta's 24-hour window, public answers to questions only when switched on, and a privacy-notice section for the Text Advisor awaiting review.

- Post the morning Stories automatically: each verified boat's count board from the day before (once its photo has no hold) and a conditions card for the day.

- Draft a daily "what's biting" post from yesterday's verified boat reports and a Sunday roundup carousel of the week's catch photos for the team to approve, and schedule approved posts into a weekly posting calendar shown in the admin Posts view.

- Strip text-advisor videos of their camera metadata (location included) before they can be approved, posted or served: the media runner copies each video without metadata with ffmpeg, and the public video link only ever serves that copy.

- Keep text-advisor photos upright: intake still strips all EXIF but keeps the JPEG's orientation value, so derived images are turned the right way, vision is told when a photo is rotated, and a sideways original is never shown on a page.

- Remember bounded completed seafloor discovery tests in an expiring private checkpoint. Keep changed or damaged evidence actionable, preserve separate recovery scopes, and avoid treating duplicate leads as new mapping work.

- Refine Big Sur habitat outlines with the original BSS08 2 m rough/smooth terrain layer. Preserve measured depth, uncertainty, credited noncommercial terms and spatial screening; this adds no new surveyed area.

- Show spatially screened measured rough-bottom patches as limited-confidence,
  unranked search areas when surrounding data cannot support a terrain grade.
  Keep detailed rankings, source-quality holds and precise fishing exports separate.

- Inspect geographic seafloor grids with their original angular registration and explicit ground-spacing ranges. Preserve native values and masks, existing metric-adapter guards and caches; interpolated DEM pixels remain unqualified for measured habitat.

- Reject acquisition-gap snapshots that omit or change surveys already used by the map. Check native source bindings before requests, preserve private physical work, and resume through unchanged measurement/rights-only refreshes without repeating source queries.

- Keep private sonar-grid medians consistent with their checked contributor depth ranges when the official readers print different precision. Preserve strict integrity checks, original outputs and source/publication holds.

- Add bounded no-fill point-bin diagnostics with independent statistic checks before lidar ingestion. Keep useful shallow measurements for future shore-fishing and spearfishing research without claiming ranked or published fishing locations.

- Let bounded original-sonar triage use a pinned private native-gap snapshot on a processing host without copying the raster cache. Preserve topology, depth/quality checks and publication holds; this screening tool adds no mapped area by itself.

- Recover the measured seafloor layer automatically after temporary publication updates, with bounded retries and expiry checks; preserve screening holds and manual layer-off choices.

- Refine Cambria/Point Estero habitat with original SCC04–06 native terrain classes, retaining measured depth, existing rankings and all source/publication restrictions. No new surveyed area is claimed.

- Refine San Simeon/Cambria habitat with the original SCC01–03 native terrain classes, preserving measured depth, producer terms and all spatial screens. Source qualification adds no new surveyed area.

- Qualify the original 2 m Monastery Beach–Cypress Point grid for the measured habitat pipeline; preserve mixed 2000–2006 dates, unknown datum and credited noncommercial terms. Source qualification alone adds no published fishing locations.

- Seafloor: complete the remaining Arguello permanent spatial review so all 33 Monterey–Point Conception reaches can be screened. Reuse physical terrain; retain all 32 affected candidates as MPA exclusions, including four security overlaps. No new measured coverage or public fishing locations is claimed.

- Add an isolated government-only seafloor input scope for separately reviewed commercial releases, retaining indirect calibration, whole-polygon screening and publication gates.

- Make browser map checks independent of live boundary-feed timing, retaining the production MPA gates and testing that unavailable current checks still withhold fishing targets.

- Qualify SCC26–28 native depth for credited noncommercial mapping, retaining MPA, security and edge-support holds while refining all affected habitat calibration.

- Refine Avila habitat with the original native terrain classes, retaining measured depth and Block J's private quality hold.

- Recover missing feed worktrees after runner cleanup so recurring source discovery can load its inputs, while preserving locked and unrelated worktrees.

- Bind original PGE Mid native terrain classes to reviewed depth, preserving measured support and existing source holds while refining habitat calibration and extraction.

- Bind original PGE South native terrain classes to reviewed depth, preserving measured support and existing source holds while refining habitat calibration and extraction.

- Bind five original SCC rough-terrain grids to their native depth sources. Preserve measured coverage, tighten eligible habitat boundaries and retain all private source/spatial holds; local screening gains 89 connected outlines while habitat area decreases by 3.057 km².

- Add source-bound native rough-terrain support for habitat calibration and extraction, preserving measured depth, existing quality holds and current publication checks.

- Preserve four original PGE South native grids as private physical sources: 111.052 km² of additional selected support and ranked candidates remain available for artifact review, with no new public fishing targets.

- Hold Avila Block J habitat pending native artifact review, retain its measured depth privately, and recompute affected public source selection and shared thresholds without changing scientific rules.

- Retain valid measured depth while keeping habitat from sources with unresolved artifact or interpretation reviews out of public maps and fishing exports.

- Apply reviewed USGS seafloor classes to thirteen SCC depth grids; preserve measured coverage and remove sediment-backed terrain candidates without claiming independent fish evidence.

- Add original 2 m Point Lobos survey support: 4.019 km² of additional selected measured coverage, ranked habitat and whole-polygon MPA screening; retain unknown datum and credited noncommercial terms.

Release reviewed Avila and SCC16 native source rows and complete the spatial-screen scope for three Avila/Pismo/northern Arguello reaches, preserving physical-first processing and whole-polygon exclusions.

Qualify seven original PGE_Mid native grids, adding 33.91 km² of selected shallow survey support across two Morro reaches while preserving native resolution, producer rights and final spatial screening.

- Seafloor: qualify existing SCC13–15 native 2 m grids; local processing adds 445 screened areas and 4.721851 km² of habitat across three bounded reaches and their shared northern boundary.

- Seafloor: qualify seven existing SCC09–12 native grids, adding 59 screened areas and 1.002481 km² of habitat across three Morro reaches in local validation; public release remains subject to the production pipeline.

- Permit the reviewed NOAA Point Lobos original archive through the native seafloor importer while retaining checksum, format and producer-use checks.

- Seafloor: qualify six existing Big Creek/Lopez Point native grids with preserved source identities and reviewed metadata corrections. Complete the intervening Big Sur reach screen; local results contain 284 passing habitat areas with all 184 held areas private. This releases existing measured support and does not claim new sonar coverage.

- Seafloor: qualify native Kasler, Soberanes and Yankee Point 2 m depth grids. Three Monterey reaches gain 24.490 km² of selected measured support and 240 net screened habitat areas in local validation, with source datum conflicts and protected-area holds retained. Production publication is verified separately.

- Seafloor: qualify native 2 m Grimes Point bathymetry and release the existing Slate Rock source under credited noncommercial terms. Two Big Sur reaches gain 416 net locally screened habitat areas. Report Grimes Point's new survey footprint separately from Slate Rock's existing private coverage; retain nominal NAVD88 depths and all publication screens.

- Seafloor: qualify original Hurricane Point, Cooper Point and Point Sur 2 m grids. Three local reaches gain 62.910 km² of selected measured support, 410 physical candidates and 46 net screened areas; the two Big Sur reaches increase from 1 to 126 screened areas. Keep source datum limitations explicit and all MPA holds private; production is verified separately.

- CI: run the complete check suite once per PR revision, preserve main and bot-dispatch checks, and cancel obsolete PR revisions so mapping work does not compete with duplicate checks.

- Seafloor: group up to three regional reaches per worker to reduce runner startup and queue overhead. Preserve exact reach assignments, sequential native validation, independent recovery receipts and complete-region publication checks; a failed reach does not stop its neighbors.

- Seafloor: use the original USGS Point Conception seafloor-character grid with seven NOAA depth products. Preserve shared survey lineage, unknown classifier accuracy and anthropogenic classes; exclude interpreted sediment from reef extraction. Local results refine 843 screened areas to 788 without adding measured bathymetric coverage.

- Seafloor: qualify original NOAA H11952 1 m shallow bathymetry near Point Conception. Local processing adds 4.353 km² of selected survey support while replacing coarser habitat classifications; candidate counts and published area may decrease with finer evidence.

- Seafloor: qualify 13 original SCC01–08 native grids for credited noncommercial use and screen Cambria–San Simeon r01. Reuse three verified private terrain caches, including categorical-row numeric normalization; local screening yields 611 areas across three reaches, 513 above the prior public subset. Production is verified separately.

- Seafloor: qualify credited noncommercial SCC17–25 depth grids and screen three Point Sal–Purisima reaches, retaining native 2 m measurements, private holds and the paid-deployment gate. Local validation yields 1,471 eligible habitat areas; production publication is verified separately.

- Seafloor: explicitly migrate verified legacy numeric-only cache identities without recalculating terrain or changing habitat geometry/ranks; retain complete private recovery and require fresh screening before release.
- Seafloor: declare the current noncommercial deployment profile and block incompatible paid deployments before writes; retain original producer credits and permission requirements.

- Trips: a launch-point catalog (`catalog/launch-points.json`, from the California DBW Boating Facilities records) builds `dist/regions/<id>/launch-points.json` for every published region; Morro Bay's public ramp, the Port San Luis ramp and Olde Port Beach are the first entries.
- Trips: a saved trip now carries its plan (launch point, up to three target species, spots, legs, window, exports taken and a status) through migration 0005 and `PATCH /api/trips`; the one-tap alert save is unchanged.

- Operations: the deploy no longer needs `VAPID_*` GitHub secrets; when they are unset it keeps the Web Push pair in the private backup bucket (`secrets/vapid.json`), generated once on the first deploy and reused after that, so alerts work on a fresh account with no manual key step.
- Seafloor: allow reviewed CSUMB originals from NOAA's Ventresca archive under the existing hash-bound noncommercial producer contract. Retain attribution and for-profit/navigation restrictions; unreviewed sources and cruises remain blocked. No catalog source or map is released by this change alone.
- Reconcile seventeen existing BSS native survey records with the newer coastal source stack while preserving prior sources and screened-cache evidence; use their reviewed noncommercial contract during the owner-authorized personal-use phase.

- Qualify six original SCC10–13 native depth grids; refine five private Morro Bay reaches with 347 net habitat candidates, retaining the measured coverage decrease and release holds.

- Qualify original SCC07–09 native 2 m/5 m bands: add 14.833 km² of private measured Point Estero/northern Morro coverage and 46 net habitat candidates, retaining native depth limits and release holds.

- Qualify cached native 5 m SCC03/04 shelf bands: add 2.191 km² of private measured coverage near the 300 ft limit; retain the 12-candidate net reduction and unchanged suitability rubric.

- Qualify original SCC26–28 native grids: add 36.624 km² of private measured Arguello coverage and 608 net habitat candidates; preserve source ownership, 1–3 rankings and release holds.

- Inspect native Avila–Pismo and southern Arguello grids: add 104.209 km² of private measured coverage and 2,005 net habitat candidates, retaining missing/conflicting metadata and release holds.

- Seafloor: inspect SCC06/14/24 native grids; add 56.29 km² selected coverage and 363 net private candidates, including first measured habitat in Arguello r05. Identify original Morro–Avila survey leads for the remaining southern gap.
- Seafloor: inspect native SCC05/15/23 and the deeper 5 m SCC05 companion; add 44.70 km² selected coverage and 81 net private habitat candidates, preserving source ownership and publication holds.
- Inspect native SCC04/16/22 grids and add private ranked Cambria/Arguello shelf coverage, preserving datum, mixed survey dates and publication holds.
- Seafloor: privately qualify native SCC03/17/21 and fill two previously empty Cambria/Conception reaches, updating three neighbors. Add 63.53 km² net measured coverage and 946 physical candidates; publication and incomplete-rank holds remain.

- Seafloor: privately qualify native SCC02/18/20 original grids and process their actual shallow intersections. Add 72.54 km² net measured coverage and 978 physical habitat candidates in the San Simeon approach and Arguello/Conception area; retain publication and ranking holds.

- Seafloor: privately qualify nine native Big Creek, Slate Rock and SCC grids. Four local reaches gain 69.54 km² of measured depth coverage and 824 physical habitat candidates; producer release qualification and spatial screening remain required before map/export publication.

- Seafloor: open explicitly selected native ArcInfo grids inside original NOAA ZIP-in-tar survey bundles, with bounded extraction and checked private recovery. Preserve native pixels and reject unsafe containers; source qualification and public screening remain separate.
- Seafloor: publish regions independently with retained batch identities for failed-job retries. Reconcile the ledger separately without downloading original surveys; retain scientific checks, report failed regions and log publication stages rather than timing out the entire coast in one job.

- Seafloor: transfer checked private physical results after rights-only source promotion without recalculating terrain. Preserve candidate geometry and rankings, reject scientific changes/corruption and keep publication held until the normal runner applies a fresh screen.

- Map and export: show original survey producer credits in reef details and retain their use restrictions in waypoint, outline and offline notes. New credited publications reject incomplete notices before export; existing government-only publications remain compatible.

- Seafloor: preserve original CSUMB noncommercial use terms and producer credit in tile and canonical-export metadata; unknown rights and for-profit release remain blocked. No source or fishing location is promoted by this contract change.

- Export: compress full canonical reef boundaries for mobile transfer, preserving every coordinate and hash/current-screen checks. Bound both compressed and decoded sizes so large Morro Bay surveys can load without weakening the limits.
- Fixed: trip-alert push notifications were never deliverable on Cloudflare because the deploy did not upload the VAPID key pair. The deploy now requires `VAPID_PUBLIC_KEY` and `VAPID_PRIVATE_KEY` (GitHub secrets) and uploads them, the smoke test checks that `/api/session` serves the public key, and a Worker without keys leaves alerts pending without claiming receipts, so the first check after the keys arrive sends them (an earlier version marked them held, which is never retried). The key check runs before any Wrangler command, so a missing key stops the job without a deploy and a rollback.
- Seafloor: allow checked native sources to advance private physical mapping while publication rights remain unqualified; isolate recovery/output caches and keep public maps, exports and ledger unchanged.

- Seafloor: read original CSUMB gzip-tar grids from the reviewed NOAA archive with bounded extraction and private recovery; preserve native values and retain source-specific rights review.

- Operations: every scheduled data workflow and CI reads its runner from a repository variable (`DATA_RUNNER`, `CI_RUNNER`; default `ubuntu-latest`), and `scripts/runner/setup.sh` turns one Ubuntu box into four self-hosted runners, so the jobs cost no billed minutes once the repository is private. Costs and steps in [docs/operations/runners.md](docs/operations/runners.md).
- Seafloor: screen southern Monterey/Carmel/PointSur whole habitat outlines;904 candidates pass locally, with MPAs excluded and changed Monterey rules holding publication for review.
- Map: show current screened survey habitat automatically for reef targets, preserve manual off, color by selected species fit and show actual regional publication counts.

- Seafloor: process original Carmel/Point Sur5m surveys in three new reaches; add85.27km² selected measured footprint and836 supported habitat ranks, held privately for spatial screening.

- Seafloor: include full H11953 depth-band footprints and native 1 m nearshore detail; +13.08 km² valid coverage. Existing relative extraction changes screened outlines, with limitations documented.
- Seafloor: read original USGS ArcInfo GRID archives at native spacing with bounded extraction and checked recovery; unlock older shelf surveys without claiming new published coverage.

- Seafloor: rescreen cached Cambria and southern Conception habitat; 1,112 additional candidates pass the expanded permanent planning scope, subject to production and trip-time checks.

- Seafloor: retain native H11953 4 m/8 m depth bands; add 65.71 km² valid survey footprint near Arguello and 475 spatially screened habitat candidates, pending production verification.

- Seafloor: extend Morro and Arguello permanent planning screens; exclude the Morro entrance channel and Vandenberg Zone 4, releasing 1,880 additional habitat candidates locally pending publication.
- Export: select up to 20 distinct best available lingcod/rockfish reefs within 300 ft, display trip priorities and a documented habitat evidence percentage, and put both in chartplotter waypoint and outline names. Export full screened survey geometry with fresh revision and whole-reef checks; restore saved selections only against that same current publication. [Ranking and export process](docs/product/ranked-reef-export.md).

- Seafloor: process southern Morro and eastern Cambria native intersections; add 89.68 km² measured coverage and 601 supported ranks in three private reaches.

- Seafloor: qualify three native NOAA Point Conception depth bands; add 76.32 km² measured coverage and 979 supported habitat ranks in three private reaches, preserving 2/4/8 m spacing.

- Seafloor: verify reviewed scientific raster content across lossless GeoTIFF encodings while retaining original/cache checksums; retain exact worker failure reasons during batch aggregation.

- Operations: `/api/daily` counts only edge-cache misses against its per-IP limit, so several people behind one address (carrier NAT, a marina's Wi-Fi) are no longer refused the cached regulation and closure checks.
- Internal: the conditions score, its tuned thresholds and the go / marginal / no-go verdict now live in one module, `web/score.ts`, shared by the Tomorrow card, the meteogram, the search plans and the coming trip planner. Ratings are unchanged: a 150-case golden fixture generated from the previous code passes exactly (`tests/test_score.mjs`).
- Seafloor: qualify the native Point Buchon survey and paired substrate; add 76.98 km² measured coverage and 1,131 supported habitat ranks in two private reaches, preserving the 80 m fine-resolution boundary.

- Seafloor: process the remaining two qualified Monterey native intersections; add 27.72 km² of measured coverage and 62 ranked habitat candidates, held privately until spatial screening.

- Seafloor: qualify the original Monterey 2 m producer product and paired substrate; add three measured physical reaches with 672 ranked habitat candidates, held privately until Monterey spatial screening.

- Seafloor: process oversized native habitat windows in bounded tiles without downsampling; join habitat across tile edges and preserve reach-wide thresholds. Morro Bay r01 has measured coverage and private ranked candidates pending its spatial screen.

- Add a daily seafloor rollout planner, reusable physical-stage cache, explicit survey promotion and per-reach failure recovery; keep legal screening as the final publication stage.

- Map startup ([P4-05], first slice): with production's live MPA check, Morro Bay's map downloads 3.6 MB of JSON at startup instead of 7.3 MB (`scripts/measure_startup.mjs --stub-mpa`). The uncertainty feed and the daily fishing evidence now load when Conditions opens, and the map reads only the regulation checks (and, when the live MPA query fails, the MPA record) of the daily feed through the new `/api/daily?region=&part=` endpoint (per-IP limited, saved in offline packs), falling back to the full feed. The map, atlas and protected-area screen load in parallel behind a loading skeleton, and a bottom-left **Legend** chip explains the visible layers and marker meanings. CI budgets the committed static startup JSON (`scripts/startup-budget.json`).
- Front end ([P4-04]): the spot sheet leads with the spot's name and answer (grade label and depth), then confidence badges (Depth, Terrain, Fish: Qualified ✓ / Estimated ~ / Unknown ?) and a freshness pill for the spot's own nearshore buoy that re-judges its age every minute. Research-only targets keep a short "Research-only" marker on the answer line, write depth as "~N ft (estimated)" and open the depth badge's why. The research-only and "mapped habitat candidate" caveats moved word for word into the badges' one-tap "why" (`web/disclaimers.ts`); the target id, rank and coordinates moved under the stats and the seabed view's Relief/From above toggle sits under the image, so the Morro Bay spot sheet shows 60 words above the fold with the research-only why open (70 before, with the caveat above the name).
- Development ([P4-04]): copy lint (`node scripts/check_copy.mjs`, CI `check` job) fails on two consecutive "not" sentences and on GFS/ECMWF/MLLW/datum outside a disclosure; caveat sentences may name methods and generated region wording is not linted; the 54 existing findings are listed in `scripts/copy-lint-baseline.json`, which can only shrink (editing a listed sentence is recorded with `--update`).
- Operations: the research inventory workflow keeps its carried state after a degraded run, and NOAA BAG HEAD checks retry `429 Too Many Requests` (honouring `Retry-After`, four workers) instead of reporting a rate-limited rescan as degraded.
- Operations ([P4-11]): cookie-less client telemetry. The app counts a fixed set of funnel steps (port selected, map viewed, forecast viewed, spot saved, offline pack saved, installed) and reports uncaught errors with the page build and last request id, batched through `navigator.sendBeacon` to `POST /api/telemetry` and written to Workers Analytics Engine when `ENABLE_ANALYTICS` is on. Nothing is sent under Do Not Track or Global Privacy Control; no ids, cookies, IPs or query strings. The daily Operations report shows the funnel and top client errors ([docs/engineering/telemetry.md](docs/engineering/telemetry.md)).
- Testing ([P4-09a]): browser tests with Playwright and axe (`pnpm e2e`, CI job `e2e`) run eight flows at phone and laptop size against the built site under `wrangler dev`; serious or critical accessibility violations fail the build.
- Front end ([P4-01b]): TypeScript and Preact foundation. A signals store (`web/state.ts`) owns region, coast, view, target and hour in the URL: opening the site with a saved port, choosing the first port, and choosing a port in the region already shown no longer reload the page (the forecast hour and target are kept), and `?hour=` links open that forecast hour. The header outlook badge, the meteogram card and the offline freshness banner are Preact components; `pnpm typecheck` covers `web/`.
- Build ([P4-01a]): Vite 8 bundles the client (`vite.config.mjs`); first load of the map drops from 84 script and stylesheet requests (242 KB gzip) to 22 (169 KB). Hashed files live in `/assets/` with a year's immutable caching; pages, `/sw.js`, vendored libraries (with SRI), data and the offline precache keep their contract. `scripts/fingerprint.mjs` is retired and `check_client.mjs` checks the Vite manifest.
- Operations: optional Workers Analytics Engine metrics (repository variable `ENABLE_ANALYTICS=true`): one data point per request (route pattern, status, latency, cache), LLM call, queue batch and cron run, with no personal data; a daily **Operations report** workflow summarises the last 24 hours. A failed cron step now fails the cron invocation.
- Operations: saved-trip checks can run on Cloudflare Queues (repository variable `ENABLE_QUEUES=true`): the Worker cron queues one message per owner after each live publication, with retries and a dead-letter queue, removing the 2,500-trip ceiling. Off by default; `/api/jobs/check` stays as the manual trigger and fallback.
- Development: Python tests run under pytest in layers (`tests/unit`, `tests/contract`, `tests/integration`, `tests/gis`; claims pins in `research/tests`) with `gis`/`claims`/`network` markers, JUnit and slowest-test summaries in CI, and the full survey-science run fails on any skip outside the private-cache allowlist.
- Docs: the README is rewritten as a short product page with a screenshot, coverage list and three-command start; datum and withdrawn-claim details now live in `docs/product/data-confidence.md`. The architecture doc no longer describes ChatGPT Sites hosting.
- Docs: `docs/product/data-confidence.md` is the single reference for grades, coverage states, freshness, depth datums and withdrawn claims.
- Docs: 39 dated rollout, source-request and research logs moved to `docs/archive/` (indexed in `docs/archive/README.md`); `docs/README.md` now links the engineering, operations and legal documents.
- Worker in TypeScript with Hono ([P3-01]): `server/` is strict TypeScript (`pnpm typecheck` in CI) routed by Hono (`server/app.ts`, `server/routes/`, `server/middleware/`). Routes, statuses, headers and cookies are unchanged; every response now carries `X-Request-Id`, JSON errors repeat it as `request_id`, and `HEAD` is answered like `GET` without a body.
- Operations: the daily data job now runs and publishes product feeds only; its NOAA BAG/ENC and USGS catalog research inventories moved to `research-daily.yml` (artifacts only), the monthly research workflows are renamed `research-substrate.yml` / `research-fish-survey.yml`, and 22 research-only catalog pins moved to `research/catalog/`.
- Smaller deploy: 206 audit receipts (3.1 MB) moved from `dist/data/` to `research/receipts/` with a sha256 manifest; the app never loaded them, and they are no longer uploaded with the site.
- Repository: the ~240 dated audit, screening, triage, discovery and one-off builder scripts moved from `scripts/` to `research/scripts/` (history kept); `scripts/` now holds only the product tools that workflows, the build and deploy run.
- Docs: architecture decision records 0002 (own NOAA/ECMWF forecasts), 0003 (R2 as feed system of record), 0005 (front-end direction, proposed) and 0006 (passkey accounts; billing proposed).
- Trip alerts use your saved boat: the form's wind, gust and sea limits start from it, the boat is saved with the trip (D1 migration 0003 adds four nullable columns), and the evening-before and morning-of checks judge wind chop against that boat and name it in the alert.
- First run: harbor, then boat (four quick choices, exact boat or skip), then tomorrow's one-word answer for that harbor and boat, with the reasoning and caveats behind a "Why?" tap.
- Seafloor habitat layer (Map options → Map layers): screened Morro Bay habitat candidates from original surveys, colored by terrain grade or by lingcod / rockfish-reef physical fit, with optional survey coverage cells. Shown only while the screening publication is current; the service worker never caches it.
- Accounts: create a SkipperCast account and sign in with a passkey (Face ID, Touch ID or device PIN; no password or email) from Guide → Your account. Saved trip alerts, comfort feedback and AI boat lookup use it; you can add or remove passkeys, sign out, export your records and delete the account.
- Contracts: feeds and generated region files are validated against `schemas/` before they are written (`ContractError`, `SKIPPERCAST_VALIDATE=off` emergency switch), and region validation uses the region schema plus cross-reference checks.
- Operations: `refresh_regions.py --run-manifest` records each regional refresh (per-region and per-source status, input/output sha256, exit status) at `var/runs/refresh-<kind>/<run_id>.json`; `skippercast.report` renders a region table and `publish_r2.py var/runs runs` uploads manifests to R2 `runs/`.
- Pipeline: every source request in `src/` goes through one HTTP client (`skippercast.http.Session`: host allowlist, DNS-pinned public addresses, bounded bodies, jittered retries honouring Retry-After, receipts, optional ETag cache); the `/usr/bin/curl` TLS fallbacks are replaced by the optional `tls` extra (`truststore`).
- Offline: a service worker now keeps the app shell and the latest public data, and "Save for offline" (Guide → Offline trip pack) stores a region's data, rules, forecast and NOAA chart tiles; saved data shows an "Offline — showing data saved …" banner. Install prompt and a one-time iOS Add to Home Screen hint.
- Fixed: every Cloudflare deploy since the gated workflow was rolled back by a false smoke-test failure (curl | grep -q under pipefail).
- Operations: the `conditions` and `data` feed branches, like `forecasts`, are now one parentless commit replaced on each publish (with a lease against concurrent publishers), and each deploy sets R2 lifecycle rules (run manifests 7 days, history backstops after the pipeline's own 90/30-day retention).
- Security: the live workflow is split into `refresh` (contents write), `notify` (OIDC identity for saved-trip checks, runs beside it and cannot fail a cycle) and `next` (dispatch only) jobs, and data workflows prefer an R2-only `R2_PUBLISH_TOKEN` over the deploy token.
- Tomorrow card on the Conditions tab: for the next three days, go / marginal / no-go per two-hour window for your saved boat, the one factor that limits the day in words, GFS–ECMWF agreement as confidence and the latest comfortable back-at-dock time. Caveats sit behind a "Why?" tap.
- Performance and abuse protection: the model API, forecast/intelligence/habitat endpoints and R2 feeds are edge-cached (`X-SC-Cache`), and `/api/om` (60/min) and `/feeds/` (300/min) are rate-limited per IP on Cloudflare.
- Security: every Worker response now carries HSTS, an enumerated Content-Security-Policy (moved from the page meta tag), frame-ancestors 'none', Permissions-Policy and COOP; vendored scripts and styles are pinned with SRI.
- Operations: data retention now runs on the Cloudflare cron as well as the trip-check job; `request_limits.expires_at` is indexed (migration 0001).
- AI boat lookup: a global daily cap (`BOAT_LOOKUP_GLOBAL_DAILY_LIMIT`, default 500), a `BOAT_LOOKUP_ENABLED` kill switch, and one usage log line per lookup with billed tokens and searches.
- Worker hardening: request errors are typed (only validation failures return their message), `/api/events/ack` validates the event id, and public `/api/health` no longer discloses which bindings and secrets exist.
- Development: shared `skippercast.util` time and file-hash helpers replace duplicated copies; CI runs `ruff check src` for syntax errors and undefined names.
- Development: `pip install -e ".[survey]"` (and `ocean`, `sst`, `publish`, `test`, `seafloor`, `dev`) installs pinned optional tools; `SKIPPERCAST_ROOT` points installed code at a checkout.
- Operations: R2 upload failures now fail the live and daily jobs, each `latest.json` records `published_at` and `run_id`, publishes are verified on the public `/feeds/` route, and the freshness monitor checks that route first.
- Operations: one region's refresh error no longer blocks the others; it is recorded as `status: failed` in the regional index, and the job fails only for the default region or a majority.
- Contracts: JSON Schemas in `schemas/` for regions, catalogs, jurisdictions, the daily, live and intelligence feeds, region indexes, coverage and forecast tiles, with `python -m skippercast validate` and CI validation of every committed file.
- Operations: structured JSON logging (`skippercast.log`), run manifests (`skippercast.runs`) and `python -m skippercast.report` step summaries; the forecast tile builder logs structured records and can write a run manifest.
- Conditions: surface currents and drift guides now use NOAA WCOFS samples from the regional pipeline (about 4 km, first 72 hours) instead of the browser's Open-Meteo request; the hourly sea-temperature weather layer is removed until an own source exists, and the legacy monitor requests SkipperCast's /api/om.
- Forecast range & uncertainty: the 31-member GEFS wind ensemble is now read directly from NOAA's GEFS open data on AWS once per cycle instead of Open-Meteo's non-commercial ensemble API.
- Web app: installable icons (PNG, maskable, Apple touch), faster startup via module preloading, a friendly retry card when the app fails to start, one combined notice when several optional layers fail, and neutral boat wording instead of the owner's boat name.

- Internal: removed duplicate and unused client files (including the unused 2.3 MB og.png), renamed -vN modules to canonical names, and made check_web.py reject -vN names in dist/.
- Internal: design tokens (colour, type, spacing, radius, elevation, z-scale, motion; light and inactive dark) in dist/tokens.css with a CI contrast check; screens are unchanged.

- Legal: a data-rights register records, for every source and runtime service, whether a paid product may use it; a CI gate fails if a new asset depends on a source not cleared for commercial use. See [data-rights register](docs/legal/data-rights-register.md).
- Draft terms of use, privacy notice and licences pages (pending review by counsel), linked from About, the Guide and Sources.
- Contributing: outside contributors must sign off commits (Developer Certificate of Origin), checked on every pull request; licensing options are laid out for the owner in [ADR 0004](docs/engineering/adr/0004-licensing.md).
- Governance: issue templates, CODEOWNERS, weekly Dependabot updates, a security policy, a production dependency audit in CI, and CI actions pinned to commit SHAs.
- CI: scheduled data and survey workflows run third-party actions pinned to commit SHAs.
- Operations: runbooks for a stale feed, an R2 outage, a D1 restore and secret rotation, plus an incident-response process; the stale-feed issue now links its runbook. See [incident response](docs/operations/incident-response.md).
- Conditions: a 7-day meteogram (wind and gust, seas, tide, hourly score band, model disagreement, now marker, provisional hatch after 72 h) opens the view; tap, drag or arrow keys pick the hour shared with the scrubber.
- Rules card: a first row now shows Open/Closed (or Check rules), bag, size, depth where the reviewed rules state it, the verified date and one official link; the full detail stays below.
- Security: the Cloudflare Worker no longer trusts ChatGPT identity headers; private features there return 401 until SkipperCast has its own sign-in.
- Fixed: trip-alert push notifications could never be enabled because the build renamed the service worker away from `/sw.js`.
- Seafloor runner setup now installs the schema validator and checks the manifest before processing or publishing.

- Tuna search overlays use the regional offshore footprint, reject uniform water and stale frames, support uncertainty-screened satellite fronts, and explain species-aware 1–3 search priorities separately from boat comfort.
- Boat profile: enter your boat (optionally looked up with AI and confirmed) and comfort and drift-control ratings scale to its length, weight, hull and layout. See [boat profile](docs/boat-profile.md).
- Search plans for five Central Coast preview regions now include their surveyed habitat footprints (575 in total); they had been built before those inputs existed.
- Map engine test pages (`/map-test.html`, `/map-test-leaflet.html`) compare MapLibre with PMTiles vector tiles against today's Leaflet map on one layer. See [map engine test](docs/archive/map-engine-test.md).

### Internal

- Give the seafloor planner an explicit acquisition action when no new reach is selected, while preserving freshness work and unverified growth. Shorten the mapping skill and retain detailed source/release recipes and historical evidence in linked references.

- Release process: version tags publish GitHub Releases whose notes are the matching CHANGELOG section; see [release process](docs/operations/release-process.md).
- Seafloor runner setup now installs the schema validator and checks the manifest before processing or publishing.
- Seafloor publication: regional PMTiles, private survey recovery and a scheduled main-only workflow with checksum, restriction-expiry and public HTTP Range checks. The first Morro Bay archive contains 1,006 screened candidates; live acceptance follows a successful post-merge dispatch.
- Seafloor spatial screening: current CDFW, NOAA federal-area and reviewed security boundaries now qualify whole habitat polygons for tier 2. Missing, stale, changed or overlapping evidence stays held; publication follows separately.
- Seafloor habitat: reusable original-substrate joins, rough-bottom extraction, A/B/C terrain grades and source-cited 1–3 species planning fits. Three Morro Bay reaches now have private review outputs, including a real survey seam; legal screening still gates publication and export.
- Seafloor coverage: original-survey footprints now qualify planning cells and produce mask-aware terrain summaries for the first Morro Bay reaches. The ledger separates classified-cell area from actual selected survey area; habitat publication remains pending.
- Seafloor ingestion: reusable USGS GeoTIFF and regular NOAA BAG adapters, hash-verified private caching and native-resolution drafts. Two survey windows are qualified for processing; habitat coverage totals remain unchanged.
- Seafloor pipeline: reproducible Central Coast reach/grid baseline and a coverage-ledger CLI. All new tiers remain unprocessed until original surveys are ingested; the reference band is explicitly provisional. See [seafloor pipeline](docs/seafloor.md).
- Published feeds (live conditions, daily data, forecast tiles) now load through the site's `/feeds/` route, ready to be served from Cloudflare R2; the site can deploy to its own Cloudflare account. See [Cloudflare](docs/cloudflare.md).
- The live conditions feed is monitored hourly and reports when it stops refreshing.
- Hosting: SkipperCast runs only on its own Cloudflare Worker; ChatGPT Sites packaging, its origin and its identity headers are gone, `CUSTOM_DOMAINS` attaches skippercast.com and www.skippercast.com as custom domains (www redirects to the apex), and workers.dev stays on as staging.

## 0.3.0 — 2026-09-20

- Mobile-first map with Map, Spots, Forecast, and Guide navigation; no long page scroll to reach the map or weather.
- Compact spot cards expand into accessible detail sheets with persistent map and GPX actions; wide screens retain a docked list and detail panel.
- Collapsible filters, a reset action, 44-pixel map-marker hit areas, safe-area spacing, and readable mobile forecast comparisons.
- Direct single-spot GPX downloads for mobile and embedded browsers, with reproducible generation and checks for all 132 files.

## 0.2.1 — 2026-09-20

- Visible A/B/C terrain-grade definitions and practical context for points, reef outlines, and drift alignments.
- Per-target explanations of all four grading factors, weighted points, and capped contributions.
- Dated AIS evidence summary with eight sampled archive dates, source URLs, counts, hashes, and explicit lack of verified local sportfishing-charter tracks.

## 0.2.0 — 2026-09-20

- Public browser map with target search, habitat grades, depth filters, reef outlines, and optional drift alignments.
- Notes and GPX export for each selected target, plus the complete reviewed atlas downloads.
- On-demand ECMWF and NOAA wind/wave comparisons at three offshore samples, with missing-data, disagreement, coverage, and freshness notices.
- Model metadata, NWS advisory lookup, source attribution, and links to current rules and entrance information.
- Browser forecast and GPX tests, asset consistency checks, and vendored Leaflet with its license.

The app displays evidence for review; automated trip qualification and alert delivery remain separate integrations.

## 0.1.0 — 2026-09-20

Initial public research release:

- Portable forecast collector and alert lifecycle logic, with explicit operator-review boundaries.
- Public USGS-derived atlas: 132 habitat candidates, 107 outlines, 31 optional drift alignments.
- Reproducible GPX, GeoJSON, and offline notes from the included public data.
- Personal-use source license and separate third-party source notices.
- Offline tests, CI, contributor guide, and onboarding documentation.

The existing personal forecast deployment and full private research atlas are not migrated or replaced by this release. This initial research release did not include a hosted application.
