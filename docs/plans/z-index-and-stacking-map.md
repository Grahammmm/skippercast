# Map z-index and stacking map

| Surface | What sets its order | Main overlap to watch |
| --- | --- | --- |
| Map app | Six `--z-*` tokens; small local integers for sticky actions and fallback content (`web/tokens.css:210–216`, `web/app/app.css:191,476`, `web/app/MapStage.tsx:127`). | Opening the phone account menu raises the **whole top strip** from 11 to 40 so its panel can cover the sheet (30); the panel's own 40 cannot do that alone (`web/app/app.css:337,627–631`, `web/ui/ui.css:110`). |
| Terrain / 3D | `/coast` redirects to the app. The embedded scene uses literal layers inside the app's map layer (0); `panel.css` is not the terrain scene's stylesheet (`server/routes/assets.ts:18–26,104`, `web/app/app.css:118`, `web/map/terrain.js:9–13`, `web/app/CoastMarkup.tsx:38–47,143–150`). | Scene loading (3) covers scene pins and labels (1), but not app chrome (10). The legacy 1000 skip link is not the app's skip link (`packages/coast/coast.css:1,5`, `packages/coast/panel.css:120–130`, `web/app/app.css:158,623–624`). |
| Dialogs | Native `showModal()` uses the browser top layer; the older body-appended account scrim uses CSS level 40 (`web/app/LimitsPanel.tsx:171–190`, `web/landing/PortInput.tsx:122–140`, `dist/account.js:819–824`, `web/app/account.css:37–42`). | A focused skip link (50) can paint above a CSS scrim, not a native modal. Sticky action rows only layer inside their own scroll surface (`web/app/app.css:464–476,623–624`, `web/app/trip.css:42–47`). |

**Evidence:** Offline source read on 2026-11-21; local `origin/main` and the card baseline both resolved to `9e078e2bd4c2db659e0f6e175c33cd6b0fd18553`. All repository anchors refer to that revision. Paint order and overlap are source deductions, not live/browser observations. To reproduce the inventory from that checkout:

```sh
git rev-parse origin/main
git grep -nE 'z-index' -- web packages
git grep -nE -e '--z-' -- web/tokens.css
git grep -niE 'zIndex|z-index' -- web packages
```

## R1. Token scale and every rule in the scan

| Token | Value | Source |
| --- | ---: | --- |
| `--z-map` | 0 | `web/tokens.css:211` |
| `--z-map-chrome` | 10 | `web/tokens.css:212` |
| `--z-dock` | 20 | `web/tokens.css:213` |
| `--z-sheet` | 30 | `web/tokens.css:214` |
| `--z-modal` | 40 | `web/tokens.css:215` |
| `--z-toast` | 50 | `web/tokens.css:216` |

The baseline grep has 57 matching **lines**: 56 CSS lines and the DOM-order comment at `web/app/Mobile.tsx:239`. Expanding the multiple declarations on single lines in `coast.css` gives 65 CSS declarations. The case-insensitive scan also finds one inline `zIndex`. “Closest” means smallest numeric distance, **not** a proposed substitute: changing a local `1` to `--z-map` could change who paints on top, and replacing 100 and 1000 with 50 would erase their order. A group selector is one declaration. A `var` row has no hard-coded z-index; its resolved value is shown. This is the `web` and `packages` inventory, not a census of unrelated `dist` pages or GPU draw order.

| Source | Selector / element | Declaration → value | Closest token |
| --- | --- | --- | --- |
| `web/app/account.css:22` | `.app-account-panel` | `var(--z-modal)` → 40 | `--z-modal` |
| `web/app/account.css:38` | `.home-port-scrim` | `var(--z-modal)` → 40 | `--z-modal` |
| `web/app/app.css:116` | `.app-map` | `var(--z-map)` → 0 | `--z-map` |
| `web/app/app.css:118` | `.app-terrain` | `var(--z-map)` → 0 | `--z-map` |
| `web/app/app.css:128` | `.app-presentation` | `var(--z-map-chrome)` → 10 | `--z-map-chrome` |
| `web/app/app.css:158` | `.app-terrain-controls` | `var(--z-map-chrome)` → 10 | `--z-map-chrome` |
| `web/app/app.css:175` | `.app-chrome-left` | `var(--z-map-chrome)` → 10 | `--z-map-chrome` |
| `web/app/app.css:191` | `.app-chrome-left > .app-mark .app-mark-actions` | `1` | `--z-map` |
| `web/app/app.css:192` | `.app-legend` | `var(--z-map-chrome)` → 10 | `--z-map-chrome` |
| `web/app/app.css:302` | `.app-mark` | `var(--z-map-chrome)` → 10 | `--z-map-chrome` |
| `web/app/app.css:320` | `.app-main > .app-stage > .app-dock` | `var(--z-map-chrome)` → 10 | `--z-map-chrome` |
| `web/app/app.css:337` | `.app-top` | `calc(var(--z-map-chrome) + 1)` → 11 | `--z-map-chrome` |
| `web/app/app.css:392` | `.app-tabs` | `var(--z-sheet)` → 30 | `--z-sheet` |
| `web/app/app.css:399` | `.app-stage > .app-conditions, .app-stage > .app-history` | `var(--z-map-chrome)` → 10 | `--z-map-chrome` |
| `web/app/app.css:449` | `.app-page` | `var(--z-sheet)` → 30 | `--z-sheet` |
| `web/app/app.css:461` | `.app-mobile-page` | `var(--z-map-chrome)` → 10 | `--z-map-chrome` |
| `web/app/app.css:476` | `.app-limits-dialog .app-limits-actions` | `1` | `--z-map` |
| `web/app/app.css:623` | `.app-skip-link` | `var(--z-toast)` → 50 | `--z-toast` |
| `web/app/app.css:631` | `.app-top:has(.app-account[data-top] .app-account-panel:not([hidden]))` | `var(--z-modal)` → 40 | `--z-modal` |
| `web/app/trip.css:43` | `.port-dialog .app-offline-actions` | `1` | `--z-map` |
| `web/app/views/hourly-table.css:6` | `.app-hourly thead th` | `1` | `--z-map` |
| `web/landing/landing.css:25` | `.landing-shore` | `var(--z-map)` → 0 | `--z-map` |
| `web/landing/landing.css:29` | `.landing-head, .landing-main, .landing-dots, .landing-foot` | `var(--z-map-chrome)` → 10 | `--z-map-chrome` |
| `web/landing/landing.css:35` | `.landing .landing-night` | `var(--z-map)` → 0 | `--z-map` |
| `web/landing/port-input.css:45` | `.app-firstrun` | `var(--z-toast)` → 50 | `--z-toast` |
| `web/landing/port-input.css:59` | `.app-boat-entry` | `var(--z-toast)` → 50 | `--z-toast` |
| `web/map/c2.css:6` | `.coast-mvp-chrome` | `1` | `--z-map` |
| `web/ui/ui.css:58` | `.ui-popover-body` | `var(--z-modal)` → 40 | `--z-modal` |
| `web/ui/ui.css:83` | `.ui-rail` | `var(--z-map-chrome)` → 10 | `--z-map-chrome` |
| `web/ui/ui.css:91` | `.ui-dock` | `var(--z-dock)` → 20 | `--z-dock` |
| `web/ui/ui.css:110` | `.ui-sheet` | `var(--z-sheet)` → 30 | `--z-sheet` |
| `web/app/MapStage.tsx:127` | `.app-stage-note.app-stage-failed` (inline) | `zIndex: 1` | `--z-map` |

| Source | Selector | Literal | Closest token |
| --- | --- | ---: | --- |
| `packages/coast/coast.css:1` | `header` | 2 | `--z-map` |
| `packages/coast/coast.css:1` | `.intro` | 1 | `--z-map` |
| `packages/coast/coast.css:1` | `.layers` | 1 | `--z-map` |
| `packages/coast/coast.css:1` | `#reading` | 1 | `--z-map` |
| `packages/coast/coast.css:1` | `.view-controls` | 1 | `--z-map` |
| `packages/coast/coast.css:1` | `#labels` | 1 | `--z-map` |
| `packages/coast/coast.css:1` | `#loading` | 3 | `--z-map` |
| `packages/coast/coast.css:5` | `#pins` | 1 | `--z-map` |
| `packages/coast/coast.css:5` | `.layers,.intro,.reading,.view-controls,footer` | 2 | `--z-map` |
| `packages/coast/coast.css:8` | `.target-detail` | 3 | `--z-map` |
| `packages/coast/coast.css:18` | `.report-bar` | 2 | `--z-map` |
| `packages/coast/coast.css:18` | `#report-close` | 1 | `--z-map` |
| `packages/coast/coast.css:29` | `.home-art-label,.home-art-caption` | 1 | `--z-map` |
| `packages/coast/coast.css:29` | `.home-art strong` | 1 | `--z-map` |
| `packages/coast/coast.css:31` | `.home-nojs` | 10 | `--z-map-chrome` |
| `packages/coast/coast.css:40` | `.relief-chip` | 1 | `--z-map` |
| `packages/coast/panel.css:124` | `.skip-link` | 1000 | `--z-toast` |
| `packages/coast/panel.css:167` | `.app-header` | 12 | `--z-map-chrome` |
| `packages/coast/panel.css:304` | `.command-bar` | 10 | `--z-map-chrome` |
| `packages/coast/panel.css:672` | `#flow-canvas` | 2 | `--z-map` |
| `packages/coast/panel.css:678` | `.map-vignette` | 3 | `--z-map` |
| `packages/coast/panel.css:683` | `.map-heading` | 4 | `--z-map` |
| `packages/coast/panel.css:718` | `.layer-rail` | 5 | `--z-map` and `--z-map-chrome` (tie) |
| `packages/coast/panel.css:757` | `.map-tools` | 5 | `--z-map` and `--z-map-chrome` (tie) |
| `packages/coast/panel.css:779` | `.map-loading` | 8 | `--z-map-chrome` |
| `packages/coast/panel.css:812` | `.map-legend` | 4 | `--z-map` |
| `packages/coast/panel.css:878` | `.map-footnote` | 3 | `--z-map` |
| `packages/coast/panel.css:896` | `.map-notice` | 4 | `--z-map` |
| `packages/coast/panel.css:1046` | `.time-dock` | 8 | `--z-map-chrome` |
| `packages/coast/panel.css:1488` | `.dialog-close` | 3 | `--z-map` |
| `packages/coast/panel.css:1750` | `.no-script` | 100 | `--z-toast` |
| `packages/coast/panel.css:2239` | `.layer-rail` (≤760 px) | 7 | `--z-map-chrome` |
| `packages/coast/panel.css:2395` | `.mobile-nav` (≤760 px) | 15 | `--z-map-chrome` and `--z-dock` (tie) |
| `packages/coast/panel.css:2725` | `.map-attribution` | 6 | `--z-map-chrome` |

**MapLibre, third-party only.** `package.json:23` and `pnpm-lock.yaml:1029` pin 6.18.0; imports are at `web/map/maplibre.js:11` and `web/map/c2.js:4`. Offline read of the cached 6.18.0 `dist/maplibre-gl.css:1` on 2026-11-21 (CSS SHA-256 `a90798a1953017790e590f7e1bd35ff103a8a4263972cb47290b78adf86f8c20`):

| Selector | Literal | Closest token |
| --- | ---: | --- |
| `.maplibregl-popup-tip` | 1 | `--z-map` |
| `.maplibregl-ctrl-bottom-left,.maplibregl-ctrl-bottom-right,.maplibregl-ctrl-top-left,.maplibregl-ctrl-top-right` | 2 | `--z-map` |
| `.maplibregl-cooperative-gesture-screen` | 99999 | `--z-toast` |
| `.maplibregl-pseudo-fullscreen` | 99999 | `--z-toast` |

The app installs zoom, nautical scale and Sources controls at bottom right and adds geolocation at top right when requested (`web/map/engine.ts:188–190,353`). The vendor selector list describes available CSS, not proof that the app activates all these states. Its large integers cannot lift descendants of `.app-map` above app chrome (`web/app/app.css:116,128,158`).

## R2. What actually stacks, bottom to top

Read each bracket as its own stack. A child can reorder its siblings, but it cannot use its number to leave its parent's stacking context. Equal levels in the same context paint in tree order for these layers; geometry, clipping and focus still matter. For example the sheet precedes the tab bar in `web/app/Mobile.tsx:253–267` and reserves space for it in `web/app/app.css:348–355`.

```text
App (Chart or Terrain; App.tsx:139–154, MapStage.tsx:230–237)
  page background / normal flow (masthead, command bar, brief)
  0   Chart [base/poster, failure note 1, vendor controls 2]
      OR Terrain [its entire scene; see below]
  10  presentation / Terrain buttons; desktop rail, mark/legend column,
      Conditions or History cover, sticky dock wrapper; phone Plan/Reports page
  11  phone top strip when closed [its own card and controls]
  30  desktop Plan/Reports cover OR phone sheet and tabs
      [phone hour controls, brief/layers, first-run card and sheet popovers]
  40  phone top strip when account open [its panel 40 is local];
      custom body scrims and any untrapped desktop disclosures at 40
  50  focused skip link; fixed desktop first-run or boat-entry card
  browser top layer: native modal backdrop, then native dialog and its controls
```

- App anchors for 0–50 are in R1; `web/app/Desktop.tsx:65–76` and `web/app/Mobile.tsx:237–267` show the alternatives. The desktop `.ui-dock` is a flex item with 20 **inside** the sticky `.app-dock` at 10 in the desktop layout; the phone's hour edge sits inside the sheet (`web/app/app.css:295–296,312–320`, `web/ui/ui.css:82–91`, `web/app/Mobile.tsx:253–254`). The desktop left column is 10; the mark/legend are static flex items there and can still use their local z-index. Even the legend's viewport-fixed, anchor-positioned popover remains under the column's ancestor stacking context; viewport positioning solves clipping, not app-wide order (`web/app/app.css:173–191`, `web/ui/ui.css:57–61`). A sheet popover's local 40 similarly stays under the sheet's 30.
- Fixed elements create contexts, including the tab bar, custom scrims and skip links; the sheet and desktop prompt cards also use transforms (even `translateY(0)` is not `none`). The blurred top card and rail/dock surfaces create contexts even without relying on positioning. Stage/main positioning plus overflow does not itself add a stack level (`web/app/app.css:115,334–355,392,448,623`, `web/ui/ui.css:82–91,106–115`, `web/landing/port-input.css:43–70`, `web/app/account.css:38`). On the separate landing surface the fixed shore/night sit at 0 below content at 10; opacity below 1 makes the fade a grouped layer, not a boost for its children (`web/landing/landing.css:25–44`).

```text
Current 3D inside .app-terrain (outer 0; web/app/app.css:118)
  auto   terrain canvas in the positioned, clipped #scene
  1      place labels → relief chip → species pins (equal level, template order)
  3      loading cover while mounted
  back outside .app-terrain: app chrome 10 and higher, as in the app diagram
  browser top layer: native sources dialog/backdrop when opened with showModal()
```

`web/map/stage.ts:524` requests host chrome; `packages/coast/src/embed.ts:37–66` mounts the scene in shadow DOM and detaches the layers panel, view controls, reading and target detail, while `web/map/terrain.css:4–13` hides the intro/footer. Within the scene, the labels/pins have their own level-1 contexts, the place/pin transforms group individual markers, and the relief chip's transform also groups it (removed at narrow widths, but its positioned 1 remains). The loading cover is removed on successful load. The shadow root scopes CSS; the outer positioned host at 0, not the shadow root itself, limits the renderer's page order (`packages/coast/coast.css:1,5,40`, `packages/coast/src/embed-template.ts:6–12`, `packages/coast/src/coast3d/viewer.ts:77,381`). The separate C2 stylesheet would put notice/sources chrome at 1 within the host alongside MapLibre controls; C2 is disabled, with no releases at this baseline (`web/map/c2.css:1–7`, `web/map/c2-releases.ts:1–5`).

```text
Coast stylesheet with legacy standalone chrome (rule order, not a current route)
  auto canvas → 1 labels/chip/pins/reading → 2 header/report bar/intro/layers/
  view controls/footer → 3 loading and target detail → 10 home no-JS notice
  → browser top layer for native report/sources dialogs [sticky report close 1]

Panel stylesheet, legacy shell rules (not another tier above current 3D)
  auto map → 2 current-flow canvas → 3 vignette/footnote → 4 heading/legend/notice
  → 5 tools and desktop layers → 6 attribution → 7 phone layers
  → 8 loading/time dock → 10 command bar → 12 header → 15 phone nav
  → 100 no-script notice → 1000 focused skip link
  native dialog, when opened in the top layer [its own sticky close 3]
```

These legacy diagrams describe each stylesheet's declared levels, not a claim all nodes coexist. In `coast.css` the `#reading` ID beats `.reading`, so it stays at 1; `.intro`, `.layers` and `.view-controls` are raised to 2 by the later rule. The blurred layers/detail panels group their descendants; home art uses local flex-item and positioned-caption layers above the transformed/masked contour art (`packages/coast/coast.css:1,5,8,18,27–31`, `packages/coast/src/coast3d/report.ts:76`). In `panel.css`, header/command/dock/nav levels can apply to static grid items in the legacy grid (`packages/coast/panel.css:22–26,160–167,297–304,1039–1046,1894–1905,2388–2395`); the map stage is positioned/clipped, and blur and the translated notice group local content (`packages/coast/panel.css:658–667,715–726,808–815,885–896`). On today's app the panel CSS import is for allow-listed chart, catch and history markup, not that legacy shell (`web/app/CoastMarkup.tsx:38–47,134–150`). The older standalone-route comment in `packages/coast/src/embed-template.ts:1–5` describes shared markup; the Worker redirect determines today's route (`server/routes/assets.ts:18–26,104`).

## R3. Real overlap states and winners

| Pair and trigger | Winner where their boxes intersect | Intent from source |
| --- | --- | --- |
| **Phone account panel/top strip vs. expanded sheet.** Open the account icon with the brief sheet up. The panel drops below its trigger and can cover the strip's lower content as well as the sheet. | Inside the strip, panel 40 paints above the other strip content. Against the sheet, the entire strip at 40 wins over 30; when the menu closes, the strip drops to 11. The inline account disclosure is static and does not trigger this raise. | Explicit: “its panel opens above the sheet” (`web/app/app.css:337–343,627–631`; `web/app/account.css:21–28`; `web/app/AccountMenu.tsx:123–126`; `web/app/Mobile.tsx:240–265`). The comment describes the panel, not a separate requirement for other strip children to rise. |
| **Focused skip link vs. modal.** Tab into a skip link on the normal page; compare the custom account overlay with opening Limits, Change port, Trip or Save for offline. | In document paint order skip link 50 beats scrim 40 **if still focused**; otherwise it is clipped. The account open path moves focus into its overlay, so this is not a normal persistent visible collision. A native modal and backdrop beat the skip link at any document z-index, and background links cannot take focus while it is modal. | Keyboard-only visibility is deliberate; native focus trapping is called out. No comment says to lift a skip link above a modal (`web/app/app.css:623–624`; `web/app/account.css:37–38`; `dist/account.js:819–839`; `web/app/LimitsPanel.tsx:1–5,178–184`; `web/landing/PortInput.tsx:122–134`; `web/app/Trip.tsx:75–85,234–243`). |
| **Toast-tier card vs. sheet.** A new visitor sees First Run, then optionally Boat Entry. | Desktop overlay 50 can cover the Plan/Reports surface at 30; the desktop layout has no phone sheet. On phone these are static content inside the sheet/page: neither card floats above the sheet or tabs. A focused skip link is the actual page-level 50 on phone and wins over sheet 30 if boxes meet. | Explicit: desktop prompt is “over the map, never modal”; the phone override keeps handle, time control and navigation reachable. No separate toast widget is implied by the token (`git grep -n -- --z-toast web packages`; `web/app/App.tsx:144–151`; `web/app/FirstRun.tsx:117–129`; `web/landing/port-input.css:43–70`; `web/app/Mobile.tsx:237–267`). |
| **Sticky action bars vs. scrolling dialog content.** Scroll Your limits or Save for offline with enough content to reach the sticky edge. | Sticky `1` covers ordinary content at the overlap inside the same dialog, not another dialog. Offline has two bars in separate sections; stickiness is bounded by the section. If same-level bars ever intersect, the later Coastal Readings row paints after the Chart Pack row. Legacy close controls likewise use a local value, not a page overlay. | The opaque background and sticky edge indicate intended action visibility; the offline comment names the feature, not a desired bar-on-bar overlap (`web/app/app.css:464–477`; `web/app/LimitsPanel.tsx:163–168,180–190`; `web/app/trip.css:42–47`; `web/app/Trip.tsx:163–173,217–224,239–243`; `packages/coast/coast.css:18`; `packages/coast/panel.css:1483–1489`). |
| **Open sheet popover vs. tabs / raised strip.** Open a tile's basis disclosure in a brief sheet, then compare at the sheet edge or with the account panel open. | Popover's local 40 cannot beat the later 30 tab bar or the raised strip's page-level 40. The sheet body can clip it before the paint order matters. The desktop legend's fixed popover still cannot escape its layer-10 outer column. | Sheet scroll and legend clipping are discussed; no comment promises that a basis disclosure covers navigation (`web/ui/ui.css:52–63,106–130`; `web/app/Mobile.tsx:253–267`; `web/app/app.css:180–186,378,392,631`; `web/ui/Popover.tsx:47–52`). |
| **3D loader or moving labels/pins vs. scene and app controls.** Enter 3D, then pan the loaded scene. | Startup cover 3 paints over scene overlays at 1 until removed. On a shared pixel after load, pins paint after labels and relief chip at equal 1; the full-screen pin wrapper is click-through, but its pin buttons can take clicks. App chrome stays above all of them. A standalone detail/loader 3 tie alone does not prove a live collision in the managed app: detail is detached. | Loader role and removal match a temporary cover; no comment assigns priority to pin over chip. Host chrome and chip placement are explicit (`packages/coast/src/embed-template.ts:6–11`; `packages/coast/coast.css:1,5,8,40`; `packages/coast/src/coast3d/viewer.ts:77`; `packages/coast/src/embed.ts:50–66`; `web/map/terrain.css:4–13`; `web/app/app.css:118,128,158`). |

## R4. Follow-up

No build unit recommended from this source-only audit. The phone account raise and phone prompt placement have explicit intent, native modal precedence doesn't require another token, and the legacy literal collisions are not evidence of a live `/coast` defect (`web/app/app.css:627–631`; `web/landing/port-input.css:68–70`; `web/app/LimitsPanel.tsx:171–184`; `server/routes/assets.ts:18–26,104`). This report changes no application behavior.
