# Client form labels, keyboard hints, and autofill

| Scope | `<input>` | `<select>` | `<textarea>` | Total |
| --- | ---: | ---: | ---: | ---: |
| Non-admin `web` and `packages` TS/TSX | 58 | 28 | 2 | 88 |
| Admin-only declarations in the same roots (excluded from field inventory) | 41 | 27 | 3 | 71 |
| Additional first-party `dist` templates/pages | 16 | 7 | 1 | 24 |
| Non-admin declarations inventoried below | 74 | 35 | 3 | 112 |

Source snapshot: locally staged `origin/main` at `9e078e2bd4c2db659e0f6e175c33cd6b0fd18553`, identical to the card baseline (offline read, 2026-11-21). Of the 112, two are retained templates with no production caller found (listed below); the rest include conditional, shared and standalone controls, not 110 simultaneous DOM nodes. No confirmed missing programmatic label in the non-admin inventory; one coordinate declaration uses a text-only keyboard hint across four field uses. See R2 for the distinction between a programmatic name and a persistent visible label.

**Counting rules.** The uncommitted workspace script `count-forms.py` reads tracked blobs at the pinned ref. For `.ts` and `.tsx` in `web` and `packages`, it matches the lower-case opening tag names `input`, `textarea`, and `select` only when followed by whitespace or the end of an opening tag. It excludes single-line comment hits (e.g. `web/ui/Dock.tsx:3`), JSX components such as `<Select>`, and counts separate tags even on the same line. It includes literal HTML inside TS templates, counts each loop/helper declaration once, and does not evaluate browser state. Manual inspection resolves callers, linked labels, repeated fields and status targets. Admin means `web/admin/` and the admin-only controls in `web/app/views/FleetAdmin.tsx:33,49`; the checkbox primitive there is shared with the public Fleet view (`web/app/views/Fleet.tsx:47–52,81`) and counted only on the non-admin side. A second pass adds the five first-party `dist` files below, not vendor code or duplicate built output. Buttons, datalists, progress indicators and non-client developer diagnostics are not form inputs in this count.

Reproduce the source candidates from the pinned checkout:

```sh
git grep -nE -e '<input[ />]' -e '<textarea[ />]' -e '<select[ />]' -- web packages
git grep -inE 'autocomplete=|inputmode' -- web packages
git grep -nE 'aria-(describedby|invalid|errormessage)|setCustomValidity' -- web packages
git grep -lE -e '<input[ />]' -e '<textarea[ />]' -e '<select[ />]' -- dist ':!dist/vendor'
git grep -nE 'createElement|contenteditable|[Hh]yperscript' -- web packages dist ':!dist/vendor'
```

The case-insensitive hint search yields 15 lines in `web`/`packages` (one is the admin invite **form** default, `web/admin/skippers.tsx:102`; the others are field lines). The TS/TSX tally is 99 native `<input>` declarations across both audiences, not the brief's approximate 89. `web/startup-forms.ts:1–12` describes startup assets, not form markup. `web/spot-watch-form.ts:13–52` validates a model; `git grep -nE 'watchFormBody|formUnchanged' -- web packages dist` finds no consuming UI. `web/boat-entry.ts:19–36` feeds FirstRun, and `web/account.ts:96–116,156–159` opens the account and exact-boat templates in `dist`.

## R1 and R3. Field inventory and validation

The label, type, hints and value columns answer R1. The last column in each table answers R3. **L** = native label element (explicit `for`/ID or wrapping); **A** = `aria-label`; **A + L** = both present (`aria-label` supplies the name). Names are English or described by their dynamic source; translated markup uses the English copy as a reference, not a hard-coded label. **—** in the two hint columns means no explicit value, not a claim about what a browser chooses. **None** in the last column means no field-linked error or hint through `aria-describedby`, `aria-invalid` or `aria-errormessage`; native constraints and separate messages are still noted where present. **Desc** means `aria-describedby`, and **Invalid** means dynamically set `aria-invalid`. No public control had an `aria-labelledby` name or `aria-errormessage` in this inventory; either attribute on a container is not a label or error association for its children.

### Landing, account entry points, and map controls

| Control source | Type | Label and source | Autocomplete | Inputmode | Value held | R3: description, error, or validation |
| --- | --- | --- | --- | --- | --- | --- |
| `web/landing/PortInput.tsx:83` (landing and map dialog) | search | L: Where are you launching? (`:40–41,81`; `web/strings.en.generated.json:783`); overridable | `off` | — | Location query | Desc: port/location note `:108`; loading/no results and device failures are separate live feedback `:87–102`. |
| `web/landing/RegionPicker.tsx:15` | select | L: California region `:14` | — | — | Region ID (location) | Desc: dated snapshot `:18`; stale-data status is separate `:19`. |
| `web/app/CommandBar.tsx:81` | search | A: Find a target; same placeholder | — | — | Species/target text filter | None; filters options, not a submitted value (`:75–92`). |
| `web/app/CommandBar.tsx:84` | select | L: Target `:83` | — | — | Target ID | None; offers grouped available and disabled options `:84–92`. |
| `web/app/CommandBar.tsx:102` | select | L: Area `:101` | — | — | Area ID (location) | None; blank clears area `:102–105`. |
| `web/app/CommandBar.tsx:139` | text (default, read-only) | A: Link to copy | — | — | Share URL | None; copy fallback, not URL entry `:125–139`. |
| `web/brief/TideStationControl.tsx:50` | select | L: Prediction station | — | — | Station ID (location) | None; separate status for lookups, empty results and errors `:41–73`. |
| `web/app/LayerRail.tsx:66` | select | L: Source `:64–65` | — | — | Currents source ID | None; retained unsupported choice named in options `:56–70`. Also used in Conditions. |
| `web/app/LayerRail.tsx:78` | checkbox | L: Commercial AIS layer label `:74–80` | — | — | Layer enabled | None. |
| `web/app/LayerRail.tsx:97` | checkbox | L: Fleet events/tracks/heat · admin (`:87–99`; access-gated variants of the map rail) | — | — | Layer enabled per activity | None. |
| `web/app/LayerRail.tsx:109` | checkbox | L: Water & channels; Depth contours · adapt to view; Fixed depth colours; Source coverage; Reefs & species pins (`:154–183`) | — | — | Layer or display mode enabled | None; disabled in unavailable states `:109,156–181`. |
| `web/app/LayerRail.tsx:122` | range | L: Seabed relief; Water opacity; Sun direction; Land (with value readout, `:115–125,162–178`) | — | — | Number: exaggeration, opacity, degrees, photo mix | None; native bounds/step and `aria-valuetext`, not error text. |
| `web/app/LayerRail.tsx:212` | select | L: Grade `:211` | — | — | Grade filter | Desc: grade explanation `:207–219`; not an error. |
| `web/app/LayerRail.tsx:229` | select | L: Base `:228` | — | — | Basemap ID | Desc: optional base/availability note `:225–242`; disabled when Chart not drawn. |
| `web/app/LayerRail.tsx:251` | select | L: Look for `:250` | — | — | Target ID | None; unsupported options disabled `:251–258`. |
| `web/app/Legend.tsx:363` | checkbox | L: saved-spots legend entry | — | — | Saved-spots layer enabled | None; availability controls disabled state `:358–365`. |
| `web/app/views/FleetAdmin.tsx:23` | checkbox | L: dynamic; Show charter grounds and Commercial AIS on Fleet (`web/app/views/Fleet.tsx:47–52`); shared admin variants (`:56–63` in FleetAdmin) | — | — | Fleet overlay/filter enabled | None. |
| `web/ui/Dock.tsx:26` | range | A: Hour (desktop `web/app/TimeDock.tsx:155–157`, phone `web/app/Mobile.tsx:97–109`) | — | — | Time via forecast-hour index | None; range bounds, disabled state and local time in `aria-valuetext`, not an error. |

### Boat entry, personal limits, port and trip alerts

| Control source | Type | Label and source | Autocomplete | Inputmode | Value held | R3: description, error, or validation |
| --- | --- | --- | --- | --- | --- | --- |
| `web/app/FirstRun.tsx:75` | number | L: Boat length (ft); Wind limit (kt); Seas limit (ft), from `web/boat-entry.ts:19–36` | — | `decimal` | Three optional numbers | None individually; fieldset links hints at `:69–79`. Length outside 8–70 ft is skipped; wind/seas can round or clamp; general save notice after close (`web/boat-entry.ts:55–58,89–113`; `FirstRun.tsx:110–118`). |
| `web/app/LimitsPanel.tsx:86` | number | L: Highest sustained wind (kt); Highest gust (kt); Highest seas or surf (ft), `:39–42,81–88` | — | `decimal` | Three profile limits | Desc: each default and bounds, plus conditional low-gust note for gust `:87–92`; native required/bounds/step. |
| `web/app/LimitsPanel.tsx:96` | select | L: Highest surge | — | — | Surge band | Desc: default band `:95–99`. |
| `web/app/LimitsPanel.tsx:105` | number | L: Cruise speed (kt) | — | `decimal` | Speed | Desc: range, no default, blank clears `:104–107`; native bounds/step. |
| `web/app/LimitsPanel.tsx:112` | number | L: Hours I want to fish | — | `decimal` | Duration | Desc: 1–12 hours, example and blank clears `:111–114`; native bounds/step. |
| `web/app/LimitsPanel.tsx:119` | number | L: Range to consider (nm, one way) | — | `decimal` | Distance | Desc: bounds, harbor/launch origin and blank clears `:118–121`; native bounds/step. |
| `web/app/LimitsPanel.tsx:127` | select | L: Launch from | — | — | Launch ID or harbor (location) | Desc: listed launches and distance origin `:126–131`. |
| `web/app/LimitsPanel.tsx:138` | number | L: Deepest dive (ft) | — | `numeric` | Depth | Desc: default and range `:137–140`; native bounds/step. |
| `web/app/LimitsPanel.tsx:144` | select | L: Diving from | — | — | Shore/boat/unset | None. |
| `web/app/LimitsPanel.tsx:153` | number | L: Farthest swim from shore (yd) | — | `numeric` | Distance | Desc: range and blank behavior `:152–155`; native bounds/step. |
| `web/app/PortAlert.tsx:48` | number | L: Wind limit (kt) | — | — | Wind threshold | None; required 1–60, step 1; shared invalid status `:31–38,53`. |
| `web/app/PortAlert.tsx:49` | number | L: Swell limit (ft) | — | — | Swell threshold | None; required 0.5–30, step 0.5; same status. |
| `web/app/TripAlerts.tsx:442` | select | L: Alert species `:441` | — | — | Species ID | None; invalid species or point goes to shared `#alert-status` `:335–342,482`. |
| `web/app/TripAlerts.tsx:457` | date | L: Trip date | — | — | Local trip date | None; required with dynamic min/max; save failures go to `#alert-status` `:335–350,482`. |
| `web/app/TripAlerts.tsx:458` | select | L: Area | — | — | Forecast point ID (location) | None; required with a seed; shared choose-area/species status as above. |
| `web/app/TripAlerts.tsx:459` | number | L: From · local hour | — | — | Start hour | None; required 0–22; shared save status. |
| `web/app/TripAlerts.tsx:460` | number | L: Until · local hour | — | — | End hour | None; required 1–23; shared save status, including rejected hour ordering (`web/alerts.ts:91`; `web/app/TripAlerts.tsx:335–342,482`). |
| `web/app/TripAlerts.tsx:461` | number | L: Wind limit · kt | — | — | Wind threshold | None; required 1–30; shared save status. |
| `web/app/TripAlerts.tsx:462` | number | L: Gust limit · kt | — | — | Gust threshold | None; required 1–40; shared save status. |
| `web/app/TripAlerts.tsx:463` | number | L: Sea limit · ft | — | — | Sea threshold | None; required 0.5–10, step 0.5; shared save status. |
| `web/app/TripAlerts.tsx:513` | select | L: Part of trip | — | — | Outbound/fishing/return | None; shared submission status `:398–410,517`. |
| `web/app/TripAlerts.tsx:514` | number | L: Comfort · 1 rough to 10 excellent | — | — | Comfort rating | None; required 1–10; same shared status. |
| `dist/boat-profile.js:42` | text | L: Make, model and year `:41` | `off` | — | Boat model query | None; max 120, lookup checks 3 trimmed characters; lookup/account/failure status `:44,83–114`. |
| `dist/boat-profile.js:48` | number | L: Length overall (ft); Beam (ft); Loaded weight (lb); Deadrise at transom (°); Cruise speed (kn); conditional AI estimate in label (`:8–14,47–49`) | — | `decimal` | Five boat measurements | None; markup min/step, but Save is a button reading `FormData` `:55–67,117–125`. Normalizer applies bounds (`dist/boat-handling.js:31–49`); missing/invalid length blocks save in shared status; optional invalid numbers may be discarded. |
| `dist/boat-profile.js:50` | select | L: Hull; conditional AI estimate `:50–51` | — | — | Hull category | None; blank can be inferred from deadrise (`dist/boat-handling.js:44–48`). |
| `dist/boat-profile.js:52` | select | L: Layout; conditional AI estimate `:52–53` | — | — | Layout category | None; optional known category (`dist/boat-handling.js:44–45`). |

Limits' form-level note and saved/default status (`web/app/LimitsPanel.tsx:79–80,160–162`) do not mark individual inputs invalid. The two alert forms' shared statuses likewise don't identify which input the user should fix.

### Planner

| Control source | Type | Label and source | Autocomplete | Inputmode | Value held | R3: description, error, or validation |
| --- | --- | --- | --- | --- | --- | --- |
| `web/app/Planner.tsx:66` | checkbox | L: spot row text, including name/ID and available evidence (`:60–75`) | — | — | Include result/spot | None. |
| `web/app/Planner.tsx:142` | text (default) | L: Boat | — | — | Boat name/text | None; native length cap and conditional field status inside label (`:133–147`; `web/float-plan.ts:48–62`). |
| `web/app/Planner.tsx:143` | number | L: People aboard | — | — | Headcount | None; native 1–999 step 1 and conditional status inside label. |
| `web/app/Planner.tsx:144` | time | L: Departure | — | — | Local departure time | None; invalid date/zone/time or DST gap handled by model; conditional status inside label. |
| `web/app/Planner.tsx:145` | time | L: Be back by | — | — | Local return time | None; local time checks including return after departure; conditional status inside label. |
| `web/app/Planner.tsx:147` | textarea | L: If overdue | — | — | Free text instructions | None; native length cap, conditional status **outside** label. |
| `web/app/Planner.tsx:230` | text (default) | L: Plan name | — | — | Plan name | None; max 80. |
| `web/app/Planner.tsx:231` | date | L: Fishing date | — | — | Local date | None; date participates in timing, no markup min/max/required. |
| `web/app/Planner.tsx:232` | time | L: Leave port at | — | — | Local time (minute steps) | None; grouped time/duration status `:203–209,235`. |
| `web/app/Planner.tsx:233` | number | L: Minutes fishing at each stop | — | — | Whole minutes | None; native bounds 0–600 and grouped time/duration status (`:235`; `web/trip-times.ts:9–22`). |
| `web/app/Planner.tsx:271` | select | L: Target | — | — | Species group | None; filter changes invalidate ranking (`web/planner.ts:447–460`). |
| `web/app/Planner.tsx:273` | select | L: Maximum spots | — | — | Count from fixed choices | None; same filter behavior. |
| `web/app/Planner.tsx:275` | number | L: Maximum depth (ft) | — | — | Depth | None; native 25–300; ranking checks bounds (`dist/spot-ranking.js:42–63`). |
| `web/app/Planner.tsx:276` | select | L: Search area | — | — | Region/map scope | None; same filter behavior. |
| `web/app/Planner.tsx:278` | select | L: From port | — | — | Port ID (location) | None; blank disables distance constraint (`dist/spot-ranking.js:42–63`). |
| `web/app/Planner.tsx:280` | number | L: Maximum one-way distance (nm) | — | — | Distance | None; native 1–100; ranking checks positive finite distance, not native ceiling (`dist/spot-ranking.js:42–63`). |
| `web/app/Planner.tsx:290` | checkbox | L: Research-coordinate export · opt in (with explanation) | — | — | Session export opt-in | None; separate export readiness `:351–375`. |
| `web/app/Planner.tsx:298` | search | L: Find a spot | `off` | — | Name/ID/grade query | None; live filtering. |
| `web/app/Planner.tsx:319` | text (default) | L: Waypoint name | — | — | Saved waypoint name | None; required, max 80; model rechecks blank name and save eligibility (`web/planner.ts:390–406`). |
| `web/app/Planner.tsx:320` | select | L: Category | — | — | Waypoint category | None; same save gate checks category. |
| `web/app/Planner.tsx:324` | checkbox | L: Saved waypoint name · category | — | — | Include waypoint | None. |
| `web/app/Planner.tsx:334` | checkbox | L: Include launch ramp: {name} | — | — | Include launch | None; shared export readiness `:351–375`. |
| `web/app/Planner.tsx:336` | checkbox | L: Fishing waypoints; Linked reef outlines; Structure alignment lines; Protected-area outlines (with descriptions `:331–339`) | — | — | Include layer per option | None; same export readiness. |
| `web/app/Planner.tsx:339` | checkbox | L: Depth contour tracks (with description) | — | — | Include contours | None; same export readiness. |
| `web/app/Planner.tsx:341` | select | L: Protected-area coverage | — | — | Map or region scope | None; same export readiness. |
| `web/app/Planner.tsx:378` | select | L: Your chartplotter | — | — | Device choice | None; adjacent model help `:376–384`. |

Float-plan status inside a wrapping label is not an explicit error association and can change the computed name when it appears (`web/app/Planner.tsx:133–147`). Export readiness (`#export-validation`) is shared; the help linkages at `web/app/Planner.tsx:361–362` are on action buttons, not the fields.

### Account, catch log, and saved spots

| Control source | Type | Label and source | Autocomplete | Inputmode | Value held | R3: description, error, or validation |
| --- | --- | --- | --- | --- | --- | --- |
| `dist/account.js:700` | text | L: Name (optional, shown only to you) `:699` | `username webauthn` | — | Optional account display name / passkey surface | None; max 60; sign-up/sign-in errors use general status `:879–939`. |
| `dist/account.js:585` | datetime-local | L: When | — | — | Local start date/time | None; blank on create means now, rejected on edit; shared log status `:455–498,606,996–1029`. |
| `dist/account.js:586` | datetime-local | L: End time (optional) | — | — | Local end date/time | None; bad parse/shared status; route rejects end before start (`server/routes/catch-log.ts:24–59`). |
| `dist/account.js:587` | select | L: What happened | — | — | Blank/fish/unknown | None; decides count requirement (`server/routes/catch-log.ts:47–54`). |
| `dist/account.js:588` | number | L: Fish count | — | — | Whole count | None; native 1–9999 step 1, not required in markup; fish entry needs a positive count at server, with failure reported through shared log status (`server/routes/catch-log.ts:50–54`; `dist/account.js:1087–1097`). |
| `dist/account.js:589` | text | L: Target species | — | — | Species text | None; max 60, optional suggestions (not an allowlist) `:522–533,957–964`. |
| `dist/account.js:590` | text | L: Method | — | — | Fishing method text | None; max 40. |
| `dist/account.js:591` | select | L: Trip (optional) | — | — | Saved trip ID | None; unavailable choices have a fallback; ownership validated by route (`:510–520,982–987`; `server/routes/catch-log.ts:58,102–125`). |
| `dist/account.js:592` | select | L: At a saved spot (optional) | — | — | Spot used to fill coordinates | None; hidden without usable spots `:535–578`; no validation link. |
| `dist/account.js:366,593–594` | text | L: Latitude / Longitude (optional, private) | `off` | `text` | Two location strings, DD/DDM/DMS | Desc: format example, inline error, device-position status. Invalid: parser failure/missing counterpart on create (`:372–389,417–427,455–498,1087–1097`); a half-pair on edit can instead receive a shared server error (`:1007–1029`; `server/routes/catch-log.ts:37–44`). |
| `dist/account.js:596` | text | L: Note | — | — | Catch-log note | None; max 1,000. |
| `dist/account.js:599` | select | L: Show | — | — | Outcome filter | None; separate match/no-match status (`:320–349,601`). |
| `dist/account.js:600` | select | L: Species | — | — | Species filter | None; same status. |
| `dist/account.js:687` | text | L: Name | — | — | Saved-spot name | None; max 80; blank accepted (`server/routes/spots.ts:13–24`). |
| `dist/account.js:366,688–689` | text | L: Latitude / Longitude | `off` | `text` | Two location strings, DD/DDM/DMS | Desc and Invalid as for log above; required by parser, not markup. Parser/route failures are distinct (`:645–646,1180–1189`; `server/routes/spots.ts:17–24`). |
| `dist/account.js:691` | text | L: Private note | — | — | Saved-spot note | None; max 1,000; general save status `:1180–1189`. |
| `dist/account.js:625` | text | L: Name | — | — | Edited spot name | None; max 80; save refusal in row status `:1129–1153`. |
| `dist/account.js:628` | textarea | L: Private note | — | — | Edited spot note | None; no markup max; server limit of 1,000 code points (`server/routes/spots.ts:13–24,45–55`); refusal in row status `dist/account.js:1139–1153`. |

### Advisor, downloads, and retained home-port template

| Control source | Type | Label and source | Autocomplete | Inputmode | Value held | R3: description, error, or validation |
| --- | --- | --- | --- | --- | --- | --- |
| `web/advisor/chat.tsx:136` | textarea | L: Message (visually hidden, `:135`; `dist/advisor/chat.css:89–93`); visible placeholder Type a message | — | — | Chat text | None; max 2,000; send failures and limits go to shared chat status `:28–33,78–99,125–127`; copy at `web/advisor/copy.ts:51–65`. |
| `web/advisor/chat.tsx:141` | file | L: Add a photo (`:139–142`) | — | — | Image attachment | None; image accept filter, shared photo size/type/upload status `:55–75,125–127`. |
| `dist/upload.html:26` | file | L: Choose a file (`:24–27`; `dist/advisor/upload.js:22`; `web/advisor/copy.ts:13`) | — | — | Image or video | None; accept filter; missing, too large, unsupported or failed upload appears in shared status (`dist/advisor/upload.js:26–29,44–61,79–99`). Advisor link, not admin (`server/routes/advisor.ts:252–253`). |
| `dist/downloads/spot-notes.html:7` | search | L: Filter by ID, priority, depth, area, or note | — | — | Download-table query | None; filter only (producer `src/skippercast/atlas/export.py:282–286`; linked in `web/app/AccountMenu.tsx:169`). |
| `dist/home-port.js:91` (retained, not counted as mounted) | search | L: Find a home port `:90` | `off` | — | Location query | None; separate no-match/device feedback `:101–158`; only declaration of initializer found via `git grep -n 'initHomePort' -- dist web packages`. |

### Coast package, including standalone controls

Native terrain panels are detached in host-chrome mode (`packages/coast/src/embed.ts:50–66`; `web/map/stage.ts:523–524`), so the standalone terrain declarations below are not duplicate map-app fields. Managed reports likewise omit the standalone report selectors (`packages/coast/src/coast3d/report.ts:65–75,82–89`).

| Control source | Type | Label and source | Autocomplete | Inputmode | Value held | R3: description, error, or validation |
| --- | --- | --- | --- | --- | --- | --- |
| `packages/coast/src/embed-template.ts:7` (`location`) | select | L: Explore a coastal location (visually hidden) | — | — | Coastal location ID | None. |
| `packages/coast/src/embed-template.ts:8` (`species`) | select | L: Target species | — | — | Species ID | None. |
| `packages/coast/src/embed-template.ts:8` (`water`) | checkbox | L: Water & channels | — | — | Water layer enabled | None. |
| `packages/coast/src/embed-template.ts:8` (`water-opacity`) | range | L: Water transparency | — | — | Number: opacity fraction | None; native 0–0.8 step 0.05; adjacent illustrative-water note. |
| `packages/coast/src/embed-template.ts:8` (`contours`) | checkbox | L: Depth contours | — | — | Contours enabled | None. |
| `packages/coast/src/embed-template.ts:8` (`habitat`) | checkbox | L: Reefs & species pins | — | — | Habitat pins enabled | None. |
| `packages/coast/src/embed-template.ts:8` (`source-coverage`) | checkbox | L: Source coverage | — | — | Coverage layer enabled | None. |
| `packages/coast/src/embed-template.ts:8` (`currents`) | checkbox | L: Surface currents | — | — | Currents enabled | None; adjacent observations status. |
| `packages/coast/src/embed-template.ts:8` (`relief`) | range | L: Seabed relief plus readout | — | — | Number: exaggeration multiplier | None; native 1–12 step 1. |
| `packages/coast/src/embed-template.ts:8` (`sun-azimuth`) | range | L: Sun direction plus readout | — | — | Degrees | None; native 0–360 step 5; nearby lighting note. |
| `packages/coast/src/embed-template.ts:8` (`photo-mix`) | range | L: Land plus readout | — | — | Number: photo blend fraction | None; native 0–1 step 0.05. |
| `packages/coast/src/embed-template.ts:8` (`fixed-ramp`) | checkbox | L: Fixed depth colours | — | — | Fixed shading scale enabled | None; nearby shading status. |
| `packages/coast/src/embed-template.ts:8` (`depth-limit`) | range | L: Maximum habitat depth plus readout | — | — | Depth (ft) | None; native 50–300 step 5. |
| `packages/coast/src/coast3d/report.ts:69` (`report-mode`) | select | A: Fishing method | — | — | Boat/shore/spear | None. |
| `packages/coast/src/coast3d/report.ts:69` (`report-day`) | select | A: Report day | — | — | Forecast date | None; choices from report. |
| `packages/coast/src/coast3d/report.ts:69` (`coast-hour`) | range | A + L: Selected forecast hour; visible label is local time or No supported forecast hour | — | — | Time via forecast-hour index | None; native bounds, disabled when empty, absent index ignored `:73–75`. |
| `packages/coast/src/coast3d/report.ts:84` (`panel-area`) | select | A: SLO report area | — | — | Area ID (location) | None; accepted values come from report area list `:84–89`. |
| `packages/coast/src/ui/history.ts:43` (`history-station`) | select | L: Station | — | — | Station ID (location) | None; data-backed options. |
| `packages/coast/src/ui/history.ts:43` (`history-metric`) | select | L: Measurement | — | — | Measurement ID | None; unavailable metrics identified in option text. |
| `packages/coast/src/ui/briefing.ts:34` (`hour-slider`, no production caller found) | range | A: Forecast hour | — | — | Time via forecast-hour index | None; native bounds, disabled when empty, `aria-valuetext` holds local hour. Recheck via `git grep -nE 'timeline\(|ui/briefing' -- web packages dist ':!dist/vendor'`. |

The existing axe summary reads saved violation and incomplete results; it isn't an inventory of mounts, help text, keyboard layouts or autofill (`e2e/axe-summary.ts:11–23`; `e2e/fixtures.ts:249–260`). No browser/device results are claimed here.

## R2. Findings ranked by likely user impact

1. **Missing programmatic labels: none confirmed in the scoped non-admin source.** The nearest visible-label gaps are Find a target (`web/app/CommandBar.tsx:81`, named with `aria-label`) and Message (`web/advisor/chat.tsx:135–136`, a visually hidden real label). Their on-screen placeholders disappear after typing. Placeholders on PortInput, Planner and the exact-boat query supplement real labels; they aren't the sole name (`web/landing/PortInput.tsx:81–83`, `web/app/Planner.tsx:298`, `dist/boat-profile.js:41–42`).
2. **Numeric-looking text: four field uses, one shared declaration.** Catch-log and saved-spot latitude/longitude specify `inputmode="text"`, not a numeric hint (`dist/account.js:366,593–594,688–689`). Expect more keyboard switching for decimal entry on some phones (estimate, not measured). The text mode is not simply an omission: the parser deliberately accepts decimal, degrees/minutes and degrees/minutes/seconds, including signs, letters and punctuation (`dist/coordinates.js:25–69`). A digits-only keyboard can make supported formats harder to enter. No other free-entry numeric-only field in the tables lacks both `type=number` and a numeric hint. Not counted as numeric typing: sliders, fixed-choice counts, native date/time fields, or the mixed-text make/model/year query. Lower-priority device checks (estimate): 13 `type=number` declarations have no explicit inputmode — four Planner values (`web/app/Planner.tsx:143,233,275,280`), two port thresholds (`web/app/PortAlert.tsx:48–49`), five trip-alert numbers and one comfort rating (`web/app/TripAlerts.tsx:459–463,514`), and fish count (`dist/account.js:588`). In particular, try entering fractional swell/sea first; don't assume a particular device keyboard from markup alone.
3. **Standard autofill: one clear identity surface, already hinted.** The passkey/account field uses `username webauthn` (`dist/account.js:699–703,879–939`). A personal `name` token would be defensible only if a distinct field is intended to collect the user's full name; an optional display name on this passkey surface is not evidence for replacing the existing tokens. No clear missing standard personal-data token on other non-admin fields: port/region/coordinates aren't postal address fields, boat/waypoint/plan names aren't a person's name, trip dates aren't birthdays, and a read-only share link isn't an entered profile URL (R1). `off` already appears on PortInput, Planner search, boat lookup, account coordinates and retained home-port search. Target search and chat have no explicit setting; whether to suppress browser suggestions is separate from adding a standard personal-data token. Admin forms were not audited for token recommendations; for example the explicit invite-phone `off` is on an operator-entered contact, not the operator's own phone (`web/admin/skippers.tsx:102–106`).

## R4. One proposed follow-up, not implemented

**Link the trip-window ordering error to the two hour inputs** (estimate: 75–105 minutes). Reserve `web/app/TripAlerts.tsx` and `e2e/trip-alert-save-pending.spec.ts` in a separate unit. Use the existing order failure from `web/alerts.ts:91` and the existing localized copy; when that failure is current, associate the explanation with From/Until and mark those fields invalid. Clear the associations when the error is corrected; keep request failures in general status, not on the hour fields. No changes to bounds, acceptance, copy policy, or notifications. Offline acceptance: extend the existing mocked reversed-hours case (`e2e/trip-alert-save-pending.spec.ts:73–87`). Assert both hour controls expose the same explanation and no save request is sent for the invalid pair; edit to a valid pair, assert the error association clears and the stubbed save proceeds. Run only the focused spec on a local server with stubbed APIs and no external requests. This is a proposal, not a test result.
