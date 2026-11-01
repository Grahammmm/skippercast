# Second active region: criteria, Morro Bay assessment and a costed plan

Decision document for SC-LAUNCH-7 (`second-region`, BUILD in the 2026-11-01 build sheet). Every fact below was read at `origin/main` 94d73d10f on 2026-11-01. This card does no data run. The build gets its own card.

## Summary

1. **The repository has no written criteria for `active`.** Neither cited document defines what `active` requires (section 1). In practice the bar is "what Morro Bay has": 10 of 26 coverage needs `ready`, plus home ports and a harbor.
2. **Morro Bay is not refined.** The roadmap's step 1 ("finish and check the Morro Bay data, brief and trip tools before anything else") still has open items that can be closed without any held right: two expired shore reviews, a stale committed evidence snapshot, and no contour receipt. These come first (section 2).
3. **Roadmap step 2, Cambria–San Simeon, cannot reach Morro Bay's bar without the held CSUMB rights that G chose not to resolve.** Without those rights it would become `active` only by relabelling data it already shows as a preview (section 4).
4. **Recommendation: Southern California** (`southern-california`) as the second active region, after the Morro Bay items. It is the only package with depth-qualified targets (11), its seabed sources are public-domain or CC0 NOAA data with no held right, and it adds 8 home ports. Three needs separate it from Morro Bay's bar, and all three can be closed with review work alone.
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
| M1 | Shore-habitat legal and access reviews have expired | `dist/regions/morro-bay/shore-habitat.geojson`: `legalReviewExpiresAt` 2026-10-04 and `accessReviewExpiresAt` 2026-10-10 (5 features each); the remaining review expires 2026-11-02. Issue #610 part 3 is open and says the cards now read "expired". | Yes: rerun the reviews. |
| M2 | Estero Bluffs shore access is missing | #610 part 3: `schemas/shore-habitat.schema.json` fixes `substrate` to `"sand"`, so rocky bluff cannot be added. This needs a format decision in the Codex lane. | Yes: schema change plus data. |
| M3 | The committed daily-evidence snapshot is stale and blocked | `dist/data/daily-evidence.json` `generated_at` is 2026-09-21T16:49:19Z and still holds Open-Meteo responses. The register's B1 action ("regenerate `daily-evidence.json` … then remove `open-meteo-api` from `KNOWN_BLOCKERS`") is still open. | Yes: engineering only. |
| M4 | No receipt for the Morro Bay contours | `docs/coast-capabilities-status.md` row "Contours: Morro Bay shelf": PREVIEW, next item "run `node --test tests/test_depth_contours.mjs` on the shipping head and record the result as a dated receipt". | Yes. |
| M5 | Tide timing is not modelled at the bar | The `tides` need reason: "Port San Luis reference water levels, not Morro Bay entrance currents." The build sheet's BUILD item `tide-bar-timing` covers this. | Yes: sibling card. |
| M6 | Bottom targets are not qualified | `bathymetry` is `partial`: "original output vertical datum and product uncertainty are unresolved; no chart-depth-qualified spot". `surveyed-bottom-targets`, `surveyed-bottom-images` and `fishing-exports` are not ready. The MLLW qualification was withdrawn on 2026-09-27. | Partly. Asking USGS or CSUMB for the datum is outbound and needs G. An original NOAA MLLW BAG over these reefs is the non-outbound route. Long pole, not a launch gate. |
| M7 | Commercial-use rights on Morro Bay's own habitat product | Data-rights register B3: `usgs-point-buchon`, `usgs-morro-bay` and `usgs-point-estero` are "needs permission" for a paid product. B2: the GFW layer is CC BY-NC. Both are in `KNOWN_BLOCKERS`. | **No.** G skipped `data-rights`. This does not affect the free edition, but it blocks charging money for Morro Bay. |

M1–M5 are the step 1 work. Each is one small card. M6 does not have to block a second region: Morro Bay is active with it open. M7 is a held right and is listed in section 4.

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
- **No new port.** `catalog/home-ports.json` has no Cambria or San Simeon port, and the package's departure harbor is Morro Bay. Making it active adds no port page, no daily answer and no new audience. Morro Bay already has a `san-simeon` local area.

So the step 2 package would become `active` only by changing its label. Its evidence would not change. G's build-sheet pattern rejects that.

## 5. Recommendation and costed plan: Southern California

### Why Southern California

- **Qualified targets.** It is the only package with a `qualified_subset` that is `ready: true`: 11 targets on native 1–4 m MLLW NOAA BAG depth with product uncertainty. That is stronger seabed evidence than Morro Bay's 132 research-only targets.
- **Clean rights.** Its seabed sources are NOAA public-domain or CC0. A paid product would not have to unwind them.
- **Audience.** It has 8 reviewed home ports: Santa Barbara, Ventura/Channel Islands, Marina del Rey, Long Beach/San Pedro, Newport Beach, Dana Point, Oceanside and San Diego. Their port pages and on-demand `get_port_report` answers already exist while the region is a preview. Activating it adds the active-only paths for these ports: sitemap listing, the 05:30 pre-generated daily answer, the no-model daily pre-router and the rules watch, plus the "Mapped area" label. All advisor paths stay dark until `TEXT_ADVISOR_ENABLED=true` is deployed, which activation does not change. This is the card's own reason for a second region: "one region is too narrow for anyone outside it to bother finding us."
- **Small gap.** Only three of Morro Bay's ten ready needs are not yet ready here.

**Risk:** the package spans Point Conception to the border. Its qualified seabed covers only Anacapa and eastern Santa Cruz Island. Mainland ports get rules, forecasts, tides, MPAs and the historical artificial-reef context, but no native mainland habitat. That still exceeds what Morro Bay's research-only targets support. It does mean "Mapped area" is island-heavy, and the build card must say so in the region's `coverage_note`, not in a banner.

### Costed plan

Units: one card is one PR or receipt. Lanes and models follow `WORKER-GUIDE.md`: routine is Sol Medium, substantial is Sol High. Times are agent wall-clock estimates, not commitments. There is no spending, no outbound message and no new host.

| # | Work | Closes | Lane / effort | Estimate |
| --- | --- | --- | --- | --- |
| **Phase 0: Morro Bay, refined (roadmap step 1, first)** | | | | |
| M1 | Rerun the shore-habitat legal and access reviews; the existing importer refreshes the expiry stamps | M1 | Sol Medium | 1 card, about 2 h |
| M2 | Allow a rocky substrate in `shore-habitat.schema.json`, then add Estero Bluffs (CCC 792–795) | M2 | Codex lane (schema owner), Sol Medium | 1 card, about 3 h |
| M3 | Regenerate the committed `daily-evidence.json` from the current pipeline and remove `open-meteo-api` from `KNOWN_BLOCKERS` (register B1) | M3 | Sol Medium | 1 card, about 2 h |
| M4 | Contour and charter test receipts on the shipping head | M4 | Sol Medium | 1 card, about 1 h |
| M5 | `tide-bar-timing` | M5 | Existing BUILD card (not new work) | n/a |
| **Phase 1: close Southern California's three gaps** | | | | |
| S1 | **dynamic-closures → ready.** Bind and hash-review the official military and security sources for the package's waters through the approved `ecfr-security` source. That means the 33 CFR 334 danger zones and restricted areas and the 33 CFR 165 security zones that intersect the package, for example around Point Mugu, San Nicolas and San Clemente. The card lists the exact sections. Add each to the Southern legal watch. The reason must name what is bound, replacing "requires direct local clearance". This also makes `season-status` ready. | 1 need, 1 capability | Sol High (legal review content) | 1 card, about 6 h |
| S2 | **wave-observations → ready.** For each of the 8 forecast contexts, record a reviewed nearshore and offshore buoy pair with a failover chain in `catalog/station-failover.json`, following the Morro Bay #611 pattern. Use `ndbc-buoys` (approved; CDIP stations are served through NDBC). Add a contract test that every configured backup has a reviewed choice. | 1 need | Sol Medium | 1 card, about 4 h |
| S3 | **substrate → ready, scoped like Morro Bay's** ("published targets have reviewed … classification"). Write a receipt showing each of the 11 qualified targets has reviewed `noaa-cinms-substrate-2006` hard-bottom classification on its exact footprint. The reviewer decides from the receipt; if it does not prove this, the need stays `partial`. | 1 need | Sol High | 1 card, about 4 h |
| **Phase 2: flip and verify** | | | | |
| B6 | Write the `active` bar into `contracts.py`: an `active` region must have every Morro Bay bar need `ready` and at least one home port. Add a failing-first regression test that a region missing one of these is rejected. Flip `southern-california` to `active` and rebuild `dist/regions/index.json`. | the flag | Sol High | 1 card, about 4 h |
| B7 | Exercise the active-only paths for the 8 ports (sitemap listing, `pregenerateDaily`, the `dailyFlow` pre-router, `watchRuleSources`) on the region's feed in tests with the advisor enabled, confirm their port pages still render, then record a feed receipt (regions.md step 6). This does not set `TEXT_ADVISOR_ENABLED` in production. | verification | Sol Medium | 1 card, about 3 h |
| B8 | US-L2: region-aware landing readings once a second region is active | front-end backlog | FE lane | existing backlog item |

**Total:** Phase 0 is 4 cards (about 8 h). Phase 1 is 3 cards (about 14 h). Phase 2 is 2 cards (about 7 h) plus US-L2.

**Dependency order:**

- M1–M4 run first and in parallel.
- S1–S3 run in parallel with each other. Each is independent of Phase 0 but should merge after it, so the roadmap order is kept.
- B6 depends on S1–S3. B7 depends on B6.

Each card is reviewed by a different model from its author, under the standing exact-head merge rule. Nothing here touches secrets, outbound messages or publication beyond the normal on-merge deploy.

### Why the alternatives are worse

| Alternative | Why it ranks below Southern California |
| --- | --- |
| Cambria–San Simeon (roadmap step 2) | The habitat gap needs the held `csumb-cambria` right, which is not viable. Without it the only change is the label. It has no home port, so it adds no audience. |
| Point Sal–Point Conception (roadmap step 3) | 0/26 needs ready and no home port. Its habitat context uses `usgs-csmp-seafloor-character` (B3). A dated USCG review put all four of its research polygons inside a launch-hazard area during the listed windows. Rules, forecasts, tides and closures would all need review from scratch. |
| Monterey–Point Sur or Santa Cruz–Monterey Bay | Each has one port and an audience, but 0/26 needs are ready. Its seabed is CSMP (B3) on NAVD88, with no full VDatum conversion or per-cell uncertainty. That means about 10 review cards before it reaches the bar. |
| Northern packages (Bodega to Crescent City) | 0/26 ready; each needs the full regulation, forecast, tide and closure review. |
| Flip Cambria anyway and call it done | That is a disclaimer by another name. The flag would claim a reviewed coverage the evidence does not have. |

## 6. G decision needed before the build card starts

The roadmap's order is the owner's ("The owner sets the order"). Recommending Southern California moves it ahead of steps 2 and 3. That is a product decision for G, not for a builder:

1. **SOCAL (recommended).** Do Phase 0, then Southern California as the second active region.
   - Pros: the only package with qualified targets; clean rights; 8 ports of new audience; three reviewable gaps.
   - Cons: departs from the north-then-south order; island-heavy seabed.
2. **NORTH.** Keep the roadmap and make Cambria–San Simeon active on conditions, rules and tides only.
   - Pros: follows the written order; cheapest (about 1 card for wave-observations).
   - Cons: no habitat north of 35.56° N while the CSUMB rights stay skipped; no new port or audience; substrate cannot honestly reach `ready`.
3. **REFINE-ONLY.** Do Phase 0 now and defer the second region.
   - Pros: no reorder.
   - Cons: "live" stays a one-region demo.

Phase 0 (M1–M4) is needed under every option and can start now.
