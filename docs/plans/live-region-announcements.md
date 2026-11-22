# Client live-region announcements

| Finding | Source evidence |
|---|---|
| The map announces several refusals and failures, but has no general “feed loaded” or “new hour ready” message. | `web/brief/Brief.tsx:707–717,767–781,795–818`; `web/ui/Dock.tsx:66`; `web/app/Mobile.tsx:108`. |
| Saving a mark, copying a share link and finishing a route boundary check have result regions; a populated Planner saved-spot list has no equivalent success message. | `web/app/MarkCard.tsx:276`; `web/app/CommandBar.tsx:138`; `web/app/Planner.tsx:95–102,373`. |
| Offline chart saves can update one polite region for every item; a desktop forecast failure can appear in two polite regions at once. | `web/app/Trip.tsx:145–177`; `dist/offline-pack.js:124–145`; `web/app/Desktop.tsx:45–52,65–71`; `web/app/FirstAnswerLine.tsx:23–42`. |
| The admin relay alert can change without a user action; the packaged 3D report can replace unchanged status nodes. | `web/admin/app.tsx:63–80,104`; `packages/coast/src/coast3d/report.ts:52,93–102`. |

## R1. Inventory

Offline source read on 2026-11-21. All anchors refer to the staged `origin/main`, `9e078e2bd4c2db659e0f6e175c33cd6b0fd18553`, which was also the brief's baseline. No deployed site, browser accessibility tree or screen reader was tested. “Yes” means the source puts that outcome in a live region; it does **not** mean a particular screen reader spoke it. In particular, a region inserted already full, unhidden after writing, removed on success, or rewritten with unchanged text can behave differently from a persistent empty region receiving new text.

```sh
git rev-parse origin/main
git grep -nE 'aria-live|role="(status|alert)"' -- web packages
git grep -nEi 'ariaLive|ariaNotify|aria-live|role.{0,8}(status|alert|log|timer|marquee|progressbar)|<output|<progress' -- web packages dist
```

The literal search returns **142 matching source lines**, not 142 live regions: two are CSS selectors (`web/app/app.css:505,541`), one is a comment (`web/brief/Brief.tsx:769`), three are explicit `off`, and some lines contain several regions. It also misses the implicit status on the desktop time-window `output` (`web/app/CommandBar.tsx:185`). Rows group sites where the individual nodes or branches are named; shared sites can mount more than once.

`S` = `role="status"` (implicit polite, atomic); `P` = explicit polite; `A` = `role="alert"` (implicit assertive, atomic). `S+P` is one region, not two. `Off` is listed for comparison, not counted as live. Skip links move focus rather than announcing through a region (`web/app/SkipLinks.tsx:20–38,49–76`); `alertdialog` is a dialog, not a live alert (`web/app/TripAlerts.tsx:93`). The reusable guard and Dock are listed below.

### Public app, landing and Advisor

| Region | Mode | Text and what updates it |
|---|---|---|
| `web/RegionPickerEntry.tsx:25` | S | Loading regions or load failure on opening the lazy picker/import rejection; success replaces the node, close removes it (`:10–26`). Shared by landing and map port chooser (`web/landing/PortInput.tsx:109`; `web/app/CommandBar.tsx:145–167`). |
| `web/advisor/chat.tsx:114` | P, additions | Greeting on mount; sender, text and photo label when a sent message or reply is appended; reply images have empty alt (`:79–91,114–122`). |
| `web/advisor/chat.tsx:125` | S | Uploading, thinking, still thinking, pending or error; photo validation/upload, send response or timeout (`:61–71,79–93`). Successful attachment label is outside the region (`:129–133`). |
| `web/app/AccountMenu.tsx:52` | S | Alerts are loading or could not load; lazy import starts upon mounting and completion replaces the fallback with Trip Alerts (`:44–52,174`). |
| `web/app/CommandBar.tsx:138` | S | Link copied; only clipboard success sets it, cleared after 3 seconds (`:118–140`). |
| `web/app/CommandBar.tsx:185` | S, implicit `output` | Time-window label and formatted window; follows shell clock and zone, not selected dock hour (`:61–65,171–185`; `web/app/App.tsx:139–150`; `web/clock.ts:35–47`). |
| `web/app/ControlsTour.tsx:12` | P, atomic | Current tour step text and count as the account-menu tour is opened or stepped (`web/app/ControlsTour.tsx:7–22`; `web/app/AccountMenu.tsx:104,168,176`). |
| `web/app/FirstRun.tsx:111` | S | Boat setup save notices and Dismiss; form submits `saveFirstUse`, returns its notices and mounts this block if nonempty (`:60–67,104–118`). |
| `web/app/KeepAwake.tsx:10` | S | Could not keep the screen awake; wake-lock request failure, cleared on preference change (`web/wake-lock.ts:12–34`). |
| `web/app/LanguageChoice.tsx:24` | S | Language catalogue failed; reads the startup or language-change outcome (`web/i18n-catalogue.ts:82–122`; `web/app/LanguageChoice.tsx:10–25`). |
| `web/app/LayerRail.tsx:137` | S | Terrain habitat availability/ranking summary; changed viewer result feeds the rail (`web/map/stage.ts:340–344,523–555`; `packages/coast/src/coast3d/viewer.ts:267–274`). |
| `web/app/LayerRail.tsx:170` | S | Terrain depth shading basis/range and contour information; viewer emits after refinement and ramp/contour edits (`web/map/stage.ts:535`; `packages/coast/src/coast3d/viewer.ts:98–107,210–214,322`). |
| `web/app/Legend.tsx:365` | S | Saved-spot layer sign-in/account/offline/off/loading/empty/failure/private-ready status; session, presentation, toggle and list/retry results (`web/map/saved-spots.ts:107–126,280–352`). |
| `web/app/LimitsPanel.tsx:80` | S | Own vs default limits for profile; open/profile change, save or reset changes that state; not a general save receipt (`:53–80,195–205`). |
| `web/app/MapStage.tsx:111` | S | Bottom relief source unavailable after the layer reports failure (marks unavailable if previously drawn; cleanup clears it, `:92–103`). |
| `web/app/MapStage.tsx:112` | S | Bottom-relief shading explanation when relief reports drawing; unmount or loss removes it (`:92–103`). |
| `web/app/MapStage.tsx:128` | S | Map/graphics unavailable; fallback when the map cannot be used (`:116–132`). |
| `web/app/MapStage.tsx:143` | S+P, atomic | Loading the map; `chartLoading` while chart starts, cleared at first idle or failure, no “loaded” text (`:116–121,135–143`). |
| `web/app/MapStage.tsx:144` | S | Reason Terrain cannot be shown; renderer availability/failure or fallback state (`:135–144`; `web/map/stage.ts:77,590–594`). |
| `web/app/MapStage.tsx:145` | S+P, atomic | Switched to chart for slow 3D; frame monitor triggers fallback and timed clear (`web/map/stage.ts:442–445,643–649`). |
| `web/app/MapStage.tsx:146` | S | Zoom in for 3D; camera zoom crosses offer threshold when not blocked (`:135–146`). |
| `web/app/MapStage.tsx:147` | S | Place waypoint prompt, refusal reason and Cancel button; arming, chart click/boundary refusal or cancel (`:140,147`; `web/planner.ts:398–425`). |
| `web/app/MapStage.tsx:148` | S | Rough seafloor note; chart seafloor layer reports rough data, clears on withdrawal (`web/map/seafloor.ts:395,461,532,605`). |
| `web/app/MarkCard.tsx:201` | S | Copy unavailable reason for current mark/screened position (`:183–203`). |
| `web/app/MarkCard.tsx:221` | S | Mark position copied or copy failed; scoped clipboard outcome (`:190–221`). |
| `web/app/MarkCard.tsx:276` | S | Saved or refusal/error text, including preflight refusal; cleared while pending unless blocked, result accepted only for the current mark (`:243–276`). |
| `web/app/Masthead.tsx:74` | S | Region/location loading when the region reader starts (`web/app/App.tsx:97–131`). |
| `web/app/Masthead.tsx:75` | S | Region read failure with Retry (`web/app/App.tsx:97–131`; `web/app/Masthead.tsx:75`). |
| `web/app/Masthead.tsx:76` | S | Missing location including region and Choose link; cannot resolve a location (`:60–76`). |
| `web/app/Masthead.tsx:109` | S | Freshness name, source age, offline note, Refresh/Updating and failed/refused refresh; minute and connectivity sampling plus manual refresh (`:101–115`; `web/app/App.tsx:74–95`; `web/brief/Brief.tsx`, search `manualRefresh`). |
| `web/app/PreviewLayers.tsx:44` | S | One note per enabled preview layer: current load/result, stale/expiry or unavailability; toggle, source read and expiry (`:30–45`; `web/map/preview-layers.ts:116`, search `previewStatus` in `web/map`; `web/map/preview/common.ts:34`). |
| `web/app/views/Fleet.tsx:48` | S | Public grounds off, number drawn or reason; audit date when set; toggle and overlay source settlement (`:38–49`; search `grounds` in `web/map/fleet.ts`). |
| `web/app/views/History.tsx:92` | S | Loading/unbound/unavailable note when no usable history; usable chart replaces it (`:50–58,74–96`). |
| `web/app/views/Reports.tsx:168` | S | Reports loading while no report body; cached/loaded or section-level stale/error body is ordinary content (`:32–58,103–107,146–168`). |
| `web/brief/Brief.tsx:585` | S | Saved forecast and source age, amber when stale; provenance/clock updates (`:579–585,795–818`). Also used in desktop first answer (`web/app/FirstAnswerLine.tsx:23–42`). |
| `web/brief/Brief.tsx:713` | S | Forecast failure reason and Retry (busy during retry); failed epoch or retry outcome (`:707–717,795–818`; `web/brief/verdict-load.ts:43–56,86–88`). Also used in desktop first answer. |
| `web/brief/TideStationControl.tsx:68` | S | Removed/activated/nearest station or nearest-port failure/no match (`:23–38,41–68`). |
| `web/brief/TideStationControl.tsx:71` | S | Station loading while selection reader is pending (`web/tide-selection.ts`, search `loading.value`). |
| `web/brief/TideStationControl.tsx:72` | S | Station reader's result/selection notice (`web/tide-selection.ts`, search `notice.value`). |
| `web/brief/TideStationControl.tsx:73` | S | Station error and Retry; failed load, retry calls refresh and list (`web/tide-selection.ts`, search `error.value`). |
| `web/brief/WhereToLook.tsx:343` | S | No ranking because habitat unavailable; ranking recomputation chooses this empty branch, not ordinary empty/loading (`:323–346`). |
| `web/degraded-notice.tsx:11` | S | Using last saved data because of cost ceiling; mounts for fetch mark, disappears on recovery without success copy (`web/degraded.ts:36–50,62–109`). Desktop masthead, mobile lead (not mark-card branch) or landing (`web/app/Masthead.tsx:120,134–142`; `web/app/Mobile.tsx:123–134`; `web/landing/Landing.tsx:157–159`). |
| `web/landing/Landing.tsx:49` | S | Language load failure and Spanish retry link; conditional on failed catalogue (`:48–49`; `web/i18n-catalogue.ts:82–122`). |
| `web/landing/Landing.tsx:78` | P | Verdict heading/reason/note/link with accessible name and saved prefix; successful verdict read or late degraded/saved state (`:74–83,153–159`; `web/landing/live-verdict.ts:71–110`). |
| `web/landing/PortInput.tsx:87` | P | Port options, empty/loading copy and buttons; port list resolves, typing, Show All or geolocation changes selection list (`:46–74,83–101`). |
| `web/landing/PortInput.tsx:102` | S+P, atomic | Finding, closest port or geolocation refusal/error, and saved-home forgotten; new query clears feedback (`:46–74,83–102`). |
| `web/landing/ProfileStep.tsx:53` | S | Preparing/ready status for map warm-up; failed or skipped warming adds no failure status (`:36–54`). |
| `web/landing/RegionPicker.tsx:19` | S | Coverage snapshot needs rechecking; age test at render (`:15–19`). |
| `web/landing/RegionPicker.tsx:20` | P, atomic | Selected region name, lifecycle and six coverage rows; user picks a region (`:15–27`). Not live feed health. |
| `web/ui/Guard.tsx:12` | S | Panel render failure and Retry; error boundary switches to fallback, retry clears (`:10–26`); desktop/mobile call sites via `git grep -n '<Guard' -- web/app`. Not an async-error handler. |
| `web/ui/Dock.tsx:66`; `web/app/Mobile.tsx:108`; `web/brief/Brief.tsx:779` | Off | Desktop/mobile selected-hour readouts and Brief “Updating…” are deliberately off; the old Brief is hidden/inert while waiting (`web/brief/Brief.tsx:767–781`). |

### Planner, Trip and alerts

| Region | Mode | Text and what updates it |
|---|---|---|
| `web/app/Planner.tsx:95,96,97` | S ×3 | Saved-spot list loading, failed with Retry, or ready-empty. Open + signed-in + region, retry and list result (`web/planner.ts:755–803`). Ready-populated renders ordinary rows. |
| `web/app/Planner.tsx:102` | S | Spot added to plan, unavailable, boundary refusal or cap; user Adds after recheck (`web/planner.ts:805–820`). |
| `web/app/Planner.tsx:124` | S | Alert save refusal, duplicate, success or API failure; save/export/plan-change flow (`web/planner.ts:829,863–879`). |
| `web/app/Planner.tsx:135` | S per field | Invalid float-plan field message; input, date/zone and open/reset/reseed change validation (`:129–147`; `web/planner.ts:553–577`; `web/float-plan.ts:49`). |
| `web/app/Planner.tsx:221` | S | Arrival forecast loading/unusable; fetch per opening/region; usable forecast replaces with ordinary basis (`:213–221,391–401`). |
| `web/app/Planner.tsx:235` | S | Invalid typed timing and maximum; invalid parse mounts it, valid input clears (`:203–208,232–235`). |
| `web/app/Planner.tsx:297` | S | Plan scope status and dates; filters, ordering, research, presets, ranking and restore (`web/planner.ts:317–386,438–481,521–524`). |
| `web/app/Planner.tsx:348` | P | Waypoint and track totals if transferable, otherwise plan mark count; recalculated from selection and gates (`:348–350`; `web/planner.ts:282`). |
| `web/app/Planner.tsx:351` | S | Export validation: ready counts or refusal/reasons; same transfer summary (`:351–355`; `web/planner.ts:282`). |
| `web/app/Planner.tsx:365` | S | Waypoint actions and file/share outcomes (`web/planner.ts:398–425,704–737`). |
| `web/app/Planner.tsx:373` | S | Route boundary result or error after Download/Show on Chart; preview removal after invalidation; pending is on buttons (`web/planner.ts:604–615,642–693`). |
| `web/app/PortAlert.tsx:53` | S | Local limits saved, cleared or invalid; submit/clear (`:32–38,47–53`). |
| `web/app/PortAlert.tsx:54` | S | Forecast check state in the configured window as limits, forecast and time change; details/clocks are outside (`:39–44,54–56`; `web/port-alert.ts:75`). |
| `web/app/PositionView.tsx:49` | S | No offline pack; pack inventory read (`web/app/PositionCheck.tsx:20–42`). |
| `web/app/PositionView.tsx:51` | S+P | Fix refusal or boundary verdict and details after position check; clears while reading (button carries busy text), drops obsolete results (`:49–72`; `web/app/PositionCheck.tsx:20–42`). |
| `web/app/Trip.tsx:91` | S | Planner loading or load failure when open; success swaps in Planner, retry clears old error (`web/trip.ts:129–149`). |
| `web/app/Trip.tsx:106` | S | Pack legal data missing or stale based on metadata (`:102–106`). |
| `web/app/Trip.tsx:173` | S+P | Offline chart phase, item counts and bytes, then save/cancel/failure; also offline refusal and delete result (`:145–173`; `web/trip.ts:183–187`; `web/trip-runtime.ts:278–284`). |
| `web/app/Trip.tsx:174` | S+P | Pack inventory checking/failure; initial and 60-second or post-save/delete inventory reads, removed on success (`:126–144,155,160,174–177`). |
| `web/app/Trip.tsx:224` | S+P | Coastal snapshot checking/none or saved date and size; save/delete result; no per-item progress (`:202–224`). |
| `web/app/TripAlerts.tsx:185,189` | S ×2 | Calendar load failed; rules load failed. Separate async requests (`:157–189,248–257`). |
| `web/app/TripAlerts.tsx:466` | S | Prefill caveats for seeded alert, dismissed as affected fields change (`:279–299,450–466`). |
| `web/app/TripAlerts.tsx:467` | S | Reuse result and fields omitted after Use again (`:292–299,467`). |
| `web/app/TripAlerts.tsx:481` | S | Current device capability/subscription findings on device check (`:244–246,476–481`). |
| `web/app/TripAlerts.tsx:482` | S | Alert form validation, save/test/push/stop results, refresh/delete/ack failure or account/data actions (`:215–225,303–310,335–396,476–482`). |
| `web/app/TripAlerts.tsx:517` | S | Comfort preference save/remove success or error (`:399–435`). |
| `web/app/TripAlerts.tsx:550,551` | S ×2 | Loading/error from region-bound alert list startup (`:539–554`); successful items and offline/disabled branches aren't live. |

### Packaged 3D viewer and report

`/coast` and `/coast.html` redirect to the app (`server/routes/assets.ts:19–20,104`). The map mounts the embed with host chrome, detaching native layers, target and reading but keeping `#loading` (`web/map/stage.ts:523–555`; `packages/coast/src/embed.ts:47–70`). The native markup below is not automatically part of the map's accessibility tree. `git grep -nE 'new CoastReport|coast3d/report' -- web packages server dist tests` distinguishes the report class and its tests from a production instantiation; report rows describe packaged behavior.

| Region | Mode | Text and what updates it |
|---|---|---|
| `packages/coast/src/embed-template.ts:6` | S | Building your view of the coast; created populated, removed on startup before refinement finishes; loader can show failure only while present (`packages/coast/src/coast3d/viewer.ts:70–79`). |
| `packages/coast/src/embed-template.ts:8` `#shading-readout` | S | Depth colours and contour range/basis; refinement and contour/ramp changes (`packages/coast/src/coast3d/viewer.ts:98–107,210–214,322`). |
| `packages/coast/src/embed-template.ts:8` `#habitat-status` | S | Checking reviewed reef release, ranked candidates/limits or withholding reason; fetch/poll, depth or shore redraw (`packages/coast/src/coast3d/viewer.ts:78,267–274,323`). |
| `packages/coast/src/embed-template.ts:9` | P | Target name, facts and evidence; selection unhides and writes children; restoration can repeat writes, close hides (`packages/coast/src/coast3d/viewer.ts:262–265,278–284,332–335`). |
| `packages/coast/src/coast3d/report.ts:77` | S | Saved offline copy and saved timestamp, with source-clock caveat. Same helper for report and measured history when each has a saved timestamp (`:59–64,78–87,99`). |
| `packages/coast/src/coast3d/report.ts:78` | S ×2 | Measured history source unavailable or loading. Tab open/retry starts read; loading flag is set after initial render, so loading text is not guaranteed to appear. Settlement renders on History; Retry is outside the status (`:78–87,96–100`). |
| `packages/coast/src/coast3d/report.ts:99` refresh | S | Source refresh unavailable; retained clocks still apply. Failed managed refresh with retained report (`:59–64,93–99`). |
| `packages/coast/src/coast3d/report.ts:99` hour | S | No supported local NWS forecast hour; model view still available. Selected hour/context without supported local hour (`:67–75,90–99`). Supported-hour heading/time is ordinary text. |

### Checked-in client scripts and standalone pages

These sites are outside the requested `web packages` grep. The current app imports the account and exact-boat dialogs (`web/account.ts:99–112,157`); the token pages and Spot notes are separate surfaces (`server/routes/advisor.ts:252–253,560`; `web/app/AccountMenu.tsx:169`). The last two rows distinguish legacy render helpers from mounted app regions.

| Region | Mode | Text and what updates it |
|---|---|---|
| `dist/account.js:366` | A per field | Inline coordinate validation for the log/spot forms; failed parse or missing coordinate counterpart sets and reveals the error, next submit clears it (`:353–398,459,1180–1189`). |
| `dist/account.js:409` | S+P per form | Geolocation finding/result/refusal for log and spot position; click, result or invalidation (`:418–453,1178–1187`). |
| `dist/account.js:584` | S | Editing-log hint; Edit or leaving edit mode shows/hides it (`:972–980`). |
| `dist/account.js:601` | S | Filtered log count; fetch, paging and filter redraw (`:339–348,967–970`). |
| `dist/account.js:604` | S | Log CSV preparing, downloaded or incomplete/failure; export click and settlement (`:150–172`). |
| `dist/account.js:606` | S | Log loading, more, read/mutation results and errors (`:947–1098`, search `logStatus`). |
| `dist/account.js:629` | S | Spot editor saving and save failure; successful PATCH closes editor and writes to account status (`:1139–1162`). |
| `dist/account.js:701` | S+P, atomic | Passkey creation/sign-in prompts, unavailable or failure, signed-in/created confirmation (`:873–939`). |
| `dist/account.js:771` | S | Signed-in account feedback: spot add/edit, GPX result, credential and account actions/errors (`:1107–1117,1160–1235`). Successful spot removal redraws without a removal message (`:1174–1177`). |
| `dist/account.js:775` | S+P | Session-list loading/failure or result of ending other sessions; initial refresh/revocation (`:724–750,1237–1238`). |
| `dist/account.js:822` | S | Checking account on dialog open; session settlement replaces markup; offline/disabled copy is not live (`:831–837,868–874,943–947`). |
| `dist/boat-profile.js:44` | S | Lookup validation/loading/match/failure or sign-in required; invalid save/storage blocked. Search and save writes (`:82–124`). A successful local save closes, without a live receipt there. |
| `dist/my-data.html:24` | S | Token/session problem, download preparation/result/error; message controls visibility (`dist/advisor/my-data.js:19–62`). |
| `dist/upload.html:33,35` | P; S | Upload percentage on computable progress; separate outcome/validation status, shown when nonempty (`dist/advisor/upload.js:26–39,57–99`). The native progress bar at `dist/upload.html:32`, like `web/app/Trip.tsx:172`, is value semantics, not a separate authored announcement region. |
| `dist/downloads/spot-notes.html:8` | P | Target count changes on every filter input (`:11`); same count markup/writer in `atlas/avila-point-estero-2026-09-20/exports/spot-notes.html:8,11`. |
| `dist/home-port.js:92,93` | P; S | Legacy chooser results and feedback; query, geolocation and forget-home (`:115–148`). Current Planner imports its key, not the dialog (`web/planner.ts:25`). |
| `dist/live-conditions.js:158,174` | S ×2 | Legacy observations rendering: missing data → loading; active alerts → alert titles in a **polite** status (`:158–174`). Current app's confidence reader imports freshness functions (`web/confidence.ts:17`), not this renderer. |

### Admin (secondary)

Each numbered site below has the indicated role; `:52` in Queue has two alternative nodes. Generic errors use the screen's own load/error copy. Normal lists/details generally replace loading with ordinary content rather than a second success status (e.g. `web/admin/queue.tsx:52,107–108`).

| File | S: polite text | A: assertive text | Update triggers (same file unless qualified) |
|---|---|---|---|
| `web/admin/app.tsx` | — | `:104` Relay down and last-good time; `:106` no access | Health/access probes on mount, Refresh and 60 s health poll (`:52–89,110`). |
| `web/admin/health.tsx` | `:111` Inbox subscribed | `:24` Health load failed; `:112` subscription error | Shell health refresh (`web/admin/app.tsx:63–80,110`); Subscribe/refusal/retry (`:90–96,109`). |
| `web/admin/queue.tsx` | `:52` Details loading; `:107` Decision/replay and sent/held result | `:52` Detail failure; `:108` list failure; `:182` decision failure | Open Details, mount/filter/More, decision via buttons, shortcuts or editor (`:29–50,63–85,94–101,122,138–179,341–350`). |
| `web/admin/contact.tsx` | `:52` Block/unblock result | `:53` Detail load error; `:77` mutation error | Contact ID load (404 is ordinary text); Block/Unblock result (`:25–43,72`). |
| `web/admin/skippers.tsx` | `:45` Invite/boat outcome or paging error | `:46` Load failure; `:117` invite error; `:178` boat action error | Mount/More/reload, invite, verify/reject, edit or remove crew (`:24–44,62–77,89–102,132–145,165–174,189–201`). Details also use Queue's sites. |
| `web/admin/funnel.tsx` | — | `:62` Load failure | Mount/day-window fetch (`:42–47,55`). |
| `web/admin/rules.tsx` | `:61` Create/save/confirm/retire receipt | `:63` List failure; `:130` row action error; `:199` edit error; `:244` create error | Mount/filter and mutation results (`:27–39,49–56,76–77,90–93,121–128,186–193,210–223`). |
| `web/admin/posts.tsx` | `:47` Empty future slot count; `:156` action result | `:35` Calendar failure; `:157` list failure | Mount/week change or post mutation refetches calendar; filters/More refetch list; schedule/publish/retry and draft decisions update notice (`:30–45,80–83,94–133,144–150,176`; `web/admin/post-card.tsx:150–177`). Reuses Queue details/decision sites. |
| `web/admin/post-card.tsx` | — | `:132` Invalid schedule; `:180` action error | Editor submit then input clear; schedule save/clear, publish, retry (`:89–100,130,150–177`). |
| `web/admin/fleet-review.tsx` | `:72` Decision/replay | `:73` List failure; `:236` decision failure | Mount/filters/More and decision response (`:31–49,59–78,126–137`). |
| `web/admin/fleet-vessels.tsx` | `:159` Edit result | `:72` List failure; `:161` vessel missing; `:162` detail failed; `:302` removal error; `:316` unpin error; `:377` edit error | Mount/filters/More/ID reads and save/unpin/remove result (`:33–64,97,140–152,200–201,274–280,298,312–314,330–351`). |
| `web/admin/fleet-operators.tsx` | `:95` Save result | `:57` List failure; `:90` detail failure; `:96` mutation error | Mount/filters/ID or mutation reload; consent/status/outreach actions (`:46–54,81–87,106–119,131,148–159,169–174`). |
| `web/admin/fleet-coverage.tsx` | — | `:79` Load failure | Mount/region fetch (`:55–64,72`). |
| `web/admin/fleet-ais.tsx` | — | `:70` Load failure; `:81` stale snapshot per stale result | Mount/region/Refresh (`:42–51,59,67–71`); loading removes previous stale node, so a refresh can remount it. |
| `web/admin/fleet-trip.tsx` | `:167` Label/approval/removal result | `:110` List failure; `:143` detail failure; `:168` mutation error | Mount/filter/More/ID reads; label, approve/delete or segment pick clears result (`:85–91,107,124,139–159,188,213,224,238,292`). |
| `web/app/views/FleetAdmin.tsx` | `:74` Activity off/loading/result/failure | — | Toggle/Apply/Show on map (`:45,56–71`), map/query changes, result reuse/read and teardown (`web/map/fleet.ts:169–175,214–243,268`). |

## R2. Async outcomes: what has a live message?

| Outcome | Live region? | What is silent (or only normally readable) |
|---|---|---|
| Main Brief daily/conditions/forecast feed settles | **No** dedicated success region. **Yes** for forecast refusal/failure and saved-copy provenance (`web/brief/Brief.tsx:585,713,795–818`). Freshness may independently change (`web/app/Masthead.tsx:109–115`). | A usable verdict, partial-feed source gaps, unrateable/unknown answer, or no usable readings can change ordinary content without a feed completion message (`web/brief/Brief.tsx:286–324,631–654,675–693,795–818,885–900`; `web/app/FirstAnswerLine.tsx:23–42`). |
| Landing readings/optional verdict | **Yes** for the populated polite verdict if available (`web/landing/Landing.tsx:74–83,153–159`), with mount caveat. **No** for readings settlement (`web/landing/Readout.tsx:23–35`). | Missing feeds or forecast failure can leave the verdict absent; the readings may be unavailable without a live error (`web/landing/readings.ts:174–196`; `web/landing/live-verdict.ts:84–110`). |
| Region/chart/terrain/history/reports ready | **No** general ready message; R1 has separate loading/failure notes (`web/RegionPickerEntry.tsx:25`; `web/app/MapStage.tsx:143–148`; `web/app/views/History.tsx:74–96`; `web/app/views/Reports.tsx:146–168`; `packages/coast/src/coast3d/viewer.ts:70–79`). | Successful view/content replaces or clears the message. Region coverage itself has a separate live block (`web/landing/RegionPicker.tsx:20`). Native 3D currents and point-reading results have no live semantics (`packages/coast/src/embed-template.ts:8,10`; `packages/coast/src/coast3d/viewer.ts:285–299,312–316`); host currents note is plain too (`web/app/Legend.tsx:178–186`). Standalone 3D report first load and successful measured history have no result status (`packages/coast/src/coast3d/report.ts:59–64,77–100`). |
| Degraded banner appears / service recovers | **Yes** for the conditional cost-ceiling notice (`web/degraded-notice.tsx:11`); landing verdict may also change (`web/landing/Landing.tsx:74–83,157–159`). **No** recovery message. | `X-SC-Degraded: cost-ceiling` sets the mark; a verified later-day live read clears it, not midnight or generic HTTP failure. Removal is not a “recovered” update; saved-input verdict may stay labelled saved (`web/degraded.ts:36–50,62–109`; `web/landing/Landing.tsx:74–79`). |
| Selected hour scrubs, commits, plays or new verdict settles | **No** direct selected-hour or ready message. Dock/Updating explicitly off (`web/ui/Dock.tsx:66`; `web/app/Mobile.tsx:108`; `web/brief/Brief.tsx:767–781`); exceptions for saved/failure, and missing local hour in packaged report (`web/brief/Brief.tsx:585,713`; `packages/coast/src/coast3d/report.ts:99`). | Dock settles after 100 ms quiet; async source epoch settles separately; ordinary verdict replaced after pending (`web/dock-selection.ts:17,62–105`; `web/brief/verdict-load.ts:10,43–56,86–88`). The desktop time-window `output` follows wall clock, not selection (`web/app/CommandBar.tsx:61–65,185`). |
| Saved spot create/edit/load | **Yes** for mark save and rejection (`web/app/MarkCard.tsx:276`), account create/edit confirmation (`dist/account.js:771,1160,1187`), layer loaded/empty/error (`web/app/Legend.tsx:365`), and Planner Add (`web/app/Planner.tsx:102`). | Planner nonempty list success has no result status (`web/app/Planner.tsx:95–102`); account list population and successful removal redraw ordinary rows (`dist/account.js:1107–1117,1174–1177`). |
| Share copied, handed off or refused | **Yes** for map link copied (`web/app/CommandBar.tsx:138`) and mark-position copy/failure (`web/app/MarkCard.tsx:221`); Planner transfer writes result to `web/app/Planner.tsx:365` (`web/planner.ts:704–737`). | Map native share completion has no app status; manual fallback selects the URL field, not a live result. Recopy within the same three-second interval can leave the same text (`web/app/CommandBar.tsx:118–140`). |
| Offline chart pack progress / completion | **Yes** for phase/item/byte updates, saved/failed/cancelled/delete statuses (`web/app/Trip.tsx:145–173`). Inventory checking/failure separate (`:174–177`). Coastal snapshot has its own result (`:202–224`). | Successful inventory refresh replaces checking with ordinary inventory instead of an explicit “checked” message (`web/app/Trip.tsx:174–191`). Coastal snapshot has no comparable item stream. |
| Form validation or async refusal | **Yes** where explicit: float/timing (`web/app/Planner.tsx:135,235`), Port Alert (`web/app/PortAlert.tsx:53`), Trip Alerts/comfort (`web/app/TripAlerts.tsx:482,517`), account coordinate alerts (`dist/account.js:366`) and R1 admin sites. | Native constraints can prevent submit before the custom status writer (e.g. `web/app/TripAlerts.tsx:335–350,457–464`); browser validation isn't an app live announcement. Repeated identical error text may not produce a new mutation. |
| Route calculated / refused / withdrawn | **Yes** for boundary-checked route download/preview result, error and removal (`web/app/Planner.tsx:373`; `web/planner.ts:604–615,642–693`). | Pending is button text (`web/app/Planner.tsx:371–372`); geometry drawn on chart is not spoken as route detail. This is a planning-route check, not a navigation guarantee (`:366–374`). |
| Other silent successes | **No** for Advisor photo uploaded (ordinary attachment label, though send/reply and errors are live, `web/advisor/chat.tsx:61–71,114–133`), successful language swap (failure-only sink, `web/app/LanguageChoice.tsx:10–25`), or alert list loaded (loading/error only, `web/app/TripAlerts.tsx:539–554`). | Focus movement, a new accessible label, or visible content can still convey part of these results through normal navigation; none is a separate completion region. |

## R3. Likely over-announcement, ranked (estimates)

These ranks estimate how disruptive a change could be, not speech counts. Re-render alone does not prove a live text mutation.

| Rank | Region and evidence | Why it could be noisy |
|---|---|---|
| 1 | Offline chart progress (`web/app/Trip.tsx:145–177`; `dist/offline-pack.js:124–145`; `web/trip-runtime.ts:141,184,195,278–284`) | Changing counts/bytes can reach the polite status per file/tile with no UI rate limit. Inventory checks have another writer; final save result can follow a burst. |
| 2 | Desktop forecast + saved copy (`web/app/Desktop.tsx:45–52,65–71`; `web/app/FirstAnswerLine.tsx:23–42`; `web/brief/Brief.tsx:579–585,707–717,795–818`) | Same forecast failure/Retry can be exposed twice. With a retained saved forecast and failed update, up to four status nodes across the two surfaces, not four proven utterances. |
| 3 | Clock and background state (`web/app/App.tsx:74–95`; `web/app/Masthead.tsx:109–115`; `web/app/CommandBar.tsx:185`; `web/clock.ts:35–47`; `web/admin/app.tsx:63–80,104`) | Freshness age can change with the minute sampler, and its atomic region wraps a changing button label. Desktop `output` can change on the hour. Admin relay is assertive and driven by a 60 s poll; a changing state/timestamp can interrupt without interaction. No evidence of one new alert for every unchanged response. |
| 4 | Terrain and packaged report (`packages/coast/src/coast3d/viewer.ts:78,98–107,210–214,267–274,308–310,322–323`; `packages/coast/src/coast3d/report.ts:52,93–102`) | Native habitat writes before host payload dedupe; 60 s polling or depth changes can write again. Refinement/ramp edits rewrite shading; report refresh replaces all panel HTML, including unchanged status nodes. Native chrome reach is limited as noted in R1; the per-frame labels/pins are not themselves live writers. |
| 5 | User-driven groups (`web/landing/PortInput.tsx:83–102`; `web/landing/RegionPicker.tsx:19–27`; `web/landing/Landing.tsx:74–83,157–159`; `web/app/Planner.tsx:348–355`; `dist/advisor/upload.js:69–75`; `dist/downloads/spot-notes.html:11`) | Port options and feedback may both change after locate; a region pick can read the whole atomic coverage block. A late landing mark changes verdict and notice. Planner counts and validation may change together; percent and filter count can update repeatedly. |

The deliberately quiet dock and hour transition (`web/ui/Dock.tsx:66`; `web/app/Mobile.tsx:108`; `web/brief/Brief.tsx:767–781`) are not a timer-noise recommendation. Chat has a bounded “still thinking” timeout, not a repeated polling announcement (`web/advisor/chat.tsx:83–93,125–126`).

## R4. One proposed unit (estimate: 75–105 minutes)

Separate visual offline-pack counters from spoken progress in `web/app/Trip.tsx:145–177`. Keep the bar and visible item/byte counts updating; use the existing status for phase changes and terminal save/failure/cancel/delete messages, not every count. Leave inventory, timing and pack writers unchanged. Add an offline fixture to `tests/test_trip_pack_announcements.mjs` using a fake progress sequence: two counts in one phase update the visible bar but not live text, the next phase changes live text, and success and failure each replace progress with the result. Proposed check: `node --test tests/test_trip_pack_announcements.mjs` after implementing that unit. This would prove DOM behavior, not screen-reader speech. No implementation or test added by this audit.
