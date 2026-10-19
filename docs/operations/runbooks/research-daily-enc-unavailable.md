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
- If the transient outage outlives the retry budget, `fetch_json` raises
  `EncUpstreamUnavailable`; `main()` writes an explicit
  `<scope>.unavailable.json` receipt and emits a `::warning`, exiting green.
  It never fabricates an empty hazard snapshot.

`research/scripts/report_enc_hazard_coverage.py` is the standalone inventory
reporter the workflow now calls (previously an inline block): it reports a
valid snapshot, downgrades only an explicit `upstream_unavailable` receipt to a
warning, and fails closed on a missing, corrupt, incomplete, or unexpected
snapshot or receipt. Absence alone is never accepted as an outage.

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

Offline (no network, stdlib only; runs in the CI `check` job):

```bash
python -m pytest research/tests/test_enc_hazard_upstream_status.py -q
```

With the survey stack (GIS test that imports `audit_enc_context_overlap`):

```bash
python -m pytest research/tests/gis/test_enc_hazard_refresh.py -q
```

Live, three scopes then the reporter:

```bash
mkdir -p var/research-daily/enc-hazards
for scope in santa-barbara-island point-reyes-tomales h11967-greenwood-tile; do
  python research/scripts/refresh_enc_hazards.py \
    --scope "$scope" --output "var/research-daily/enc-hazards/$scope.geojson"
done
python research/scripts/report_enc_hazard_coverage.py --directory var/research-daily/enc-hazards
```

The reporter exits non-zero only when a snapshot is missing or invalid without
an explicit `upstream_unavailable` receipt.

## Inventory-job validation (three consecutive green runs)

The acceptance is three consecutive green `research-daily.yml` inventory jobs on
the approved revision, not just local runs. After the fix is reviewed and
merged:

1. Let the scheduled run fire after `daily-data.yml`, or dispatch it with
   `gh workflow run research-daily.yml`.
2. For each run, record the run id and timestamp, confirm the "Refresh NOAA ENC
   danger review" steps and the "Report NOAA ENC danger-source coverage" step
   are green, and confirm each scope either produced a snapshot (18 layer
   queries) or an explicit `upstream_unavailable` receipt.
3. A red run for any other reason breaks the streak; fix and restart the count.
