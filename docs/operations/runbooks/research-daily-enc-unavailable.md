# research-daily: NOAA ENC hazard step unavailable

The research inventory workflow (`research-daily.yml`) snapshots NOAA ENC
Direct charted danger geometry for three bounded scopes. This runbook records
the failure mode that made that step red in about one second, the repair, and
how to reproduce and verify it. It is a research workflow, so a red run is a
SEV4 "normal issue and PR", not a product outage.

## Failure signature

```
Traceback (most recent call last):
  File ".../research/scripts/refresh_enc_hazards.py", line 75, in refresh
    metadata, digest = fetch_json(url)
  File ".../research/scripts/refresh_enc_hazards.py", line 36, in fetch_json
    raise ValueError("ENC service reported an error: " + str(result["error"])[:180])
ValueError: ENC service reported an error: {'code': 500, 'message': 'Error handling
service request :Could not find service. Service may be stopped or it may not be
configured.', 'details': []}
```

The step failed in roughly one second because NOAA answered the request
immediately (HTTP 200) with a JSON body carrying an ArcGIS `error` object
(`code` 500, "Could not find service …"). It was not a timeout, a host change,
or a schema change.

## Root cause

NOAA's `encdirect.noaa.gov` ArcGIS host intermittently answers a *valid*
MapServer metadata request with that transient 500 "Could not find service"
body. The service and its layers are still present (the full layer list returns
on the next request), so this is an upstream flake, not a removed or renamed
service. The refresh script treated any `error` key as fatal and had no retry,
so one transient response aborted the whole three-service refresh.

## Repair

`research/scripts/refresh_enc_hazards.py`:

- `fetch_json` retries the exact transient signature (`code` 500 and the
  message contains both "Could not find service" and "may be stopped or it may
  not be configured") up to `TRANSIENT_ATTEMPTS` (5) times with a capped
  exponential backoff, on the same reviewed URL.
- Any other error — a different message, a non-500 code, a redirect, an empty
  or oversized body, or malformed JSON — still fails closed immediately with no
  retry.
- The 18 concurrent layer queries are fully drained instead of letting
  `ThreadPoolExecutor.map` raise the first exception in submission order. A real
  parse/validation/host-control error outranks an isolated outage no matter
  which one finishes first; only when every failure is the transient outage does
  the run classify as upstream-unavailable.
- Every scope invocation writes a `<scope>.run-status.json` record that is
  `in-progress` at the start, then terminal `success` (snapshot written) or
  `upstream_unavailable` (receipt written), or `failed` on a hard error before
  the process exits non-zero. If the transient outage outlives the retry
  budget, `main()` writes an explicit `<scope>.unavailable.json` receipt and a
  `::warning`, exiting green; it never fabricates an empty hazard snapshot.

`research/scripts/report_enc_hazard_coverage.py` is the standalone inventory
reporter the workflow calls (previously an inline block). Its entry point
(`main`) uses `report_bound`, which binds each scope to its current-invocation
`run-status.json` record rather than trusting whatever snapshot or receipt
happens to be on disk:

- `success` — report the coverage from the snapshot named by the status, only
  when the snapshot's `checked_at` matches the status record.
- `upstream_unavailable` — report the outage from the receipt named by the
  status, and label any historical valid snapshot as "last-known" (not current).
- missing, corrupt, mismatched, `in-progress`, `failed` or any other nonterminal
  status — fail closed (exit non-zero).

A prior snapshot or receipt can therefore never satisfy a new run: a fresh
invocation overwrites the status record first, and a later `success` retires an
obsolete active outage without erasing its receipt. The low-level `report()`
helper (per-scope snapshot/receipt logic) is unchanged and remains unit-tested.

No new hosts were added; all requests still go to the reviewed
`encdirect.noaa.gov` host and are rejected otherwise by the existing
`fetch_json` host check, which runs before any network request.

## Reproduce

The failure is intermittent, so run the step repeatedly to observe both the
flaky 500 and the recovery:

```bash
# Observe the transient upstream 500 and the retry/recovery in one script:
PYTHONPATH=src python research/scripts/refresh_enc_hazards.py \
  --scope santa-barbara-island --output var/research-daily/enc-hazards/santa-barbara-island.geojson
```

## Verify

### Offline (no network, no GIS packages)

Runs the retry/outage unit tests and the invocation-binding integration
regressions (which mock only `urllib.request.urlopen` and `time.sleep`). This is
what the CI `check` job runs; it needs `pytest` (a dev tool from
`requirements-test.txt`, installed with `pip install -e '.[test]'` — not a
standard-library module):

```bash
pip install -e '.[test]'
python -m pytest \
  research/tests/test_enc_hazard_upstream_status.py \
  research/tests/test_enc_hazard_invocation_binding.py -q
```

### Offline with the survey stack (GIS / pyproj)

The `research/tests/gis/` tree also imports `audit_enc_context_overlap` and
needs the survey stack:

```bash
pip install -e '.[survey]'
python -m pytest research/tests/gis/test_enc_hazard_refresh.py -q
```

### Live, three scopes then the reporter

```bash
mkdir -p var/research-daily/enc-hazards
for scope in santa-barbara-island point-reyes-tomales h11967-greenwood-tile; do
  python research/scripts/refresh_enc_hazards.py \
    --scope "$scope" --output "var/research-daily/enc-hazards/$scope.geojson"
done
python research/scripts/report_enc_hazard_coverage.py --directory var/research-daily/enc-hazards
```

The reporter exits non-zero whenever any scope's current-invocation status is
not a terminal `success` or `upstream_unavailable` (including a missing, corrupt,
mismatched, in-progress or failed status). A scope is reported healthy only on a
matching `success` snapshot or an explicit current `upstream_unavailable`
receipt.

## Inventory-job validation (three consecutive green runs)

The acceptance is three consecutive green `research-daily.yml` inventory jobs on
the approved revision, not just local runs. After the fix is reviewed and
merged:

1. Let the scheduled run fire after `daily-data.yml`, or dispatch it with
   `gh workflow run research-daily.yml`.
2. For each run, record the run id and timestamp, confirm the "Refresh NOAA ENC
   danger review" steps and the "Report NOAA ENC danger-source coverage" step
   are green, and confirm each scope either produced a snapshot (18 layer
   queries) or an explicit `upstream_unavailable` receipt bound to that run's
   `run-status.json`.
3. A red run for any other reason breaks the streak; fix and restart the count.
