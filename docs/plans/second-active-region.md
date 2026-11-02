# Second active region: criteria, Morro Bay assessment and a costed plan

Decision document for SC-LAUNCH-7 (`second-region`, BUILD in the 2026-11-01 build sheet). Every fact below was read at `origin/main` 94d73d10f on 2026-11-01. This card does no data run. The build gets its own card.

## Summary

1. **The repository has no written criteria for `active`.** Neither cited document defines what `active` requires (section 1). In practice the bar is "what Morro Bay has": 10 of 26 coverage needs `ready`, plus home ports and a harbor.
2. **Morro Bay is not refined.** The roadmap's step 1 ("finish and check the Morro Bay data, brief and trip tools before anything else") still has open items that need no held right: two expired shore reviews, a stale committed evidence snapshot, and no contour receipt. These come first (section 2). The expired reviews are dated **human** reviews awaiting owner confirmation. An agent can prepare the evidence, but only the owner can renew them.
3. **Roadmap step 2, Cambria–San Simeon, cannot reach Morro Bay's bar without the held CSUMB rights that G chose not to resolve.** Without those rights it would become `active` only by relabelling data it already shows as a preview (section 4).
4. **Recommendation: Southern California** (`southern-california`) as the second active region, after the Morro Bay items. It is the only package with depth-qualified targets (11), its seabed sources are public-domain or CC0 NOAA data with no held right, and it adds 8 home ports. Three needs separate it from Morro Bay's bar:
   - Two (`wave-observations`, `substrate`) close with bounded engineering and review work.
   - The third, `dynamic-closures`, does **not** close through review alone. Its gap is operational Navy range status around the islands, and the static legal text is already watched. The plan adds a fail-closed reader for the official USCG notices. Even then, live clearance stays a trip-time check, so `ready` needs an owner-approved scope (S1 and decision 2 in section 6).
   - **This reorders the roadmap.** The owner sets the order, and the roadmap lists Southern California at no step. G has to accept the reorder before the build card starts (section 6).

## 1. What `active` requires versus `preview`

### What the cited documents actually say

`docs/product/data-confidence.md`, section "Coverage states", defines need states, not region states:

> | `ready` | An **approved** source is bound and the region's reviewed evidence says it covers the need. |
> | `partial` | An approved source is bound but covers the need only in part; the `reason` says what is missing. |
> | `research` | Only **candidate** sources are bound: promising, but records, precision or rights still need review. |
> | `missing` | No reviewed source is bound. |

> A product capability (for example `surveyed-bottom-targets`, `fishing-exports`, `season-status`) is ready only when every need it depends on is `ready` or `not-applicable`; otherwise its `gaps` list names the blocking needs. Readiness describes reviewed source coverage only; current freshness and legal permission are checked separately.

On regions, it says only this:

> Regions themselves are `active` (Morro Bay & Avila) or `preview` (every other package) in `dist/regions/index.json`.

`docs/coast-capabilities-status.md` does not mention region status at all. Its `PREVIEW` is a different idea, a feature status:

> | PREVIEW | The code and documents are merged at the pinned commit, and a merge or commit record is cited. Whether captains can see the feature on the served site, and whether its data is current, is not proven here. |

It also states "**No row on this page is LIVE.**"

**Finding:** the brief assumed these two documents quote the `active` criteria. They do not. Both are also pinned to older commits (data-confidence to c3fe61e5, merge of #854).

### The closest written rule

`docs/regions.md`, step 5:

> Preview status allows explicit geological context and regional forecasts while unavailable targets stay empty. Published fishing targets require ready depth, substrate and MPA coverage, or a hash-validated qualified subset that proves depth/substrate for its exact footprints while keeping the other gates. Partial source coverage remains partial. A production-ready forecast also needs fresh observations, advisories and confidence checks at runtime.

Morro Bay itself does not meet the "published fishing targets" clause. Its `bathymetry` need is `partial`, and its coverage note reads: "The 132 published coordinates and bottom views are research-only."

### What the code does with the flag

| Where | Effect of `active` |
| --- | --- |
| `schemas/region.schema.json`, `platform/contracts.py` `_region_shape` | `status` is one of `active`, `preview` or `draft`. Nothing checks how ready the needs are. |
| `platform/build.py` | Only a `preview` package may publish empty atlas, habitat and bottom-index placeholders. An `active` package must ship real files. |
| `server/advisor/pages/port.ts` `portExists`, `server/routes/advisor.ts` `/ports/:id` | **Not gated on `active`.** A port page exists for every `catalog/home-ports.json` port whose region is built and not `draft`, so preview-region ports (including Southern California's 8) already have pages. The route calls `portPage` with no status check. |
| `server/advisor/tools/get_port_report.ts` | **Not gated on `active`.** The model's `get_port_report` answers for any catalog port, so a preview port's "what's biting" question is already answered on demand. |
| `server/advisor/pages/port.ts` `activePortIds`, `server/advisor/pages/sitemap.ts` | Only active-region ports are listed in the sitemap. |
| `server/advisor/answers/reports.ts` `activePorts`, `pregenerateDaily`, `dailyFlow` | Only active-region ports get the 05:30 pre-generated daily answer, and only they are answered by the daily pre-router without a model call. A preview port's plain question goes to the model and `get_port_report`. |
| `server/advisor/admin/rules.ts` `activeRegions`, `watchRuleSources` | The daily rules-watch slot reads only active regions' feeds for regulation changes. |
| `server/advisor/gate.ts`, `server/routes/advisor.ts` `ADVISOR_PATHS`, `TEXT_ADVISOR_ENABLED` | Independent of region status. Port pages (`/ports/*`), advisor answers and the other gated advisor paths 404 until `TEXT_ADVISOR_ENABLED=true` is deployed. Activating a region does not lift this. |
| `web/ports.ts` | The port chooser labels a port "Mapped area" (active) or "Regional preview". |
| `docs/plans/front-end/dev-plan.md` backlog US-L2 | "Second active region on the landing: region-aware readings once another region leaves preview" is waiting on this card. |

### The bar this plan uses

No document defines it, so this plan measures candidates against what Morro Bay has today:

- **Needs (the 10 `ready` in Morro Bay):** substrate, protected-areas, regulations, dynamic-closures, wind-forecast, wave-forecast, wave-observations, tides, wind-ensemble, wave-ensemble.
- **Capabilities:** season-status, conditions-outlook and tide-chart are ready.
- **Ports:** at least one reviewed home port and harbor, so the active-only advisor paths (sitemap, daily pre-generation, the daily pre-router, rules watch) have something to serve.
- **Status flag:** it is changed only after the needs are reviewed `ready`. Flipping it first would be a relabel, not a fix.

G should adopt this bar, or a stricter one, in writing. The build card then adds it as a validation rule (see B6 in section 5) so the flag cannot drift from the evidence again.

## 2. Morro Bay against roadmap step 1

**It is not refined.** The roadmap says: "Morro Bay is the only active region until it is refined. 1. Morro Bay, refined. Finish and check the Morro Bay data, brief and trip tools before anything else." Open items, with evidence:

| # | Outstanding item | Evidence at 94d73d10f | Closeable without a held right? |
| --- | --- | --- | --- |
| M1 | Shore-habitat legal and access reviews have expired | `dist/regions/morro-bay/shore-habitat.geojson`: `legalReviewExpiresAt` 2026-10-04 and `accessReviewExpiresAt` 2026-10-10 (5 features each); the remaining source review expires 2026-11-02. Issue #610 part 3 is open and says the cards now read "expired". The dates come from `REVIEWS` in `scripts/collect_shore_habitat.py` (lines 48–57): "Dated human reviews, carried from fish's shore source review of 2026-10-03 … pending owner confirmation. Renew only after re-reading the sources by hand." The importer "copies them verbatim … a fresh download cannot renew a source, access or legal review" (lines 12–14), and `docs/data-sources.md` says the same. The register rows `noaa-esi-2006` and `ccc-access-points` also await owner confirmation. | Yes, but **not by an agent alone.** An agent can prepare a re-read dossier. Renewal is a substantive human review by the owner, and the review windows are 24 h (legal), 7 days (access) and 30 days (source). |
| M2 | Estero Bluffs shore access is missing | #610 part 3: `schemas/shore-habitat.schema.json` fixes `substrate` to `"sand"`, so rocky bluff cannot be added. This needs a format decision in the Codex lane. | Yes: schema change plus data. |
| M3 | The committed daily-evidence snapshot is stale and blocked | `dist/data/daily-evidence.json` `generated_at` is 2026-09-21T16:49:19Z and still holds Open-Meteo responses. The register's B1 action ("regenerate `daily-evidence.json` … then remove `open-meteo-api` from `KNOWN_BLOCKERS`") is still open. | Yes: engineering only. |
| M4 | No receipt for the Morro Bay contours | `docs/coast-capabilities-status.md` row "Contours: Morro Bay shelf": PREVIEW, next item "run `node --test tests/test_depth_contours.mjs` on the shipping head and record the result as a dated receipt". | Yes. |
| M5 | Tide timing is not modelled at the bar | The `tides` need reason: "Port San Luis reference water levels, not Morro Bay entrance currents." The build sheet's BUILD item `tide-bar-timing` covers this. | Yes: sibling card. |
| M6 | Bottom targets are not qualified | `bathymetry` is `partial`: "original output vertical datum and product uncertainty are unresolved; no chart-depth-qualified spot". `surveyed-bottom-targets`, `surveyed-bottom-images` and `fishing-exports` are not ready. The MLLW qualification was withdrawn on 2026-09-27. | Partly. Asking USGS or CSUMB for the datum is outbound and needs G. An original NOAA MLLW BAG over these reefs is the non-outbound route. Long pole, not a launch gate. |
| M7 | Commercial-use rights on Morro Bay's own habitat product | Data-rights register B3: `usgs-point-buchon`, `usgs-morro-bay` and `usgs-point-estero` are "needs permission" for a paid product. B2: the GFW layer is CC BY-NC. Both are in `KNOWN_BLOCKERS`. | **No.** G skipped `data-rights`. This does not affect the free edition, but it blocks charging money for Morro Bay. |

M1–M5 are the step 1 work. M2–M4 are each one small agent card, and M5 is the existing `tide-bar-timing` BUILD card. M1 has a human gate (see the Phase 0 plan below). All of M1–M5 must be done before the second region's status flag changes (B6). M6 does not have to block a second region: Morro Bay is active with it open. M7 is a held right and is listed in section 4.

A structural note on M1: a 24-hour legal review and a 7-day access review cannot be kept current by occasional hand review. Readers drop a run only when its 30-day source review expires, so the shorter reviews will show "expired" again soon after any renewal. Whether those windows are right is the owner's call. This plan does not change them.

## 3. Gap table: every package against the bar

Generated from `dist/regions/*/coverage.json` and `catalog/home-ports.json`:

| Package | Status | Needs ready | Morro Bay's ready needs not ready here | Capabilities ready | Published targets (qualified) | Home ports |
| --- | --- | --- | --- | --- | --- | --- |
| `morro-bay` | active | 10/26 | none | season-status, conditions-outlook, tide-chart | 132 (0) | 2 |
| `cambria-san-simeon` | preview | 8/26 | substrate (partial), wave-observations (partial) | season-status, conditions-outlook, tide-chart | 0 (0) | 0 |
| `southern-california` | preview | 7/26 | substrate (partial), dynamic-closures (partial), wave-observations (partial) | conditions-outlook, tide-chart | 11 (11) | 8 |
| `monterey-point-sur` | preview | 0/26 | all 10 (substrate research; rest partial/research) | none | 0 (0) | 1 |
| `santa-cruz-monterey-bay` | preview | 0/26 | all 10 | none | 0 (0) | 1 |
| `point-reyes-pigeon` | preview | 0/26 | all 10 | none | 0 (0) | 1 |
| `bodega-point-reyes` | preview | 0/26 | all 10 | none | 0 (0) | 1 |
| `fort-bragg-point-arena` | preview | 0/26 | all 10 | none | 0 (0) | 1 |
| `shelter-cove-north-mendocino` | preview | 0/26 | all 10 | none | 0 (0) | 1 |
| `humboldt-bay-cape-mendocino` | preview | 0/26 | all 10 | none | 0 (0) | 1 |
| `crescent-city` | preview | 0/26 | all 10 | none | 0 (0) | 1 |
| `point-arguello-conception` | preview | 0/26 | all 10 | none | 0 (0) | 0 |
| `south-big-sur-san-simeon` | preview | 0/26 | all 10 | none | 0 (0) | 0 |
| `big-sur-coast` | preview | 0/26 | all 10 | none | 0 (0) | 0 |
| `point-arena-bodega` | preview | 0/26 | all 10 | none | 0 (0) | 0 |
| `trinidad-klamath` | preview | 0/26 | all 10 | none | 0 (0) | 0 |

Only two packages are close to the bar: Cambria–San Simeon and Southern California. Every other package needs its regulations, forecasts, tides and protected areas reviewed from scratch before it is even comparable, so they are out of the running for a second region.

Two drift findings, not fixed on this card:

- The README coverage table omits `trinidad-klamath`.
- `docs/regions.md` calls Trinidad–Klamath a **draft**, but `regions/trinidad-klamath/region.json` and the generated index say `preview`.

## 4. Held data rights

G chose to SKIP `data-rights` (build sheet, SKIP list). Any step that needs one of these rights resolved is therefore not viable:

| Right (register row) | Source | Who depends on it | Effect |
| --- | --- | --- | --- |
| `csumb-cambria`: "unresolved … **needs permission** … Not shipped" | CSUMB Block05 native bathymetry | Cambria–San Simeon bathymetry and substrate north of about 35.56° N | **Blocks roadmap step 2's habitat product.** `research/receipts/csumb-original-source-policy-review.json`: for-profit use is "not authorized without express CSUMB permission"; `website_redistribution_cleared: false`. The archive ledger's San Simeon–Cambria acquisition step depends on CSUMB SCC/BSS blocks 04–06, and all three are under this hold. |
| `ds1091-charter-grounds`: "permission-required" | 2011 charter-ground interviews | Charter layers north of Point Estero (the "excluded Cambria and charter layers" in the roadmap) | Not viable. No plan here uses it. |
| B3: CSUMB co-produced USGS releases (`usgs-point-buchon`, `usgs-morro-bay`, `usgs-point-estero`, `usgs-csmp-seafloor-character`) | USGS public domain, but the CSUMB policy says commercial use needs permission | Morro Bay's whole habitat product; Cambria's survey habitat; the Monterey, Santa Cruz, Point Conception and Bodega/Point Reyes context | Not a blocker for the free personal-use edition: Morro Bay is already active on these sources. It **is** a blocker before SkipperCast charges money, and it applies to Morro Bay too. |
| B4: `pmep-hapc` (terms unreviewed) | PMEP habitat compilation | Big Sur and South Big Sur–San Simeon | It is the only habitat layer those packages have. |
| B2: `gfw-effort` (CC BY-NC) | Commercial AIS effort | Morro Bay only | Not a second-region issue. |

**Southern California depends on none of these.** Its seabed sources are `noaa-h13093`, `noaa-h13323` and `noaa-cinms-bathymetry-2025` (all CC0 1.0), plus `noaa-cinms-substrate-2006`, `noaa-socal-gea`, `cdfw-kelp-2016` and `cdfw-artificial-reefs` (US public domain or facts). Its only `KNOWN_BLOCKERS` entries are the shared runtime ones in B1 and B6.

### Why Cambria–San Simeon is not reachable

- **What is already ready:** forecasts, tides, rules and closures are ready in the preview.
- **Native survey north of Cambria:** the only non-held fine survey in the package is Point Estero. It covers 35.530–35.542° N (3 survey-habitat features), which lies inside Morro Bay's own fishing bounds (35.05–35.56° N). Every fine grid north of that is CSUMB and held.
- **Substrate can only reach `partial`.** Morro Bay's substrate is `ready` because "published targets have reviewed USGS seafloor classification". Cambria has no published targets and cannot get any north of 35.56° N without the held grids, and USGS SIM 3327 is "not a 2 m seabed classification".
- **No new port.** `catalog/home-ports.json` has no Cambria or San Simeon port, and the package's departure harbor is Morro Bay. Making it active adds no port to the sitemap or the daily pre-generation, and no new audience. Morro Bay already has a `san-simeon` local area.

So the step 2 package would become `active` only by changing its label. Its evidence would not change. G's build-sheet pattern rejects that.

## 5. Recommendation and costed plan: Southern California

### Why Southern California

- **Qualified targets.** It is the only package with a `qualified_subset` that is `ready: true`: 11 targets on native 1–4 m MLLW NOAA BAG depth with product uncertainty. That is stronger seabed evidence than Morro Bay's 132 research-only targets.
- **Clean rights.** Its seabed sources are NOAA public-domain or CC0. A paid product would not have to unwind them.
- **Audience.** It has 8 reviewed home ports: Santa Barbara, Ventura/Channel Islands, Marina del Rey, Long Beach/San Pedro, Newport Beach, Dana Point, Oceanside and San Diego. Their port pages and on-demand `get_port_report` answers already exist while the region is a preview. Activating it adds the active-only paths for these ports: sitemap listing, the 05:30 pre-generated daily answer, the no-model daily pre-router and the rules watch, plus the "Mapped area" label. All advisor paths stay dark until `TEXT_ADVISOR_ENABLED=true` is deployed, which activation does not change. This is the card's own reason for a second region: "one region is too narrow for anyone outside it to bother finding us."
- **Small gap.** Only three of Morro Bay's ten ready needs are not yet ready here. Two of them close with bounded work. The third (`dynamic-closures`) is the hard one; see S1.

**Risk:** the package spans Point Conception to the border. Its qualified seabed covers only Anacapa and eastern Santa Cruz Island. Mainland ports get rules, forecasts, tides, MPAs and the historical artificial-reef context, but no native mainland habitat. That still exceeds what Morro Bay's research-only targets support. It does mean "Mapped area" is island-heavy, and the build card must say so in the region's `coverage_note`, not in a banner.

### Costed plan

Units: one card is one PR or receipt. Lanes and models follow `WORKER-GUIDE.md`: routine is Sol Medium, substantial is Sol High. Times are agent wall-clock estimates, not commitments. **Owner time is not estimated**: rows marked *owner gate* wait on G for an unknown time, and that wait is the critical path. There is no spending, no outbound message and no new host.

| # | Work | Closes | Lane / effort | Estimate |
| --- | --- | --- | --- | --- |
| **Phase 0: Morro Bay, refined (roadmap step 1, first)** | | | | |
| M1a | Prepare a shore re-read dossier: fetch the NOAA ESI layer, the CCC access inventory and item terms, and the CDFW Central Coast rules page, saving responses under `var/` with `--save-sources`. Diff each against the 2026-10-03 hashes and list anything changed (closures, archived points, rule text) for each of the 5 runs and 8 access points. It must **not** edit `REVIEWS` or the register. | evidence only | Sol Medium | 1 card, about 2 h |
| M1b | **Owner gate.** G (or a human G names) re-reads the sources against the dossier and records a dated decision for each review: renew, or drop the run or access point. Only a human can supply this; an agent rerun cannot. The register rows `noaa-esi-2006` and `ccc-access-points` are confirmed at the same time. | M1 acceptance | Owner (G) | owner time, unknown wait |
| M1c | After M1b, copy the owner's dated decisions into `REVIEWS` and rebuild offline with `--sources`. The PR cites the M1b decision record and must change no date the owner did not give. | M1 | Sol Medium | 1 card, about 1 h |
| M2 | Allow a rocky substrate in `shore-habitat.schema.json`, then add Estero Bluffs (CCC 792–795). The new run carries no review date until it passes the same owner gate as M1b. | M2 | Codex lane (schema owner), Sol Medium; owner gate for its review dates | 1 card, about 3 h, plus owner review |
| M3 | Regenerate the committed `daily-evidence.json` from the current pipeline and remove `open-meteo-api` from `KNOWN_BLOCKERS` (register B1) | M3 | Sol Medium | 1 card, about 2 h |
| M4 | Contour and charter test receipts on the shipping head | M4 | Sol Medium | 1 card, about 1 h |
| M5 | `tide-bar-timing` | M5 | Existing BUILD card (not new work) | n/a |
| **Phase 1: close Southern California's three gaps** | | | | |
| S1a | **Discovery receipt for operational range status.** The static legal text is already watched: `jurisdictions/california-southern.json` binds San Clemente (33 CFR 165.1141), San Nicolas (334.980), Point Mugu (334.1126) and other 334 sections. Binding more sections would not change the gap reason ("Navy/security access around islands requires direct local clearance"). The repo already treats operational state as a USCG notice matter: `research/catalog/san-miguel-naval-danger-zone.json` says "current operation status requires Local Notice to Mariners or radio confirmation", and `research/receipts/point-conception-launch-hazard-review.json` uses a USCG Broadcast Notice to Mariners. Make a bounded read of the official USCG District 11 Local Notices to Mariners and Broadcast Notices on `www.navcen.uscg.gov`. That host is already in the approved `harbor-authority` source, so no host is added. Record, with hashes, whether the notices name the scheduled operations, areas and times for each 33 CFR area in the package, and how often they are issued. **This is unverified today.** The receipt decides whether S1b is possible. | evidence only | Sol High | 1 card, about 3 h |
| S1b | **Only if S1a finds usable notices:** add a reviewed candidate source and a fail-closed adapter. Each run binds the current LNM issue and the active BNMs to the 33 CFR areas. An area with a listed operation, an unreadable or out-of-period notice, or an unmatched area is shown as **held: check before entering**, never as clear. Runtime failure publishes no clearance. Tests: a failing-first test that a stale or missing notice yields `held` for every Navy area; a notice naming an area and time window yields `held` inside the window. Source review goes through the normal approval. | operational schedule | Sol High | 1–2 cards, about 8–10 h |
| S1c | **Owner scope gate.** Even with S1b, a weekly notice and its broadcasts are not live clearance. San Clemente operations, for example, are also announced by radio. `dynamic-closures` can say `ready` only if G accepts this scope: "scheduled Navy operations from official USCG notices, fail-closed; live clearance remains a trip-time check". That matches the trip-time limit `docs/regulations.md` already states ("live Navy clearance is not [checked]"). If G does not accept it, or S1a finds nothing usable, the need **stays `partial`**, and `season-status` stays not ready. Southern California then becomes active only if G explicitly approves an active bar that admits that one `partial` need with the island Navy areas held (section 6, decision 2). The reason text is never edited to close the gap. | `dynamic-closures`, `season-status` | Owner (G) | owner time, unknown wait |
| S2 | **wave-observations → ready.** For each of the 8 forecast contexts, record a reviewed nearshore and offshore buoy pair with a failover chain in `catalog/station-failover.json`, following the Morro Bay #611 pattern. Use `ndbc-buoys` (approved; CDIP stations are served through NDBC). Add a contract test that every configured backup has a reviewed choice. | 1 need | Sol Medium | 1 card, about 4 h |
| S3 | **substrate → ready, scoped like Morro Bay's** ("published targets have reviewed … classification"). Write a receipt showing each of the 11 qualified targets has reviewed `noaa-cinms-substrate-2006` hard-bottom classification on its exact footprint. The reviewer decides from the receipt; if it does not prove this, the need stays `partial`. | 1 need | Sol High | 1 card, about 4 h |
| **Phase 2: flip and verify** | | | | |
| B6 | Write the `active` bar G approves into `contracts.py`: an `active` region must have every bar need `ready` (or the exact exception G approved in S1c) and at least one home port. Add a failing-first regression test that a region missing one of these is rejected. Flip `southern-california` to `active` and rebuild `dist/regions/index.json`. | the flag | Sol High | 1 card, about 4 h |
| B7 | Exercise the active-only paths for the 8 ports (sitemap listing, `pregenerateDaily`, the `dailyFlow` pre-router, `watchRuleSources`) on the region's feed in tests with the advisor enabled, confirm their port pages still render, then record a feed receipt (regions.md step 6). This does not set `TEXT_ADVISOR_ENABLED` in production. | verification | Sol Medium | 1 card, about 3 h |
| B8 | US-L2: region-aware landing readings once a second region is active | front-end backlog | FE lane | existing backlog item |

**Agent total:** Phase 0 is 5 agent cards (about 9 h) plus the existing `tide-bar-timing` card. Phase 1 is 4–5 agent cards (about 19–21 h, or about 11 h if S1a finds nothing usable). Phase 2 is 2 cards (about 7 h) plus US-L2. **Owner gates:** M1b, M2's review dates, and S1c, plus G's roadmap decision. Their waits are not estimated and set the real calendar.

**Dependency order:**

- M1a, M2, M3 and M4 run first and in parallel. M1b waits on M1a; M1c waits on M1b. M5 runs on its own card.
- S1a, S2 and S3 run in parallel with each other and with Phase 0. S1b waits on S1a. S1c waits on S1b, or on S1a if it finds nothing usable. Phase 1 merges after Phase 0, so the roadmap order is kept.
- B6 depends on M1c, M2–M5, S1c, S2 and S3. B7 depends on B6.
Each card is reviewed by a different model from its author, under the standing exact-head merge rule. Nothing here touches secrets, outbound messages or publication beyond the normal on-merge deploy.

### Why the alternatives are worse

| Alternative | Why it ranks below Southern California |
| --- | --- |
| Cambria–San Simeon (roadmap step 2) | The habitat gap needs the held `csumb-cambria` right, which is not viable. Without it the only change is the label. It has no home port, so it adds no audience. |
| Point Sal–Point Conception (roadmap step 3) | 0/26 needs ready and no home port. Its habitat context uses `usgs-csmp-seafloor-character` (B3). A dated USCG review put all four of its research polygons inside a launch-hazard area during the listed windows. Rules, forecasts, tides and closures would all need review from scratch. |
| Monterey–Point Sur or Santa Cruz–Monterey Bay | Each has one port and an audience, but 0/26 needs are ready. Its seabed is CSMP (B3) on NAVD88, with no full VDatum conversion or per-cell uncertainty. That means about 10 review cards before it reaches the bar. |
| Northern packages (Bodega to Crescent City) | 0/26 ready; each needs the full regulation, forecast, tide and closure review. |
| Flip Cambria anyway and call it done | That is a disclaimer by another name. The flag would claim a reviewed coverage the evidence does not have. |

## 6. G decisions needed

The roadmap's order is the owner's ("The owner sets the order"). Recommending Southern California moves it ahead of steps 2 and 3. These are decisions for G, not for a builder. The roadmap choice is not the only human gate: M1b (the shore re-read) and M2's review dates also need the owner, under every option.

**Decision 1: roadmap order (before Phase 1 starts).**

1. **SOCAL (recommended).** Do Phase 0, then Southern California as the second active region.
   - Pros: the only package with qualified targets; clean rights; 8 ports of new audience; two gaps close with bounded work.
   - Cons: departs from the north-then-south order; island-heavy seabed; `dynamic-closures` depends on S1a's unverified finding and on decision 2.
2. **NORTH.** Keep the roadmap and make Cambria–San Simeon active on conditions, rules and tides only.
   - Pros: follows the written order; cheapest (about 1 card for wave-observations).
   - Cons: no habitat north of 35.56° N while the CSUMB rights stay skipped; no new port or audience; substrate cannot honestly reach `ready`.
3. **REFINE-ONLY.** Do Phase 0 now and defer the second region.
   - Pros: no reorder.
   - Cons: "live" stays a one-region demo.

**Decision 2: `dynamic-closures` scope for Southern California (after S1a/S1b, before B6).**

1. **Accept the notice scope (recommended if S1b ships):** `ready` means scheduled Navy operations from official USCG notices, fail-closed, with live clearance a trip-time check, the limit `docs/regulations.md` already states.
2. **Approve an active bar with one held exception:** the need stays `partial`, the island Navy areas show as held, and B6 encodes that exact exception.
3. **Decline both:** Southern California stays `preview` until a live operational source exists. Phase 0 and S2/S3 still stand.

Agent-only work that can start now under every option: M1a, M2's schema change, M3 and M4. M1b waits on the owner; M1c waits on M1b.
