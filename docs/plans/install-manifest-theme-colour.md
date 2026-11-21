# Installed-app and page theme colours

## R1. Summary and colour table

| Setting or surface | Dark/default | Light | Source on main |
| --- | --- | --- | --- |
| Manifest `theme_color` | `#082e3b` | Same; one value | `dist/manifest.webmanifest:1` |
| Manifest `background_color` | `#082e3b` | Same; one value | `dist/manifest.webmanifest:1` |
| Map (`app.html`) `theme-color` meta | `#082e3b` | Same; no `media` attribute | `dist/app.html:20` |
| Landing `theme-color` meta | `#082e3b` | Same; no `media` attribute | `dist/landing.html:35` |
| Map body (`--bg`) | `#07131d` | `#f4f8f9` | `web/tokens.css:35,421–422`; `web/app/app.css:11`; stylesheet links at `dist/app.html:31–33` |
| Deeper background (`--bg-deep`, used by the landing body) | `#020b12` | `#e4edf1` if the light selector is applied | `web/tokens.css:36,421–423`; `dist/landing.html:47–52`; `web/landing/landing.css:10` |
| App runtime `applyTheme` | Removes `data-theme`; root CSS sets `color-scheme: dark` | Sets `data-theme="light"`; root CSS sets `color-scheme: light` | `web/theme-boot.ts:19–27`; `web/tokens.css:49,421,493` |

**Verdict:** The two manifest fields and both meta tags agree with each other, but not with either exact map body colour or the default landing background (table above). The mismatch is much larger in light mode.

Basis: offline source read on 2026-11-21 at local `origin/main` `26aa28ab1ce4e883c0850cdb7f1243c4ed48c07e` (the supplied baseline). No live site or phone was tested.

`bootTheme` uses a saved `light` or `dark` choice under `skippercast-theme-v1`, otherwise Auto uses `matchMedia('(prefers-color-scheme: light)')` (no match support means dark). The app reapplies it on a choice change and follows OS changes only in Auto. Neither path edits the meta tag (`web/theme-boot.ts:3–31`; `web/theme-choice.ts:6–18`). Vite injects the blocking theme boot script into **`app.html` only**, not the landing (`vite.config.mjs:159–191`); the landing starts without `data-theme` (`dist/landing.html:1–3,47–52,82`; `web/landing/main.tsx:74–90`). The light `--bg-deep` token is not evidence of a light landing page.

## R2. What a phone visitor might see

| Surface | Estimate based on the checked-in inputs |
| --- | --- |
| Installed launch/splash | On an installer that uses manifest `background_color` for launch, expect a fixed dark teal field. The manifest starts at `/`, which serves the dark landing with no query; even there the landing paints darker than the splash hint. If the landing forwards a returning visitor to a saved port and the map boots light, the transition can be more obvious. The manifest cannot see the saved choice before the page runs (`dist/manifest.webmanifest:1`; `server/routes/assets.ts:34–42`; `web/landing/main.tsx:32–37,80–86`; R1). |
| Address bar | In a browser that honours the page meta hint, the bar can remain dark teal above a light map, whether light came from the OS in Auto or from an explicit override. A dark map also differs in hue, but both surfaces are dark. A standalone window may have no address bar (`dist/manifest.webmanifest:1`; `dist/app.html:20`; `web/theme-boot.ts:19–31`; R1). |
| OS status bar | Where a browser or installed shell derives the status bar tint from the manifest or page hint, it may also remain dark above the light map. Neither page supplies an Apple-specific status bar style. Do not infer an exact bar tint, icon/text contrast, or iOS splash from these files: platforms can ignore, adjust, or select a different hint (R1; `git grep -niE 'theme-color|apple-mobile-web-app-status-bar-style' -- web server vite.config.mjs dist/app.html dist/landing.html` returned only the two meta tags on 2026-11-21). |

## R3. Icons and shortcuts

| Asset | Manifest declaration (`dist/manifest.webmanifest:1`) | Actual file |
| --- | --- | --- |
| `/app-icon.svg` | `any`, `image/svg+xml`, purpose `any` | SVG, `viewBox="0 0 192 192"`, no fixed raster pixel size (`dist/app-icon.svg:1`) |
| `/app-icon-192.png` | `192x192`, `image/png`, purpose `any` | 192 × 192 PNG, 8-bit RGBA |
| `/app-icon-512.png` | `512x512`, `image/png`, purpose `any` | 512 × 512 PNG, 8-bit RGBA |
| `/app-icon-maskable-512.png` | `512x512`, `image/png`, purpose `maskable` | 512 × 512 PNG, 8-bit RGB |
| All three shortcut icons | All reuse `/app-icon-192.png`, `192x192`, `image/png`; no explicit purpose | Same 192 × 192 PNG above |
| `apple-touch-icon.png` | Not in manifest; separate link on both pages (`dist/app.html:27`; `dist/landing.html:42`) | 180 × 180 PNG, 8-bit RGB |

Raster results are from the 2026-11-21 read-only PNG header probe (`python3 icon-headers.py` in the task workspace: verify the PNG signature and first `IHDR`, then read the big-endian width/height at bytes 16–23 and bit depth/colour type at 24–25). No declared size or format mismatch. A maskable icon should keep its important mark inside the central circle of radius 40% of the edge, not just fit in a 512 px square. The offline pixel read on 2026-11-21 (`python3 mask-zone.py`, using the top-left teal as background) returned: “Background RGB: (0, 127, 119); non-background pixels: 12217; max pixel-centre radius: 160.57px; safe-zone radius: 204.80px”. The mark fits that circle; actual OS crops were not tested. `scripts/precache.mjs:35–36,97–112` lists the manifest, app icons and Apple icon among built top-level static assets; that does not imply the bare `/map` shell opens offline without a pack (`scripts/precache.mjs:25–26,39–45`).

All three shortcut URLs target the app shell, not separate server pages: the worker resolves `/map` to `app.html` by path (`server/routes/assets.ts:10,34–42,100–112`). None names an area. The app replaces a regionless/coastless entry with the saved home or the landing. The home URL preserves an exact `view=conditions` and `#export`; the no-home landing URL drops both (`web/app/main.tsx:48`; `web/ports.ts:109–136,206–220`; read-only fixture assertions at `tests/test_ports.mjs:244–275`).

| Shortcut (`dist/manifest.webmanifest:1`) | What the app answers |
| --- | --- |
| Map: `/map` | Opens the saved home's map, with the default Coast view; no saved home falls back to landing (`web/ports.ts:206–220`; `web/state.ts:334–337`). |
| Conditions: `/map?view=conditions` | With a saved home it reaches the Conditions view: the query is recognised and rendered on desktop and phone. Without home it falls back to landing, not a regionless Conditions view (`web/state.ts:52,163,334–337`; `web/app/Desktop.tsx:71`; `web/app/Mobile.tsx:265`; home rules above). |
| Trip planner: `/map#export` | Opens the trip-planner dialog, not the Plan view, when a resolved region is present. It waits without opening while regionless; no home falls back to landing (`web/app/main.tsx:71–72`; `web/trip.ts:29,229–245`; read-only fixture assertions at `tests/test_app_shortcuts.mjs:54–64,78–95`; home rules above). |

## R4. Smallest proposed fix

**One follow-up unit, estimated 75–100 minutes: match the map's toolbar hint to its effective theme.** Keep a single unqualified meta tag, with the dark map background `#07131d` as the static fallback in `dist/app.html`. In `vite.config.mjs`, put the existing blocking script after that tag but still before the body, keeping its build dependency entry. Today it runs just after the charset and before the meta tag exists (`dist/app.html:3–5,20`; `vite.config.mjs:159–191`). In `web/theme-boot.ts`, have `applyTheme` also set that tag to `#f4f8f9` in effective Light and `#07131d` otherwise. This covers boot, overrides and Auto through the same existing caller (`web/theme-boot.ts:19–31`; `web/theme-choice.ts:6–18`). A media-only pair would track the OS, not the app override; it could show a light hint with a forced-dark map or a dark hint with a forced-light map.

**Offline acceptance for that unit:** update the app-specific expectation in `tests/test_v2_head.mjs:17–37` (it currently requires both tags to equal the legacy manifest value; keep the landing, icon and link assertions). Extend `tests/test_theme_choice.mjs:7–26,29–63` to assert that the existing meta tag follows the root for Auto at boot, OS changes, and both overrides against the OS, and matches the CSS tokens in R1. Run `node --test tests/test_theme_choice.mjs tests/test_v2_head.mjs` and `pnpm build` with offline dependencies; inspect the emitted app head to confirm the single tag precedes the blocking script and both precede the body. `tests/test_site_discovery.mjs:18–55,107–138` checks discovery metadata, not the theme hint; no snapshot edit is proposed.

Leave `dist/landing.html`, the manifest, icons, shortcuts, stylesheet tokens and cache policy unchanged in that unit. The landing does not use the app's boot-time theme, and the single manifest background remains a fixed launch hint; the proposed change does not promise a light splash or control an OS-owned status bar (R1–R2). No implementation was made in this report.
