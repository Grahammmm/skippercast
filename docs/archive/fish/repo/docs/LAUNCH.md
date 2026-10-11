> **Historical archive (copied 2026-10-11, SkipperCast FE-62).** This is `docs/LAUNCH.md` from the retired Fish (SLO Fish Report) repository at commit `68d7b44` (2026-10-06). It records how Fish worked and what was checked at the time, is not maintained, and may describe services, data and claims that no longer exist. SkipperCast's own documentation is the live truth: start at the [archive index](../../README.md) and [front-end design § 15](../../../../plans/front-end/design.md#15-retiring-fish). Links to Fish code, configuration or data that were not archived are shown as plain text, and identifiers that could not be published were redacted.

# SLO Fish Report launch plan

Status: locally implemented rebuild with production and browser acceptance outstanding, October 1–2, 2026. Actual collections, local Worker/PMTiles transport and source review do not establish a deployed daily operation or visual-quality acceptance.

Read [architecture](ARCHITECTURE.md), [independent review](INDEPENDENT-REVIEW.md), [product/source research](PRODUCT-DESIGN-RESEARCH.md), [shore species model](SPECIES-OPPORTUNITY.md), [history](HISTORY-PIPELINE.md), [bottom overlay](BATHYMETRY-OVERLAY.md), [habitat bridge](SKIPPERCAST-BRIDGE.md) and [domain/distribution research](../research/domain-distribution.md).

## Domain and infrastructure

1. Confirm **SLOFishReport.com** registration, exact spelling, purchase/renewal total and owner account in Namecheap. Earlier RDAP research was dated discovery, not current availability. Registration is not performed by this repo.
2. Add the zone in the intended Cloudflare account. Copy Cloudflare's assigned nameservers to Namecheap Custom DNS, wait for authoritative zone activation and verify DNS. Keep registrar ownership at Namecheap.
3. Bind only the approved county root/`www` hostnames to the independent Worker. Verify HTTPS, canonical root and `www` redirect, unknown-host rejection and preview isolation. Set the **exact** preview hostname as `PREVIEW_HOST`; do not relax the registry for arbitrary hosts.
4. Provision a dedicated Fish D1 database and configure `DB` with the actual ID in `wrangler.jsonc`. Apply **0001 and 0002**, not only initial report tables:

```sh
npm run db:local
npm run db:remote
```

Local and remote are distinct databases. Run the remote command only after checking the configured Fish binding. `0001_initial.sql` creates reports/run audits and subscription/delivery scaffolding; `0002_auxiliary.sql` creates history/ocean snapshots. Subscription tables do not activate a mail system.

5. Optionally bind a dedicated R2 bucket as `EVIDENCE` for normalized report/auxiliary archives. Raw history/GIS checkpoint upload, immutable full report history and distribution queues are separate extensions.
6. Configure account authentication, usage alerts and rollback/backup arrangements; keep any future keys in Worker secrets. The reviewed government sources and initial map layers require no paid API key. Validate actual plan/workload costs rather than treating a researched baseline as a guaranteed bill.
7. Build/deploy only with authorized account access:

```sh
npm run check
npm test
npm run build
npm run deploy
```

The Cron is hourly at UTC minute 17. **Without DB it skips collection** and serving uses dated bundled assets. Witness a real scheduled report **and** auxiliary refresh, then a distinct later run, before claiming unattended operation. Inspect original clocks and D1 outcomes; `/api/health` covers report state, not complete ocean/history/imagery readiness.

FishingReport.com remains optional. The earlier source-backed asking-price discrepancy is in distribution research; no cheaper equivalent acquisition or current price is established by this build. Do not substitute a lookalike domain or imply a broker/purchase action has occurred.

## Local data preparation

```sh
npm ci
npm run refresh
npm run refresh:ocean -- --county=slo
npm run refresh:history -- --max-files=80 --concurrency=2
npm run dev
```

Report refresh is SLO-specific. Ocean refresh uses the reviewed county binding. History's npm script includes `--all-years`, discovers actual catalogs and reuses hash-verified annual checkpoints; use `--revalidate` only for an explicit revision check. These commands update local assets and receipts, not D1 cloud state, deployment or Cron.

The original full history collection obtained all 65 advertised annual files (46215 2004–2025, 46028 1983–2025). Provider catalogs and artifact counts change; inspect the actual receipt rather than expecting fixed counts forever. Hourly Worker recent-history refresh reuses the stored seasonal reference instead of doing an annual backfill. Missing variables remain gaps.

Reviewed shore/habitat/bottom jobs:

```sh
node scripts/import-shore-habitat.mjs
node scripts/import-skippercast.mjs
../skippercast-seafloor-rollout/.venv/bin/python scripts/import-bathymetry.py --skipper-root ../skippercast-seafloor-rollout
```

Native bottom import uses existing approved read-only caches and GIS dependencies. Shore source/rule/access expiry must be independently re-reviewed; rerunning the importer is not evidence of renewed fishing eligibility. CUSP is a reviewed static extract, not an implemented automatically refreshed native land polygon. Review producer terms, source changes, original clocks, partial coverage and attribution before publishing new map assets.

## Acceptance gates

| Gate | Evidence required / known state |
| --- | --- |
| Contracts/build | Type checks, applicable offline tests and production build; no null-as-zero, forecast-as-observation or source-age relabeling. Parent final CI must match the saved commit. |
| Actual transport | Local bathymetry 206/header/PNG decoding verified through the production PMTiles reader. Still check deployed endpoint, exact bytes/ETag, both habitat regions and changed/withdrawn/expired release failures. |
| Source publication | Failed attempts cannot replace useful prior snapshots; retained layers keep original clocks and error provenance. Validate report/ocean/history separately, including storage outage/fallback. |
| Time/alerts | Pacific local days/DST, supported forecast horizon, actual selected-hour synchronization, relevant alerts and unavailable alert checks; warnings suppress favorable windows. |
| Currents/clouds | Actual WCOFS/HF frames and missing wet cells; no future radar. GOES observed acquisition/loop time, not a future forecast. Neither tide nor coarse current field clears a bar/dive entry. |
| Bottom/habitat | Partial survey footprint, nominal datum/uncertainty, transparent native-bottom gaps, separate depth and ordinal species-fit scales. Protected-water depth is physical context; habitat legal/version gates remain separate. |
| Shore | Historical ESI 2006 geometry, factual CCC approach references, full geometry protection checks, dated rule/access/source review and hazards. No promise of today's bars, troughs, access opening or fish. |
| Conditions/health | CDIP native three-hour sample time, no offshore-as-breaker claim, health sample dates unknown, surface-vs-bottom temperature distinction and dive visibility unknown. |
| History | Per-metric sample counts/gaps, collected versus available years, native UTC-hour aggregation and descriptive seasonal band; no catch model or standard climatology claim. |
| Rights | NOTICE and original manifests reflect NOAA CUSP/ESI, CCC separate state terms, NAIP dated context, GOES and USGS originals, CDIP/MUR and CDFW CC BY 4.0. No standalone restricted CSUMB product. |
| Browser design/accessibility | **Outstanding: live visual QA blocked by browser administration policy, not performed.** Authorized phone/desktop inspection must cover chart readability, map composition/attribution, keyboard/touch filters, dialogs/focus, reduced motion, outage messages and frame/tile performance. Source review is not beauty assurance. |
| Production schedule | Dedicated resources/auth, both migrations, actual report and auxiliary runs, later refresh and outage/recovery receipts. No operational schedule claim yet. |
| Distribution | Email/social/sponsors remain inactive until their separate activation gates below. No iMessage broadcast promise. |

The initial scope is recreational SLO marine planning. Three forecast points and partial bottom/habitat coverage do not produce exact location clearance. Current species/date/method rules, access, breaking surf, full return route and entry/exit conditions need their separate sources/local review. Commercial harvest eligibility/recommendations remain excluded pending independent rules work.

## Operating cadence after provisioning

Hourly code collects report conditions and auxiliary currents/GOES/recent history. Forecast, model, observed, analysis and acquired imagery clocks remain distinct. Native CDIP/WCOFS three-hour samples do not become hourly measurements; MUR is a daily analysis. The browser ages data each minute and attempts bounded recovery every ten minutes.

Human review should check source outages, key claims, current access/rules and actual local weather context before stronger timing language. Review annual archive revisions/catalogs and static source rights periodically. Prospective forecast-error analysis needs forecasts archived before validity; retrospective buoy history alone does not provide that validation. A once-per-local-date morning editorial issuance guard, versioned digest queues, a licensed bulk operator feed and automated legal/access change monitoring are future work, not implemented scheduling behavior.

Habitat proxy live-manifest checks last at most five minutes and never outlive screens; changed approved hashes require reviewed re-import. Physical historical bathymetry has no legal-screen expiry but still needs approved source identity, checksum, bounded transport and explicit nominal datum. Uptime does not establish source freshness. Keep original clocks visible when collection stops.

## Email activation

Provision a dedicated Fish sender and audience; other projects' subscribers are not Fish consent. Authenticate provider-issued DKIM/SPF/DMARC DNS. Implement double opt-in, county/mode/area/frequency preferences, consent wording/version, confirmation and pending status. Protect signup with bot/rate limits and meaningful failures.

Verify confirmation/wrong/expired tokens, preferences, unsubscribe, bounce/complaint suppression and consent recheck before each send. Delivery must use the correct report version/date, idempotency and forecast expiry; reconcile unknown provider outcomes before retry. Choose the actual volume tier before promising same-morning delivery. `/api/subscribe` remains a disabled 503 scaffold even when credentials/env fields exist. No signup or sending acceptance is claimed.

## Marketing, sponsors and county expansion

Start with useful indexed county/area/mode information, RSS, original source links and later opt-in digests. Configure Search Console/sitemap and audience measurement after domain deployment. Dated public report archives and permissioned partner promotion are future marketing work; do not label them live features.

Weekly Instagram begins with source-grounded editorial/graphic drafts approved by a human. Validate the supported professional-account login/permissions, tokens, media accessibility, publication receipt and unknown-outcome retry logic before automation. No ordinary website-to-iMessage broadcast is promised; supported-program evaluation is separate.

Keep access free. Future sponsor cards are labeled `Advertisement`, use appropriate sponsored links and aggregate reporting, and never change forecasts, species priority or habitat ranking. No purchase, outreach or social posting is performed by this checklist.

MontereyFishReport.com and SantaBarbaraFishReport.com require registration, reviewed hostname/config, actual county products/stations, independent rights/species/method/rules/access context, regional asset import, degraded-source tests, authorized visual QA and witnessed refresh. Reuse the codebase, not SLO's evidence.
