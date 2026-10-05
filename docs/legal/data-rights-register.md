# Data-rights register

**Status:** first complete pass, 2026-09-28; Text Advisor rows added 2026-10-04 (owner/counsel to confirm). Not legal advice; rows marked *needs permission* or *unknown* need the owner (and, where noted, counsel).
**Machine-readable source of truth:** `rights.commercial_use`, `rights.attribution_required` and `rights.commercial_note` on every entry in [`catalog/sources.json`](../../catalog/sources.json).
**CI gate:** [`tests/contract/test_commercial_sources.py`](../../tests/contract/test_commercial_sources.py).

This register answers one question per dataset: *may a paid, $10/month SkipperCast use it?* That is a different question from the one `rights.license` already answers (may it be redistributed in the free personal-use edition?). A source can be freely redistributable and still not cleared for a commercial product.

It was built from `catalog/sources.json`, [`NOTICE.md`](../../NOTICE.md), [`docs/data-sources.md`](../data-sources.md), every asset bound in `regions/*/region.json`, the runtime provider bindings in those files, and the third-party hosts called from `src/`, `server/` and `dist/*.js`.

## How the gate works

`tests/contract/test_commercial_sources.py` collects every *usage*:

- every asset bound in a non-draft `regions/*/region.json` (`assets.*`), mapped to catalog sources in the test's `ASSET_SOURCES` table. Empty placeholders (no targets, areas or views) carry no third-party data; search plans inherit the sources of their recorded `input_receipts`; `protected_areas` files must point at CDFW ds582; species ecology dossiers are original SkipperCast summaries that cite agency pages;
- every runtime provider binding (`intelligence.providers.*`, `pipeline_sources.*`, and the wind/wave forecast bindings the scheduled pipeline samples);
- every runtime call to a known third-party service host in `src/`, `server/` and `dist/*.js` (Open-Meteo APIs, OpenStreetMap tiles, the NOAA chart display service).

It fails when an asset is bound but unmapped, when a mapping omits a source the file itself cites (for example an Open-Meteo URL inside `daily-evidence.json`), or when the set of usages whose source is not `"allowed"` differs from `KNOWN_BLOCKERS`.

`KNOWN_BLOCKERS` is an explicit, dated allow-list. Each entry names the register row below and the exact usages it covers. CI stays green today because the list equals the real offender set; **adding** an offender (a new asset, region or call that depends on a blocked source) fails CI, and **resolving** one also fails CI until its entry is removed. When you resolve a blocker: change the source's `commercial_use` (or remove the usage), delete the `KNOWN_BLOCKERS` entry, and update the blocker section here in the same PR.

Adding a new source to `catalog/sources.json` now requires `commercial_use` and `attribution_required` (`skippercast.platform.contracts.load_catalogs` rejects entries without them).

## Launch blockers

Every item here must be closed, licensed or removed before SkipperCast charges money.

### B1 — Open-Meteo free API (mostly resolved)

- **Sources:** `open-meteo-api`. (`noaa-gefs-members` is resolved: members now come directly from NOAA's AWS Open Data bucket, public domain.)
- **Terms:** Open-Meteo API data are CC BY 4.0, but the [free API terms](https://open-meteo.com/en/terms) restrict access to non-commercial use.
- **Resolved:** the GEFS ensemble is built from NOAA directly (`src/skippercast/forecast/ensemble.py`, #51); the browser ocean-current request was replaced by NOAA WCOFS, and the legacy monitor now calls SkipperCast's own `/api/om` (#54); the Content-Security-Policy no longer allows `marine-api.open-meteo.com`.
- **Remaining:** the committed Morro Bay `data/daily-evidence.json` snapshot still contains Open-Meteo model responses from before the switch.
- **Action:** regenerate `daily-evidence.json` from the current pipeline, then remove `open-meteo-api` from `KNOWN_BLOCKERS`.
- **Owner:** Engineering.

### B2 — Global Fishing Watch CC BY-NC

- **Source:** `gfw-effort` — [Global AIS-based Apparent Fishing Effort Dataset v3.0](https://doi.org/10.5281/zenodo.14982712), CC BY-NC 4.0.
- **Where:** `data/commercial-ais-effort.geojson`, bound as `assets.commercial_ais` in Morro Bay and drawn by `dist/commercial-ais.js`. (`data/ais-evidence.json` only links the archive in a research note.)
- **Action:** either request a commercial licence from Global Fishing Watch, or unbind the layer from `regions/morro-bay/region.json` and move the file to research receipts.
- **Owner:** Owner (licence email) · Engineering (removal).

### B3 — CSUMB co-produced seafloor data

- **Sources:** `usgs-point-buchon`, `usgs-morro-bay`, `usgs-point-estero`, `usgs-csmp-seafloor-character` (and the already-withheld `csumb-cambria`).
- **Terms:** the USGS release metadata for these products state U.S. public domain, but the surveys were produced with the CSUMB Seafloor Mapping Lab, whose [data-library policy](https://csumb.edu/undersea/sfml-data-library/) permits non-profit use with acknowledgment and requires express permission for for-profit use (noted in `docs/archive/statewide-buildout.md`). Which terms govern a USGS-published release is unresolved, so these are recorded as *needs permission* rather than cleared.
- **Where:** the whole Morro Bay habitat product (`data/atlas.json`, `data/habitat-regions.json`, `regions/morro-bay/bottom/index.json`, `regions/morro-bay/search-plans.json`, charter search outlines in `data/charter-grounds.json`), Cambria survey habitat, and the Monterey, Santa Cruz, Point Conception, Point Reyes/Bodega and Fort Ross survey-habitat context.
- **Action:** one email to CSUMB SFML asking for written permission for commercial use of derivatives of the named USGS/CSMP releases (or confirmation that the USGS public-domain release governs); counsel to review the answer.
- **Owner:** Owner.

### B4 — PMEP habitat compilation (terms unreviewed)

- **Source:** `pmep-hapc` — PMEP West Coast nearshore rocky-reef HAPC via PSMFC's map service.
- **Where:** `regions/big-sur-coast/survey-habitat.geojson`, `regions/south-big-sur-san-simeon/survey-habitat.geojson` and their search plans.
- **Action:** find and record PMEP/PSMFC terms of use; if they are not clearly open, ask PSMFC or unbind the two layers.
- **Owner:** Owner (terms check) · Engineering (catalog update).

### B5 — Landing-report facts

- **Source:** `landing-reports` (SoCalFishReports and landing pages).
- **Terms:** only dated catch facts and links are published, and facts are not copyrightable in the US, but the publisher's terms of use, the automated daily collection and compilation rights have not been reviewed for a paid product (guide §10.3).
- **Where:** `data/charter-grounds.json`, `data/daily-evidence.json` (Morro Bay).
- **Action:** counsel review of the publisher's terms; consider asking the publisher for permission.
- **Owner:** Owner (counsel).

### B6 — OpenStreetMap tile service

- **Source:** `osm-tiles` (runtime service; not in the catalog because no data need covers a basemap).
- **Terms:** OSM data are ODbL (commercial use allowed with attribution), but the tile servers are donated capacity under the [OSMF tile usage policy](https://operations.osmfoundation.org/policies/tiles/), with no service guarantee and limits on heavy use. Not a sound basis for a paid app.
- **Where:** fallback basemap in `dist/chart-map.js` (and the unused `dist/map-test-common.js`).
- **Action:** self-hosted PMTiles basemap or a commercial tile provider before paid launch (guide P4-05).
- **Owner:** Engineering.

## Runtime services outside the catalog

| Service | Id | Licence / terms | Attribution required | Commercial use OK | Where used in app | Action | Owner |
| --- | --- | --- | --- | --- | --- | --- | --- |
| OpenStreetMap standard tiles | `osm-tiles` | ODbL data; OSMF tile usage policy | yes | **unknown** | `dist/chart-map.js`, `dist/map-test-common.js`, `server/security-headers.ts` (CSP) | [Blocker B6](#b6--openstreetmap-tile-service) | Engineering |
| NOAA Chart Display Service (ENC WMS) | `noaa-enc-display` | US public domain | no (credit requested) | yes | `dist/chart-map.js`, `dist/map-test-common.js` | None | Engineering |

The browser also calls NWS (`api.weather.gov`) and NOAA CO-OPS (`api.tidesandcurrents.noaa.gov`) directly; they are public domain and covered by the `nws-weather` and `noaa-tides` rows.

## Text Advisor: personal content and processors

Added 2026-10-04 (TA-C5). The Text Advisor ([plan](../plans/text-advisor/README.md)) takes content from people (skippers' and anglers' photos, videos and counts) and passes personal data through outside services. These rows answer the same question for that content and those services: may a paid SkipperCast use them, on what terms. They are not in `catalog/sources.json` and not checked by the CI gate. Every legal judgment here is **owner/counsel to confirm**; the engineering facts (what is stored, where, for how long) are from the code as built, with the security side in the [threat model § 9](threat-model.md#9-text-advisor).

| Content or service | Id | Licence / terms | Attribution required | Commercial use OK | Where used in app | Action | Owner |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Skipper-submitted content: photos, videos, count-board photos and count texts | `advisor-skipper-content` | The skipper's own content. Photos and videos: consent by text when the boat is registered (SK-2: "OK for SkipperCast to post your photos and videos on our Instagram and Facebook, always credited and tagged to {boat}? Reply YES."), stored as `advisor_boats.consent_photos_at` with `consent_message_id` (the message row stays; its text is nulled after 180 days). Revocable: "revoke" / "stop posting my photos" sets `consent_revoked_at` and rejects every unposted post; posted items stay on Instagram and Facebook until removed by hand. Counts become reports that publish on the skipper's confirmation, without photo consent | yes: credited and tagged to the boat | **owner/counsel to confirm**: whether a text YES is a sufficient licence for a paid product's posts; whether people shown in a skipper's photo (crew, customers) need their own release; the engine-approved morning Stories (TA-S5) | `server/advisor/intake/skippers.ts` (consent), `server/advisor/intake/reports.ts`, `server/advisor/social/drafts.ts`, `server/advisor/social/publish.ts`, `server/advisor/social/stories.ts`, `server/advisor/pages/boat.ts`, `server/advisor/pages/port.ts`, `GET /media/*` | Counsel review of the consent wording and the Story auto-approval; keep the consent message row for as long as a post exists | Owner (counsel) |
| Angler-submitted photos shared with credit | `advisor-angler-photos` | The angler's own photo. Consent: a YES within 24 hours to "can we share this with credit?" (AC-1), then the credit asked once ("anonymous" allowed); the photo becomes `publish_state='queued'` with `credit` and an `angler_photo` review the admin decides. No dedicated consent record: the evidence is the inbound YES (text nulled after 180 days) and the review (deleted 90 days after the decision). Revocable through FORGET ME, which deletes the photo and its unposted posts; posted items stay until removed by hand | yes: the credit the angler gave, or none if anonymous | **owner/counsel to confirm** | `server/advisor/intake/anglers.ts`, `server/advisor/tools/share_angler_photo.ts`, `server/advisor/social/drafts.ts`, `server/advisor/pages/` | Counsel review; consider a durable consent record (media id, message id, time) like the skippers' | Owner (counsel) |
| Meta Platform Terms: Instagram and Facebook content and data | `meta-platform` | [Meta Platform Terms](https://developers.facebook.com/terms/) and Developer Policies, Instagram Terms of Use. Received through the Graph API: DMs, keyword comments, Instagram-scoped ids, collaborator usernames and post insights, used only to answer and to publish; a data-deletion instructions URL (`/privacy.html#text-advisor`) is required. Publishing: our own posts of consented content, with collaborator invites the boat accepts. Nobody else's Instagram content is reposted | no | **owner/counsel to confirm**; the messaging permissions need Meta App Review ([runbook](../operations/runbooks/advisor-meta-app-review.md)) | `server/advisor/social/*.ts`, `server/advisor/channels/instagram.ts`, `GET`/`POST /api/advisor/inbound/meta` | App Review; counsel to confirm the use, the 24-hour messaging window and the deletion flow against the Platform Terms | Owner (counsel) |
| Anthropic API (customer content sent to the model) | `anthropic-api` | [Anthropic Commercial Terms of Service](https://www.anthropic.com/legal/commercial-terms) and Usage Policy. Sent: the message, recent turns, the contact's brief (display name, home port, boat), tool results and photos; never a phone number. Disclosed in `/privacy.html#text-advisor` | no | yes (a commercial API); **owner/counsel to confirm** the data-processing terms and retention for these inputs | `server/advisor/engine.ts`, `server/advisor/vision/claude.ts`, `server/advisor/prompts/`, `server/advisor/answers/` (daily answers), `server/advisor/social/drafts.ts` (captions) | Confirm a data processing addendum is in place; set a workspace spend limit | Owner |
| Twilio (only after a port) | `twilio` | [Twilio Terms of Service](https://www.twilio.com/en-us/legal/tos) and Acceptable Use Policy; A2P 10DLC brand and campaign registration for US texting. Numbers, message text and MMS media pass through Twilio, which keeps message logs | no | **owner/counsel to confirm**; not in use until a port | `server/advisor/channels/twilio.ts`, `/api/advisor/inbound/twilio*` | Before a port: 10DLC registration (TA-O3), data processing addendum, message-log retention setting ([port to Twilio](../operations/runbooks/advisor-port-to-twilio.md)) | Owner |
| Apple iMessage and the BlueBubbles relay | `apple-imessage-relay` | Apple Account and iCloud terms for the dedicated account; the open-source BlueBubbles server (its licence to record). Every text passes through Apple (iMessage) or the carrier (SMS); the iPhone, the Mac and, with Messages in iCloud on, Apple keep every conversation and attachment as received, outside SkipperCast's retention and FORGET ME (threat model § 9.2) | no | **unknown, owner/counsel to confirm**: whether Apple's terms allow a consumer Apple Account to carry a business messaging service (suspension risk, threat model § 9.9) | `server/advisor/channels/bluebubbles.ts`, `/api/advisor/inbound/bluebubbles/:token`, [relay setup](../operations/runbooks/advisor-relay-setup.md) | Counsel review; Keep Messages 30 days on both devices; delete the conversation on the relay after a FORGET ME; align the privacy notice | Owner (counsel) |
| Cloudflare (storage and processing) | `cloudflare-storage` | Cloudflare's subscription agreement and data processing addendum. Holds the advisor's D1 tables, the private R2 bucket `skippercast-advisor-media` (originals, derived images, exports), the queues, Workers Logs (request URLs and redacted `advisorLog` lines) and Analytics Engine counts; Tunnel and Access front the relay | no | yes; **owner/counsel to confirm** the data processing addendum covers this personal data | `wrangler.jsonc`, `scripts/wrangler_config.mjs` (`ADVISOR_BUCKET`), `server/advisor/retention.ts`, `server/advisor/media.ts` | Confirm the addendum; note the Workers Logs retention in the privacy notice if counsel asks | Owner |

The vision provider on the owner's own Hermes machine (TA-V2, in progress) will add a row when it ships: photos would then also leave Cloudflare for that host.

## Catalog sources

One row per entry in `catalog/sources.json`. "Where used" lists usages found by the CI gate (asset paths are relative to `dist/`; `region.json:*` rows are runtime bindings present in every published region). "Licence" is the redistribution review already recorded in the catalog.

| Dataset | Source id | Licence | Attribution required | Commercial use OK | Where used in app | Action | Owner |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Point Buchon bathymetry and seafloor character | `usgs-point-buchon` | US public domain | yes | **needs permission** | `data/atlas.json`<br>`data/charter-grounds.json`<br>`data/habitat-regions.json`<br>`regions/morro-bay/bottom/index.json`<br>`regions/morro-bay/search-plans.json` | [Blocker B3](#b3--csumb-co-produced-seafloor-data) | Owner |
| Morro Bay bathymetry and seafloor character | `usgs-morro-bay` | US public domain | yes | **needs permission** | `data/atlas.json`<br>`data/charter-grounds.json`<br>`data/habitat-regions.json`<br>`regions/morro-bay/bottom/index.json`<br>`regions/morro-bay/search-plans.json` | [Blocker B3](#b3--csumb-co-produced-seafloor-data) | Owner |
| Point Estero bathymetry and seafloor character | `usgs-point-estero` | US public domain | yes | **needs permission** | `data/atlas.json`<br>`data/charter-grounds.json`<br>`data/habitat-regions.json`<br>`regions/cambria-san-simeon/search-plans.json`<br>`regions/cambria-san-simeon/survey-habitat.geojson`<br>`regions/morro-bay/bottom/index.json`<br>`regions/morro-bay/search-plans.json` | [Blocker B3](#b3--csumb-co-produced-seafloor-data) | Owner |
| San Simeon geology and bathymetric contours | `usgs-san-simeon` | US public domain | no (credit requested) | yes | `regions/cambria-san-simeon/geology.geojson` | None | Engineering |
| NOAA hydrographic surveys and uncertainty grids | `noaa-bag` | CC0 1.0 | no (credit requested) | yes | `regions/bodega-point-reyes/search-plans.json`<br>`regions/bodega-point-reyes/survey-habitat.geojson`<br>`regions/humboldt-bay-cape-mendocino/search-plans.json`<br>`regions/humboldt-bay-cape-mendocino/survey-habitat.geojson`<br>`regions/point-arena-bodega/search-plans.json`<br>`regions/point-arena-bodega/survey-habitat.geojson` | None | Engineering |
| NOAA National Bathymetric Source Modeling tiles | `noaa-nbs-modeling` | CC0-1.0 recorded in inspected contributor tables | no (credit requested) | yes | Not shipped (catalog or research only) | None | Engineering |
| NOAA BlueTopo bathymetry | `noaa-bluetopo` | U.S. public domain/CC0-1.0 product; check each contributor RAT for source restrictions | no (credit requested) | **unknown** | Not shipped (catalog or research only) | Rights review before any use | Owner |
| West Coast seafloor induration 2017 | `noaa-west-coast-substrate` | metadata-review-needed | no (credit requested) | **unknown** | Not shipped (catalog or research only) | Rights review before any use | Owner |
| California seafloor camera and sample observations | `usgs-camera-samples` | dataset-review-needed | no (credit requested) | **unknown** | Not shipped (catalog or research only) | Rights review before any use | Owner |
| CDFW Predicted Nearshore Benthic Substrates of California R7 | `cdfw-ds3091-predicted-substrate` | CC BY 4.0 | yes | yes | Not shipped (catalog or research only) | Keep attribution in NOTICE and licences page | Engineering |
| California Marine Protected Areas DS582 | `cdfw-mpas` | CC BY 4.0 | yes | yes | `data/charter-grounds.json`<br>`data/daily-evidence.json`<br>`data/protected-areas.geojson`<br>`regions/big-sur-coast/protected-areas.geojson`<br>`regions/monterey-point-sur/protected-areas.geojson`<br>`regions/point-arena-bodega/protected-areas.geojson`<br>`regions/point-arguello-conception/protected-areas.geojson`<br>`regions/point-reyes-pigeon/protected-areas.geojson`<br>`regions/santa-cruz-monterey-bay/protected-areas.geojson`<br>`regions/shelter-cove-north-mendocino/protected-areas.geojson`<br>`regions/south-big-sur-san-simeon/protected-areas.geojson`<br>`regions/southern-california/protected-areas.geojson` | Keep attribution in NOTICE and licences page | Engineering |
| NOAA West Coast federal groundfish areas | `noaa-groundfish-areas` | US public domain | no (credit requested) | yes | `data/regulations-mendocino.json`<br>`data/regulations-northern.json`<br>`data/regulations-san-francisco.json`<br>`data/regulations.json`<br>`regions/southern-california/regulations.json` | None | Engineering |
| California DBW Boating Facilities (launch ramps, hoists, beach launches) | `ca-dbw-boating-facilities` | Facts only | no (credit requested) | yes | `catalog/launch-points.json` → `dist/regions/*/launch-points.json` | None | Engineering |
| CDFW recreational ocean fishing rules | `cdfw-rules` | Facts only | no (credit requested) | yes | `data/daily-evidence.json`<br>`data/regulations-mendocino.json`<br>`data/regulations-northern.json`<br>`data/regulations-san-francisco.json`<br>`data/regulations.json`<br>`regions/southern-california/regulations.json` | None | Engineering |
| Federal security-zone rules | `ecfr-security` | US public domain | no (credit requested) | yes | `data/charter-grounds.json`<br>`data/regulations-mendocino.json`<br>`data/regulations-northern.json`<br>`data/regulations-san-francisco.json`<br>`data/regulations.json`<br>`regions/southern-california/regulations.json` | None | Engineering |
| NOAA GFS atmospheric forecast through Open-Meteo | `noaa-gfs` | CC BY 4.0 | no (credit requested) | yes | `region.json:source_bindings.wind-forecast` | Update the catalog record: retrieval now uses SkipperCast NOAA/ECMWF tiles, not Open-Meteo | Engineering |
| ECMWF IFS atmospheric forecast through Open-Meteo | `ecmwf-ifs` | CC BY 4.0 | yes | yes | `region.json:source_bindings.wind-forecast` | Update the catalog record: retrieval now uses SkipperCast NOAA/ECMWF tiles, not Open-Meteo | Engineering |
| NOAA GFS Wave 0.16° through Open-Meteo | `noaa-gfs-wave` | CC BY 4.0 | no (credit requested) | yes | `region.json:source_bindings.wave-forecast` | Update the catalog record: retrieval now uses SkipperCast NOAA/ECMWF tiles, not Open-Meteo | Engineering |
| ECMWF WAM 9 km through Open-Meteo | `ecmwf-wam` | CC BY 4.0 | yes | yes | `region.json:source_bindings.wave-forecast` | Update the catalog record: retrieval now uses SkipperCast NOAA/ECMWF tiles, not Open-Meteo | Engineering |
| NDBC station observations and wave spectra | `ndbc-buoys` | US public domain | no (credit requested) | yes | `data/daily-evidence.json`<br>`region.json:intelligence.providers.spectra`<br>`regions/southern-california/observations.json` | None | Engineering |
| NWS forecasts, advisories and station observations | `nws-weather` | US public domain | no (credit requested) | yes | `data/daily-evidence.json` | None | Engineering |
| NOAA CO-OPS water levels and predictions | `noaa-tides` | US public domain | no (credit requested) | yes | `data/daily-evidence.json` | None | Engineering |
| West Coast HF radar surface currents | `ioos-hfr` | US public domain | no (credit requested) | yes | `data/daily-evidence.json` | None | Engineering |
| JPL MUR sea surface temperature analysis | `mur-sst` | US public domain | yes | yes | `data/daily-evidence.json` | Keep attribution in NOTICE and licences page | Engineering |
| Aqua MODIS ocean chlorophyll | `modis-chlorophyll` | US public domain | yes | yes | `data/daily-evidence.json` | Keep attribution in NOTICE and licences page | Engineering |
| Regional ocean circulation and subsurface forecasts | `regional-roms` | dataset-review-needed | no (credit requested) | **unknown** | Not shipped (catalog or research only) | Rights review before any use | Owner |
| Satellite kelp canopy histories | `kelpwatch` | ODbL-1.0 | yes | **unknown** | Not shipped (catalog or research only) | Rights review before any use | Owner |
| FRAM fishery-independent groundfish surveys | `noaa-survey-catches` | dataset-review-needed | no (credit requested) | **unknown** | Not shipped (catalog or research only) | Rights review before any use | Owner |
| OBIS species occurrence records | `obis-occurrences` | dataset-review-needed | yes | **unknown** | Not shipped (catalog or research only) | Rights review before any use | Owner |
| West Coast recreational fisheries statistics | `recfin` | dataset-review-needed | no (credit requested) | **unknown** | Not shipped (catalog or research only) | Rights review before any use | Owner |
| Published local landing trip facts | `landing-reports` | Facts only | yes | **unknown** | `data/charter-grounds.json`<br>`data/daily-evidence.json` | [Blocker B5](#b5--landing-report-facts) | Owner |
| Official local sportfishing fleet pages | `operator-identities` | Facts only | no (credit requested) | yes | `data/ais-evidence.json`<br>`data/charter-grounds.json` | None | Engineering |
| MarineCadastre historical AIS broadcasts | `noaa-ais` | CC0 1.0 | no (credit requested) | yes | `data/ais-evidence.json` | None | Engineering |
| Apparent fishing effort from AIS | `gfw-effort` | CC BY-NC 4.0 | yes | **no** | `data/commercial-ais-effort.geojson` | [Blocker B2](#b2--global-fishing-watch-cc-by-nc) | Owner |
| Official harbor and entrance information | `harbor-authority` | Facts only | no (credit requested) | yes | `data/daily-evidence.json` | None | Engineering |
| CSUMB Block05 Cambria native bathymetry | `csumb-cambria` | unresolved | yes | **needs permission** | Not shipped (catalog or research only) | Rights review before any use | Owner |
| 2011 charter fishing-ground interviews DS1091 | `ds1091-charter-grounds` | permission-required | yes | **needs permission** | Not shipped (catalog or research only) | Rights review before any use | Owner |
| NOAA / IOOS HF radar 1 km and 6 km | `noaa-hfr-thredds` | US public domain | no (credit requested) | yes | `region.json:intelligence.providers.hfr` | None | Engineering |
| NOAA West Coast Operational Forecast System | `noaa-wcofs` | US public domain | no (credit requested) | yes | `region.json:intelligence.providers.regional_current` | None | Engineering |
| NOAA GEFS wind ensemble (NOAA AWS Open Data) | `noaa-gefs-members` | Public domain | yes | yes | `region.json:intelligence.providers.wind_ensemble` | — | — |
| NOAA GEFS Wave exceedance probabilities | `noaa-gefs-wave-prob` | US public domain | no (credit requested) | yes | `region.json:intelligence.providers.wave_ensemble` | None | Engineering |
| CDFW Southern California artificial reef guide (2001) | `cdfw-artificial-reefs` | Facts only | no (credit requested) | yes | `regions/southern-california/reef-context.geojson` | None | Engineering |
| NOAA Southern California Groundfish Exclusion Areas | `noaa-socal-gea` | US public domain | no (credit requested) | yes | `regions/southern-california/groundfish-exclusions.geojson` | None | Engineering |
| NOAA/NCCOS California benthic substrate compilation | `noaa-cinms-substrate-2006` | US public domain | no (credit requested) | yes | `regions/southern-california/search-plans.json`<br>`regions/southern-california/survey-habitat.geojson` | None | Engineering |
| NCCOS Channel Islands merged multibeam bathymetry | `noaa-cinms-bathymetry-2025` | CC0 1.0 | no (credit requested) | yes | `regions/southern-california/bottom/index.json`<br>`regions/southern-california/qualified-bottom/manifest.json`<br>`regions/southern-california/search-plans.json`<br>`regions/southern-california/survey-habitat.geojson` | None | Engineering |
| CDFW 2016 aerial kelp canopy and subsurface classification | `cdfw-kelp-2016` | Facts only | yes | yes | `regions/southern-california/search-plans.json`<br>`regions/southern-california/survey-habitat.geojson` | Keep attribution in NOTICE and licences page | Engineering |
| NOAA H13093: Vicinity of Anacapa Island | `noaa-h13093` | CC0 1.0 | no (credit requested) | yes | `regions/southern-california/atlas.json`<br>`regions/southern-california/bottom/index.json`<br>`regions/southern-california/qualified-bottom/manifest.json`<br>`regions/southern-california/search-plans.json` | None | Engineering |
| NOAA H13323: Cavern Point to Smugglers Cove | `noaa-h13323` | CC0 1.0 | no (credit requested) | yes | `regions/southern-california/atlas.json`<br>`regions/southern-california/bottom/index.json`<br>`regions/southern-california/qualified-bottom/manifest.json`<br>`regions/southern-california/search-plans.json` | None | Engineering |
| NOAA CPC ENSO Diagnostic Discussion | `noaa-cpc-enso` | US public domain | no (credit requested) | yes | Not shipped (catalog or research only) | None | Engineering |
| NOAA Geo-Polar Blended night SST, 5 km | `noaa-blended-sst` | US public domain | no (credit requested) | yes | `region.json:pipeline_sources.sst` | None | Engineering |
| NOAA NPP/NOAA-20 merged OCI chlorophyll, near real time | `noaa-viirs-merged-chlorophyll` | US public domain | no (credit requested) | yes | `region.json:pipeline_sources.chlorophyll` | None | Engineering |
| NOAA NDBC HFRNet US West Coast hourly 6 km surface currents | `noaa-ndbc-hfr-uswc-6km` | US public domain | no (credit requested) | yes | `region.json:pipeline_sources.currents` | None | Engineering |
| Offshore Cape Mendocino bathymetry and seafloor character | `usgs-cape-mendocino` | US public domain | no (credit requested) | yes | `regions/humboldt-bay-cape-mendocino/search-plans.json`<br>`regions/humboldt-bay-cape-mendocino/survey-habitat.geojson` | None | Engineering |
| California State Waters Map Series seafloor character (DS 781) | `usgs-csmp-seafloor-character` | US public domain | yes | **needs permission** | `regions/bodega-point-reyes/search-plans.json`<br>`regions/bodega-point-reyes/survey-habitat.geojson`<br>`regions/monterey-point-sur/search-plans.json`<br>`regions/monterey-point-sur/survey-habitat.geojson`<br>`regions/point-arena-bodega/search-plans.json`<br>`regions/point-arena-bodega/survey-habitat.geojson`<br>`regions/point-arguello-conception/search-plans.json`<br>`regions/point-arguello-conception/survey-habitat.geojson`<br>`regions/santa-cruz-monterey-bay/search-plans.json`<br>`regions/santa-cruz-monterey-bay/survey-habitat.geojson` | [Blocker B3](#b3--csumb-co-produced-seafloor-data) | Owner |
| PMEP West Coast nearshore rocky-reef HAPC compilation | `pmep-hapc` | unreviewed | yes | **unknown** | `regions/big-sur-coast/search-plans.json`<br>`regions/big-sur-coast/survey-habitat.geojson`<br>`regions/south-big-sur-san-simeon/search-plans.json`<br>`regions/south-big-sur-san-simeon/survey-habitat.geojson` | [Blocker B4](#b4--pmep-habitat-compilation-terms-unreviewed) | Owner |
| Open-Meteo forecast, marine and ensemble APIs (free tier) | `open-meteo-api` | CC BY 4.0 | yes | **no** | `data/daily-evidence.json` | [Blocker B1](#b1--open-meteo-free-api-mostly-resolved) | Owner |

## Web and code dependencies

Third-party code shipped to browsers (Leaflet, MapLibre, PMTiles and any fonts) is listed with its licence text on the in-app licences page and in `NOTICE.md`; those licences (BSD/OFL) allow commercial use with notice. SkipperCast's own code is under `LICENSE`, whose personal-use terms are a separate launch blocker handled by the licensing ADR (guide P0-11).

## Maintenance

- Re-review this register whenever a source, region asset or runtime provider is added; the CI gate forces the mapping, not the legal judgment.
- Record decisions (emails, licences, counsel advice) by date in the relevant blocker section and update `rights.commercial_note`.
