# SP1410: malformed regional forecast containers are unavailable

Spec SP-14-v1, card SP1410-FORECAST-ENVELOPE. Base: Grahammmm/skippercast main
33734f90073a2150eac5a418564ea314c4a591ac.

## The problem

`intelligenceFeed` (server/advisor/answers/feeds.ts) admitted any feed whose
`region_id` matched. `windowConditions` (server/advisor/answers/conditions.ts) then
calls `.filter` on `forecast.models.gfs_global.data[point].hourly.time`, so a
correct-region feed whose `time` was a string or an object threw a TypeError inside
`get_conditions`, the planning brief and the daily answer's inputs, instead of
giving the ordinary "regional forecast unavailable" day. A valid empty `time`
array already gave an unavailable day without an exception.

## The change

`intelligenceFeed` keeps its reader and region checks and adds a read-only shape
gate (`forecastContainersOk`) for the containers the conditions readers index into:

- the feed is a plain object (not an array);
- `forecast`, when present, is a plain object, and `forecast.models`, when present,
  is a plain object;
- each recognized model present (`gfs_global`, `ecmwf_ifs025`, `ncep_gfswave016`,
  `ecmwf_wam`) is a plain object;
- a model's `data` is an array, except that an explicit provider-error record
  (truthy `error`) may carry no array; absent `data` stays allowed;
- every point in a `data` array is `null` or a plain object; a point's `hourly`,
  when present, is a plain object, and its `time`, when present, is an array.

Anything else returns `null`, which every caller already treats as "no forecast".
The gate never writes to the feed, adds no schema version, no numeric, unit or
freshness rule, and makes no source call. Sample values and units remain the
policy of `readHour`/`sample`; unrecognized models and extra fields are ignored.
`dailyFeed`, `feedReader` and reader routing are unchanged.

## Acceptance rows and tests

All tests are in tests/test_sp1410_forecast_envelope.mjs and use the complete real
modules with an injected offline reader. Fixtures are card-owned synthetic JSON in
tests/fixtures/sp1410_forecast_envelope/: `complete.json` (producer-shaped
intelligence feed, two points, four models), `minimal.json` (matching region,
empty GFS time arrays), `daily.json` (valid daily feed with one Small Craft
Advisory for PZZ645) and `contract.json` (the 19 malformed-container cases, each a
path and value applied to a fresh copy of `complete.json`). `offline.mjs` is the
test's offline boundary, imported before any product module.

| Row | Test |
| --- | --- |
| A1 | `A1 every malformed forecast container in an otherwise correct-region feed is unavailable (null)` |
| A1 | `A1 get_conditions answers a malformed feed with an unavailable forecast and keeps the daily advisories` |
| A2 | `A2 the card-owned producer-shaped feed is admitted unchanged and gives the same conditions` |
| A2 | `A2 the committed producer fixture tests/fixtures/feeds/intelligence.json is admitted and gives the same conditions` |
| A2 | `A2 valid empty arrays, absent models, null points, absent containers and provider-error records keep the missing-data outcome` |
| A3 | `A3 reader rejection, null and non-object input and a wrong or missing region stay null` |
| A3 | `A3 the gate never mutates a feed and admits optional unrelated fields` |
| A3 | `A3 sample values and units stay owned by readHour` |
| A3 | `A3 dailyFeed and reader routing are unchanged` |
| A4 | `primary regression` (contract case `gfs-time-string` must be refused) |
| A4 | `healthy control` (empty GFS time array admitted, available false, no throw) |
| all | `offline boundary: no network, model or storage access in any case` |

A4: `--suite baseline` registers only the pair (`SP1410_SUITE=baseline`) and runs
it against the unchanged primary file. Its success is BASELINE_GAP_REPRODUCED: the
primary fails at its `SP1410_PRIMARY_SHAPE_REJECTION` assertion after recording
the original `windowConditions` TypeError as observed data, and the control
passes. `--suite focused` reruns the same pair with the change and requires an
earlier baseline receipt whose test and fixture bytes are identical.

Original compatibility (`--suite regression`): tests/test_advisor_tools.mjs and
tests/test_advisor_daily.mjs, unchanged.

The launcher is scripts/accept_sp1410_forecast_envelope.py (stdlib Python; see
its docstring for every suite, exit code and receipt field).

## Compatibility deltas

- A correct-region feed with a malformed consumed container was admitted and
  could throw; it is now `null`. `get_conditions` and the planning brief give the
  "regional forecast unavailable" day with the daily advisories intact.
- In the daily answer (server/advisor/answers/reports.ts) such a feed now counts
  as an intelligence feed that did not load (`feeds.intelligence: false`), so a
  stored answer for the day is kept rather than regenerated from a broken feed.
- `null` for a present model, `hourly` or `time` (and for `forecast` or `models`)
  is a malformed container and is refused; only points may be `null`. The feed
  schema (src/skippercast/coastal/resources/intelligence-feed.schema.json) has
  each model as an object with an array `data`, so these nulls are outside it.
- A provider-error record whose `data` array holds malformed point containers is
  refused, because `windowConditions` reads `gfs_global` times without looking at
  `error`. Error records with an empty, absent or non-array `data`, or with
  well-formed earlier points, are admitted as before.
- Feeds without a `forecast` block (snapshots predating it, which the schema
  still allows) or without `forecast.models` stay admitted, as before.

## Limitations

- This is scoped acceptance only: the full Node discovery, Python matrices,
  regional/search parity, e2e, audits and CI at the exact head stay owed to the
  operator and CI owners.
- The gate checks containers only. Values inside a valid `time` array, units,
  freshness, point order and model agreement are out of scope.
- No producer, forecast generation, web client or alert-policy change. The
  browser surface-field points (SP-FIELD-SHAPE) and trip dates (SP1403) belong to
  other cards.
