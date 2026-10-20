# Pelagic search context that follows the selected hour (design only)

Status: design, October 20, 2026. No UI code. The build card (PS-16) builds
only what this document allows. Scope: albacore and bluefin, the two pelagic
targets of the active region (`regions/morro-bay/region.json` `species`).
The other targets in `SPECIES_METHODS` (yellowfin, dorado, yellowtail) follow
the same rules when a region lists them; they are not designed here.

## 1. The problem and the answer in one paragraph

Pelagic anglers want to know where the water looks worth a look at the hour
they plan to fish, and want that to change as the hour changes. SkipperCast
already publishes the physical inputs per region in `habitat-dynamics.json`
(method `pelagic-context-v1`, `src/skippercast/pipeline/habitat_dynamics.py`),
and `species_support` (L91-100) deliberately returns `habitat_score: None` and
`catch_probability: None`. The web app reads the SST analysis and WCOFS
layers from that manifest for Water temp and Currents
(`web/map/habitat-feed.ts` L175, L207) but reads nothing of
`species_methods`. This design adds a **per-species context readout**: a
small set of separate evidence lines, each naming its product, grid, time and
age. Only the WCOFS forecast lines change with the selected hour. There is
**no combined score, no rank number, no probability, and no ordering of
places**. A search priority stays off until the validation test in section 4
passes, and today that test cannot even be run (section 4.4).

## 2. What is shown (acceptance 1)

### 2.1 Where it appears

- A **Pelagic context** section in the point readout when the selected species
  is albacore or bluefin and the user taps a water point inside the region's
  `bounds`. It reads the cell of each product that contains the point (the
  nearest native cell centre, accepted only within half a cell spacing). It
  never takes a value from a neighbouring cell, never interpolates and never
  fills a gap.
- No new map layer, tint, outline, pin or numbered marker. The existing Water
  temp (`web/map/layers.ts` L105) and Currents (L142) layers are unchanged.
  If PS-16 or a later card wants a map element, it is a new entry in
  `web/map/layers.ts` under the layer-card rules (legend, basis sentence
  naming product, grid and age, attribution, time tag, age limit past which
  it is withheld) and it still may not shade "good" water.
- `web/confidence.ts` is unchanged. Its fish badge stays `unknown`
  (L87-88): this readout is water context, not a fish claim.

### 2.2 Lines for albacore

Each line carries its own source name, grid spacing, sample or valid time and
age. Lines are listed in this order every time; the order is fixed by type,
never by value.

1. **Reference temperature range: 12–21 °C (54–70 °F).** Shown with its
   stated meaning, copied from `SPECIES_METHODS["albacore"]["range_meaning"]`
   (habitat_dynamics.py L30-31): "99% of SST encountered by tagged
   eastern-Pacific juvenile albacore in the cited synthesis; not an optimum
   or a presence/absence boundary." Life stage: juvenile eastern-Pacific
   albacore. Source: NOAA's 2024 HMS FMP Amendment 8 Appendix F (`HMS_DOC`,
   L26). Its "age" is the source's publication date (October 2024); it is a
   literature reference, not a measurement of today's water.
2. **Satellite surface temperature (observed context).** The `sst-analysis`
   layer at the point: temperature, its `analysis_error_c`, and one neutral
   phrase: "inside the reference range", "outside the reference range" or
   "no value at this point". Source and grid from the layer (Morro Bay today:
   `noaa-blended-sst`, Geo-Polar Blended night L4 analysis, 0.05°), the
   analysis date and its age in hours. Label: "Analysis, partly interpolated;
   dated context, not a forecast for the selected hour." Withheld past the
   layer's `max_age_hours` (72 h today) or when status is not `ok`/`retained`.
3. **Supported contrast (satellite).** `temperature_gradient_c_per_km` and
   `thermal_contrast_supported` at the point (computed in `gradients`,
   L103-126). Wording by flag value:
   - `1`: "Temperature changes here by more than the summed analysis error of
     the neighbouring cells."
   - `0`: "Temperature change here is not larger than the summed analysis
     error. This does not show that there is no front"
     (docs/dynamic-species-method.md L35).
   - missing: "Not computable here (a neighbouring cell or its error is
     missing)."
   This is the only line that may use the word "supported", and only for the
   satellite analysis, because it is the only product with a per-cell error.
4. **Model surface water at the selected hour (forecast).** From
   `wcofs-surface-forecast` at the frame chosen by `frame_for_time` (L58-88):
   model surface temperature with the same neutral range phrase as line 2,
   the model gradient magnitude in °C/km labelled "model gradient, no error
   estimate", and surface current speed and direction. Source: NOAA WCOFS,
   0.04° regular grid, NAD83, cycle time, valid time and cycle age. Label:
   "Model surface water; not bottom flow, boat drift or fish movement." It is
   never merged with line 2: two products, two lines, two times.
5. **Chlorophyll (observed context).** `chlorophyll-observation` at the point,
   or "no valid pixel (cloud or retrieval gap)", with date and age; withheld
   past `max_age_hours` (96 h today). No range or comparison: there is no
   species reference for it.
6. **Fixed limit line**, from `species_support`'s `reason` (L100): "Physical
   search context only; no locally validated catch or absence inference."

### 2.3 Lines for bluefin

1. **Reference temperature range: none.** The line says so in words:
   "No numeric reference range. No locally validated single
   surface-temperature optimum. Fish use multiple depths and forage fields."
   (`SPECIES_METHODS["bluefin"]`, L34-35, `temperature_range_c: None`; life
   stage "Size and fish depth unresolved"; source NOAA species account). The
   build must keep it missing. It must not borrow albacore's 12–21 °C,
   yellowfin's 64–88 °F, a published fishing-report range or any other
   number, and no code path may compute an inside/outside phrase for bluefin
   (`species_support` already returns `temperature_within_reference_range:
   None` when the band is `None`, L96).
2. to 6. As albacore lines 2–6, except that temperatures are shown as values
   only, with no range phrase.

### 2.4 Never shown

- A combined, weighted or summed value of any of the lines; a 0–100 or any
  other score; a probability; a rank or order number; "best", "hot",
  "feeding", "fish here", "bite" or any presence wording; green/red or
  good/bad colouring of a line.
- A value from another date presented as the selected hour's value, or an
  analysis that post-dates a selected past hour (`frame_for_time` L82-86).
- Any value when the region's manifest fails the existing tile checks in
  `web/map/habitat-feed.ts` (one failing tile refuses the whole layer).

### 2.5 Build notes for PS-16

- Read `species_methods` from the same manifest `habitat-feed.ts` already
  loads; the manifest only carries the region's own species (L414). Extend
  the SST reader to carry `temperature_gradient_c_per_km` and
  `thermal_contrast_supported` (today it keeps temperature and error only,
  L177-187) and add a WCOFS temperature/gradient reader beside the current
  one.
- Port `frame_for_time` and `species_support` semantics to TypeScript with
  parity tests on shared fixtures, including the stale, out-of-span,
  missing-step and bluefin-`None` cases. The browser's forecast admission
  must also respect `selectedCurrent`'s retrieval limit (fetched + 6 h) and
  the 36 h cycle limit (`packages/coast/src/state/current-layer.ts`).
- Copy passes `node scripts/check_copy.mjs`; method names (and "datum") go in
  the disclosure, not the line.

## 3. How future hours work (acceptance 3)

- **Only WCOFS moves with the hour.** The forecast fields that drive any
  change are the `wcofs-surface-forecast` frame's `temperature_c`, `u_mps`,
  `v_mps` and the derived `temperature_gradient_c_per_km` (fields list,
  habitat_dynamics.py L296). Nothing else in the readout changes when the
  time dock moves forward.
- **Steps and horizon.** WCOFS publishes three-hourly frames f000–f072 from
  one cycle (L275); the collector keeps the latest populated cycle of today
  or yesterday. The selected hour uses the nearest frame within 90 minutes
  and inside the actual valid span (L74-81). A missing step stays missing;
  there is no interpolation across it and no extrapolation past the last
  frame.
- **Age.** A forecast is withheld once its cycle is older than 36 h (L375,
  checked at L71-73) and in the browser also once the fetch is older than
  6 h. Because a cycle's frames run to cycle + 72 h but expire at cycle +
  36 h, the reachable future is "up to the last frame of a cycle no older
  than 36 h", which is less than 72 h from now except right after a new
  cycle.
- **Past the horizon** the forecast lines say "No ocean forecast at the
  selected hour" and disappear. Longer weather and wave horizons (GFS, GFS
  Wave, ECMWF) never extend them, and the last frame is never held.
- **Observed products do not move.** For any selected hour the satellite
  SST, contrast and chlorophyll lines show the latest frame at or before that
  hour, keep their own date and are labelled observed context (L82-86). They
  are not relabelled as a forecast for the trip.
- **No independence claim.** WCOFS assimilates SST and HF radar
  (habitat_dynamics.py L300), so agreement between lines 2 and 4 is not
  confirmation and is never presented as such.

## 4. Validation plan (acceptance 2)

The readout in section 2 needs no validation: it shows dated measurements and
literature references with their stated meaning. Validation is required only
before anything is shown as a **priority**: any ordering, highlighting,
"look here first" wording or number that prefers one place or hour over
another. N-4 (the owner decision on any number on a place) applies on top of
this: passing the test does not by itself approve a number.

### 4.1 What would be tested

A pre-registered rule, written into
`docs/plans/pelagic-context/preregistration.md` (a later card) before any
outcome data is examined, and not changed afterwards:

- Albacore: a cell is flagged when the product's temperature is inside
  12–21 °C **and** its gradient is at least G °C/km. G is fixed in the
  pre-registration; the starting value is the retired overlay's 0.05 °C/km
  "Priority 1" display heuristic (docs/research/morro-bay-tuna.md L69-73),
  stated as an untested prior, not a finding.
- Bluefin: gradient at least G only. No temperature term, because there is
  no reference range. If bluefin fails, it gets no priority; a range is never
  added to make it pass.
- Satellite analysis and each WCOFS lead-time bucket (0–24 h, 24–48 h,
  48–72 h) are tested separately, using forecasts archived **before** their
  valid time (docs/dynamic-species-method.md L59). A bucket or product that
  fails gets no priority even if another passes.

### 4.2 Outcome data that SkipperCast holds or could lawfully hold

| Data | Status | Usable for | Limit |
| --- | --- | --- | --- |
| Morro Bay and Avila landing-report facts (SoCalFishReports daily boat totals), `history/*.json` on the `data` branch | Held. At `data` commit 858deae33 (2026-10-19): 149 distinct reports, 47 dates, 2026-08-22 to 2026-10-18. Albacore: 0. Bluefin: 3 reports on 3 dates, none with a named ground | Dated, port-level presence of positive reports only | No positions, no zero-catch effort, selected sample (docs/bite-evidence.md); publisher terms unreviewed for paid use (Blocker B5, docs/legal/data-rights-register.md) |
| Daily satellite SST samples in the same history files | Held since 2026-09-21 | The environmental side of a satellite test | One product (Geo-Polar 0.05°); MUR and earlier products are not comparable |
| WCOFS frames at issue time | **Not held.** The `conditions` branch keeps one commit, so past cycles are overwritten | Forecast-hour tests | Needs an archive (NEEDS G 2) |
| NOAA public HMS and albacore troll logbook products (InPort item 20828 describes catch and effort from 1964) | Not held; public access level and aggregation unverified | Positioned catch and effort at the published resolution | Must pass a Skill 1 source review first (NEEDS G 1); a coarse aggregate can only validate at its own resolution |
| RecFIN / CDFW published CPFV aggregates (`recfin` in catalog/sources.json, `candidate`) | Not held; terms unreviewed | Regional effort and catch context | CPFV logbooks themselves are confidential (FGC § 8022, register L117); only published aggregates are lawful |
| Charter AIS pelagic-troll segments joined to same-day landing reports | Admin-only data under the charter-fleet plan | Positioned effort, with positive days from reports | Internal-only rights for aisstream data; effort location is not a catch position; never published |

### 4.3 The test that must pass

All of the following, on held-out data, or the priority stays off:

1. **Positioned outcomes with effort.** At least 30 positioned positive
   events on at least 10 distinct dates **and** at least 30 positioned
   zero-catch or effort-only events for the species, from at least two
   seasons. The earlier season may inform the pre-registration; only the
   later season is scored. Port-level reports alone cannot pass: they say
   nothing about where.
2. **Effort-normalised lift above 1.** Over the held-out dates, the share
   of positive events inside flagged cells divided by the share of effort
   inside flagged cells, with a 95% interval from a block bootstrap over
   dates whose lower bound is above 1. Cells without valid data at the
   event's time are excluded from both shares, not counted as unflagged.
3. **Better than simple baselines.** The rule's lift interval must sit above
   the lift of (a) day-of-year season alone and (b) for albacore,
   temperature-in-range alone. A rule that only reproduces where boats
   already fish fails (docs/dynamic-species-method.md L73).
4. **Resolution.** The test runs at the coarser of the product grid and the
   outcome's stated position accuracy, and any priority is shown only at
   that resolution and only for the products and lead buckets that passed.
5. **Recorded.** The result (data range, commits, counts, lift and interval
   for rule and baselines) is written to a dated note under `docs/archive/`
   whether it passes or fails.

### 4.4 Today's result and what happens on failure

- **Today the test is not evaluable**: SkipperCast holds no positioned
  pelagic outcome, no pelagic zero-catch effort, zero albacore reports and
  three bluefin reports without a ground. Not evaluable counts as failed.
  Priority display is **off**; the section 2 readout ships on its own.
- **On failure** nothing is shown as a priority, the readout stays as
  designed, and the note records the failure. The same held-out data is
  never reused to tune G or the rule. A new attempt needs a new
  pre-registration and a new held-out season.
- **On a pass** a priority may be proposed to the owner under N-4, labelled
  as an order of search from named ocean fields, with the held-out lift
  stated. It is re-scored every season and withdrawn automatically if the
  next season's lift interval includes 1.

## 5. The search strips in docs/species-search-plans.md (acceptance 4)

**Retired.** Section "Data flow" step 5 of
[species-search-plans.md](../../species-search-plans.md) (L11) describes the
v1 overlay `ocean-transition-v2`: three adjacent WCOFS cells per strip,
ordered by water transitions ([research/morro-bay-tuna.md](../../research/morro-bay-tuna.md)
L3-4, L65-80). Its code lived in `dist/search-plan-data.js` and was deleted
with the v1 shell in Grahammmm/skippercast#561 (commit dabb9c249,
2026-10-11), and its test was removed from `tests/test_coast_targets.mjs`. A
search of `web/`, `dist/*.js` and `packages/coast/src` on this branch finds
no search-strip code. This design does not revive the strips or their
priority tiers. The step should be marked retired in that doc.

This answer was checked directly on this branch because the CI6-12
read-only card (t_02a40500) had not run when this was written; CI6-12 should
confirm it, and the doc update belongs to whichever card the orchestrator
assigns.

## 6. Owner decisions (acceptance 5)

Deadline for all three: **16:00 PDT, October 20, 2026**. NEEDS G 1 and 2
are reversible and proceed with the recommended option after the deadline,
with a comment on the card. NEEDS G 3 is N-4 and waits for G.

**NEEDS G 1: outcome data for validation**

1. **RECOMMENDED:** ship the readout only; open a Skill 1 source-review card
   for the public NOAA HMS / albacore troll logbook products and the RecFIN
   CPFV aggregates. No data is used until approved. Downside: priority stays
   off for at least a season.
2. Option 1 plus charter AIS pelagic-troll segments joined to landing
   reports as internal-only validation evidence. Downside: depends on
   unresolved rights (aisstream internal-only, Blocker B5) and gives effort
   positions, not catch positions.
3. Drop the priority path; readout only, permanently. Downside: the ranked,
   time-changing part of the request stays partial.

**NEEDS G 2: archive WCOFS cycles for forecast-hour validation**

1. **RECOMMENDED:** keep each day's `habitat-dynamics.json` and its WCOFS
   tiles in a private store under ignored `var/` on AgentOrange, not in git.
   About 0.7 MB a day for Morro Bay (2026-10-20: manifest 46,763 bytes plus
   8 WCOFS tiles, 626,020 bytes). Downside: a new retained dataset to
   operate and back up.
2. Commit them to the public `data` branch `history/`. Downside: about
   250 MB a year in git for one region.
3. No archive; rely on re-downloading past cycles from NOAA. Downside:
   past-cycle availability is unverified, so forecast-hour tests may never
   be possible.

**NEEDS G 3: any number on a place (already recorded as N-4 in the parity plan)**

1. **RECOMMENDED:** no number; separate evidence lines as in section 2.
2. A search order, only after section 4 passes, labelled as an order from
   named ocean fields, not a catch chance.
3. A 0–100 score. Contradicts docs/bite-evidence.md L47 and
   `species_support`; not supported by any data held.
