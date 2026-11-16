# Four-sector PSIX fetch: offline retry-readiness receipt (AUDINV-FIX-115)

**Status: live retry HOLD.** This is an offline readiness report. No robots, form,
search or export request was made, no adapter fetch path was run, and nothing here
grants a retry. Machine-valid output is review-required, not acceptance.

- Unit: AUDINV-FIX-115 (inventory FIX-115, `modes/unit-queue.tsv:2875`), approved by G
  2026-11-15 (decision log:1931, "approve ALL 295 NOT-STARTED audit rows").
- Spec checked source: remote main `0991fc70d212c9405f7b174950cb3fa4d7c6846d`.
  The builder re-read `src/skippercast/fleet/adapters/uscg_psix.py` and `regions/CA/fleet.json`
  in a fresh clone of current main (read-only; no network use other than the git clone).
- Evidence labels: **OBSERVED** = read from a file in this clone or the spec's retained
  excerpts; **INFERRED** = derived; **UNKNOWN** = not available here.

## 1. Fleet binding (OBSERVED)

`regions/CA/fleet.json:738-746`: source `uscg-psix`, adapter `uscg-psix`, `enabled: true`,
params `service: "passenger"`, `url: https://cgmix.uscg.mil/XML/PSIXExportSearch.aspx`.

Four literal sectors, in this order (`regions/CA/fleet.json:743`), and no fifth:

1. `San Diego`
2. `Los Angeles - Long Beach`
3. `San Francisco`
4. `Humboldt Bay`

`regions/OR/fleet.json:305` binds the same adapter to two other sectors (`Columbia River`,
`North Bend`). They are outside this unit and are not a fifth sector of this fetch.

## 2. Adapter sequence and code limits (OBSERVED; implementation limits, not a grant)

Source `src/skippercast/fleet/adapters/uscg_psix.py` (360 lines on checked main).
Per sector the adapter does: **GET form → search POST → export POST**
(`UscgPsix.export`, ~lines 318-333).

| Limit | Value | Where |
| --- | --- | --- |
| Export response byte cap (`MAX_BYTES`) | 50,000,000 bytes | line 48, passed as `max_bytes` at line 329 |
| Workbook member cap (`MAX_MEMBER`) | 100,000,000 bytes uncompressed | line 49, enforced at line 175 |
| Export POST timeout | 300 s | line 329 |
| Success test on export body | must start with `PK`, else `PsixFormatError` | lines 331-332 |

These are code caps. They are **not** an owner-authorized aggregate request/byte/retained
budget (see section 5).

## 3. Historical upstream state (OBSERVED, historical only)

`NEXT-ITERATION.md:227-229`: on 2026-10-20T05:18Z the second bounded fetch of the 4 CA
sectors failed on both `robots.txt` and `PSIXExportSearch.aspx` with HTTP 503 "Service
Unavailable". The parser was verified on synthetic fixtures only (t_6cb00fa2, parser-only).

Current recovered status: **UNKNOWN**. The 2026-10-20 503 is dated history and is never
current recovery evidence. A passing parser card does not prove upstream recovery or a
successful four-sector export.

## 4. Offline evidence run on checked main (spec author, OBSERVED)

`tests/unit/test_fleet_psix_dates.py tests/unit/test_fleet_psix_official.py` — exit 0,
`10 passed, 20 subtests passed`, `CHECKED_SOURCE_IMPORTS: {"wrong_origin_modules": []}`.
These are synthetic fixtures. They show the parser accepts a well-formed layout; they
populate **no** live bytes, request count, success or recovery field below.

## 5. Owner fields (all unfilled; every unknown is HOLD)

| Field | Value | State | Custodian |
| --- | --- | --- | --- |
| Robots.txt observation (current) | — | UNKNOWN / HOLD | fleet source owner |
| Form GET observation (current) | — | UNKNOWN / HOLD | fleet source owner |
| Search POST observation (current) | — | UNKNOWN / HOLD | fleet source owner |
| Export POST observation (current) | — | UNKNOWN / HOLD | fleet source owner |
| Parser recovery observation on live bytes | — | UNKNOWN / HOLD | fleet source owner |
| Approved total request budget | — | UNKNOWN / HOLD | G / admission owner |
| Approved total byte budget | — | UNKNOWN / HOLD | G / admission owner |
| Approved retained-bytes budget | — | UNKNOWN / HOLD | G / admission owner |
| Attempt window (start/end) | — | UNKNOWN / HOLD | G / admission owner |
| Authorization expiry | — | UNKNOWN / HOLD | G / admission owner |
| Prior-attempt history | 2026-10-20 attempt 2: 503 on robots + export page (above); attempt 1 record not retained here | partial, preserved | fleet source owner |

## 6. Edge cases: how a future receipt must treat them

1. **Historical 503** stays history; it never becomes "recovered" or "current".
2. **Robots unknown or failing, or any missing admission field in section 5** = HOLD. The
   adapter itself records a robots refusal as a skip, not a pass.
3. **Exactly four sectors**, spelled and ordered as in section 1; adding a fifth is a new
   admission, not part of this retry.
4. **Three successes and one failure** is a *partial* result, not four-sector success; keep
   the failed sector's receipt.
5. **HTTP 200 HTML, a malformed form/XLSX, or an oversized archive/member** is not a
   successful export (`PsixFormatError` paths: missing `PK` magic, bad zip, member over
   `MAX_MEMBER`, missing `PSIXInspections` sheet or columns).
6. **Parser fixture passes** (section 4) must never fill live bytes, request or success fields.
7. **Code caps (section 2) and owner-authorized aggregate budgets (section 5) are distinct.**
   There is no automatic retry; each attempt needs its own admission and preserves earlier
   attempts, including failed and partial ones.

## 7. Handoff

- A future live fetch must be separately admitted after current upstream recovery evidence
  and a filled section 5, as its own card. This report manufactures no allowance and does not
  invoke the adapter normal fetch path.
- Canonical queue/ledger, config and the adapter are unchanged.

## 8. Verification (builder)

```
test -s docs/engineering/audits/four-sector-fetch-ready-receipt.md
git diff --check
```

Both run in the clone at build time; results are in the PR body.
