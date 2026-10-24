# SC-CACHE-CLOCK: explicit, host-independent cached evidence times

`skippercast.coastal.cached_inventory.epoch` turns clock values into epoch
seconds for `freshness(doc, now, horizon)`, `inventory(...)` and `produce(...)`.
Before this change a timezone-naive string such as `2026-01-01T00:00:00` was
interpreted in the host's local timezone, so the same rights or scope evidence
could be fresh on one machine and stale on another.

## Contract

- Finite `int`/`float` epochs keep their previous domain and are returned
  unchanged. `bool`, NaN, infinities, non-clock types and integers too large
  for a float are refused with `ValueError("finite clock required")` (the last
  previously escaped as `OverflowError`).
- A string must be a complete extended date-time with an explicit offset:
  `YYYY-MM-DDTHH:MM:SS`, an optional fraction of 1-6 digits, then `Z`,
  `+HH:MM` or `-HH:MM`; ASCII digits only, upper-case
  `T` and `Z`, offset hours 00-23 and minutes 00-59. `-00:00` (RFC 3339
  "offset unknown") is refused. Any other string, including naive, date-only,
  minute-precision, basic-format, space-separated, out-of-range calendar/time
  and malformed values, raises
  `ValueError("explicit-offset complete date-time required")`.
- The awareness check is a separate gate (`aware_instant`): the pattern
  accepts a missing offset only so that this gate is what refuses naive
  values, and the negative acceptance suite can disable it in isolation.
- Equal instants written with different offsets give identical epoch values.
- `freshness` keeps its inclusive endpoints (`checked_at <= now` and
  `valid_until >= horizon`) and returns `False` for missing, null, malformed,
  out-of-range or naive evidence times. Missing time is never treated as now;
  nothing is renewed or extended.
- `inventory`/`produce` still validate `now`/`horizon` first (prospective
  horizon, at most one hour), before any metadata read or output write.
  Evidence times are checked only after the existing bounded metadata read and
  cause no additional read.

No plan/schema contract, allowance constant, output lifecycle, report field or
CLI argument changed. The CLI already takes numeric `--now`/`--horizon`.

Behaviour change to note: aware strings that Python's `fromisoformat` used to
accept but that are not complete extended date-times (for example
`2026-01-01T00:00Z`, `20260101T000000Z`, `2026-01-01 00:00:00Z`) are now
refused, and therefore make evidence not fresh.

## Acceptance

`scripts/accept_sc_cache_clock.py --suite {focused,contract,negative} --output
<candidate>/out/<new-run>` runs `tests/unit/test_sc_cache_clock.py` (rows a1/a2/a3)
and the existing `tests/unit/test_coastal_cached_intake.py` in-process, offline,
against the staged repository only, and writes a write-once receipt with
argv, cwd, input hashes, per-phase counts and raw pytest output. Host timezone
variation uses a test-local `datetime` subclass, never host settings or
environment overrides. The negative suite replaces `aware_instant` with an
in-memory pass-through double and requires every naive regression to fail
while the aware positive and completeness-gate sets stay green.

A passing local run is REVIEW REQUIRED; it is not full CI, source
qualification or semantic acceptance.
