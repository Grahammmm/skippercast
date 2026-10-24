# SC-CACHE-CLOCK: explicit, host-independent cached evidence times

`skippercast.coastal.cached_inventory.epoch` turns clock values into epoch
seconds for `freshness(doc, now, horizon)`, `inventory(...)`, `produce(...)`
and the module CLI. Before this change a timezone-naive string such as
`2026-01-01T00:00:00` was interpreted in the host's local timezone, so the
same rights or scope evidence could be fresh on one machine and stale on
another.

## Contract

- Finite `int`/`float` epochs keep their previous domain and are returned
  unchanged. `bool`, NaN, infinities, non-clock types and integers too large
  for a float are refused with `ValueError("finite clock required")` (the last
  previously escaped as `OverflowError`).
- A string must be a complete date-time with an explicit offset. The base
  parser (`datetime.fromisoformat` after replacing `Z`) is still the parser,
  and every complete, explicitly offset string it accepted keeps exactly its
  base value. That includes basic and extended calendar dates, week dates with
  a day, any single date/time separator the parser accepts (for example `T`,
  `t` or a space), basic or extended times with seconds, `.` or `,` fractions
  of any length (truncated to microseconds, as before), and `Z` or any numeric
  offset spelling the parser reads, with or without colons, with optional
  seconds, and with a `.` or `,` fraction after the offset hour, minute or
  second field (for example `+05.5`, `+05:30.5`, `+0530,5`, `+05:30:00.5`),
  including `+05` and `-00:00` (all still read exactly as before).
- The completeness check looks only at the date and time part (a fixed
  prefix pattern); it never matches the offset. The offset text is read by the
  base parser, plus one range check on its integer minute/second fields.
- Newly refused, all with
  `ValueError("explicit-offset complete date-time required")`:
  - naive strings (no offset), whatever their layout;
  - date-only strings;
  - incomplete times (hour-only or minute-only) and week dates without a day;
  - offset minute or second fields of 60 or more (with or without a
    fraction), which the parser used to carry silently into the next hour or
    minute.
  Strings the base parser already refused (out-of-range calendar/time values,
  offsets of 24 hours or more, lowercase `z`, `UTC` suffixes, surrounding
  whitespace, non-ASCII digits and similar) are still refused, now with the
  same stable message. The test fixture `base_accepted_now_refused` lists every
  aware vector that changed from accepted to refused; a test checks it against
  the base parser so no further narrowing happens unnoticed. Class-level tests
  cross every complete date/time layout with every supported offset spelling
  and check epoch, freshness and inventory against the base parser.
- The awareness check is a separate gate (`aware_instant`), so a missing
  offset is refused there, and the negative acceptance suite can disable it in
  isolation.
- Equal instants written with different offsets give identical epoch values.
- `freshness` keeps its inclusive endpoints (`checked_at <= now` and
  `valid_until >= horizon`) and returns `False` for missing, null, malformed,
  out-of-range, incomplete or naive evidence times. Missing time is never
  treated as now; nothing is renewed or extended.
- `clock_window(now, horizon)` holds the single prospective-horizon rule (at
  most one hour). `inventory`, `produce` and the CLI `main()` call it first,
  so an invalid `--now`/`--horizon` (non-finite, reversed, equal or more than
  an hour apart) is refused before the CLI creates its output directory,
  writes `cli-plan-admission.json` or reads the plan or any metadata. Valid
  runs keep the same output files, fields and lifecycle. Evidence times are
  checked only after the existing bounded metadata read and cause no
  additional read.

No plan/schema contract, allowance constant, output lifecycle, report field or
CLI argument changed. The CLI already takes numeric `--now`/`--horizon`.

## Acceptance

`scripts/accept_sc_cache_clock.py --suite {focused,contract,negative} --output
<candidate>/out/<new-run>` runs `tests/unit/test_sc_cache_clock.py` (rows a1/a2/a3)
and the existing `tests/unit/test_coastal_cached_intake.py` in-process, offline,
against the staged repository only, and writes a write-once receipt with
argv, cwd, input hashes, per-phase counts and raw pytest output.

Before it imports anything or creates the run root, the runner checks every
input against the frozen identities in
`tests/fixtures/sc_cache_clock/input-pins.json` (SHA-256 and size). Each input
is opened one path component at a time from `/` with no-follow descriptors,
so a symlink anywhere in the unresolved ancestry, a special file or a
non-regular leaf is refused. Reads are capped at 2 MiB per file and 16 MiB in
total, at most size+1 bytes are read, and the descriptor identity must not
change during the read. Any difference exits 3 and writes nothing. The pins
file has to be regenerated whenever a pinned input changes; its own hash is
recorded in each receipt.

Host timezone variation uses a test-local `datetime` subclass, never host
settings or environment overrides. The negative suite replaces
`aware_instant` with an in-memory pass-through double and requires every naive
regression to fail while the aware positive and completeness-gate sets stay
green.

A passing local run is REVIEW REQUIRED; it is not full CI, source
qualification or semantic acceptance.
