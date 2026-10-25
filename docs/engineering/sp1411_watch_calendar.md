# SP1411-WATCH-CALENDAR scoped acceptance note

Scope: validate the existing canonical UTC millisecond format by requiring a parse/ISO round trip equal to the supplied timestamp. This rejects calendar overflow (including February 30 and April 31), non-leap February 29, rollover hours, leap seconds, and unsupported formats without changing accepted canonical timestamps, ordering, precision, watch gates, registry rules, caps, or rejection precedence.

A1: `watchUpdate rejects impossible first and last sightings atomically before prepares` exercises the complete watchUpdate request path with synthetic D1 state. It checks indexed errors, zero database prepares for invalid dates, mixed-batch rejection, and unchanged prior state. `primary regression: February 30 is rejected before any database operation` is the required A4 baseline red; `healthy control: canonical February 28 timestamp is accepted unchanged` is its positive control.

A2: `canonical timestamps, leap day, precision, ordering and replay remain compatible` covers leap day, millisecond precision, equal and increasing first/last timestamps, and idempotent replay.

A3: synthetic cases in `tests/fixtures/sp1411_watch_calendar/cases.json` cover February 29 non-leap year, February 30, April 31, month/day zero, 24-hour rollover, leap seconds, and timezone/precision forms that remain rejected.

Compatibility delta: only `server/fleet/watch.ts` timestamp predicate changes. The original `tests/test_fleet_watch.mjs` is run unchanged by regression mode. Fixture data is synthetic and card-owned. No live source, external service, production database, AIS listener, or model is used.

Limitations: the focused and selected original tests are scoped evidence only. Repository checks, typechecks and build are distinct acceptance rows; the full repository matrix, required CI, semantic review, publication, and release remain owned by the operator. Machine-valid output is REVIEW REQUIRED and does not imply whole-repository or release acceptance.
