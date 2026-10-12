# Fixed discovery control and source manifest

Use the available repository Python 3.11+ runtime. `scripts/discover.py` uses the
standard library for control/HTTP and the existing repository `jsonschema` for
manifest validation (`pyproj` validates native CRS when available). It writes
private output beside the supplied checkpoint. It
never imports product code. All examples below are command shapes, not permission
to begin a run. Replace placeholders with independently checked official URLs.

## Plan and launch

Before initialization, prepare a small JSON plan with 1–4 catalogs and at most
12 queries total. Establish official publisher identity from retained evidence
or an authoritative documentation URL. Host allowlists are exact DNS names, not
suffixes. List only relevant official catalog and product hosts; no credentials,
signed URLs or authentication tokens. List the initial finite metadata/API
queries, including an explicit geographic filter and output CRS where supported.
For ArcGIS footprints request `outSR=4326&returnGeometry=true`, retaining native
CRS as a different metadata field. Request a finite result count and do not
automatically chase pagination beyond the fixed query ceiling.

```json
{
  "catalogs": [{
    "id": "original-publisher",
    "publisher": "Original official publisher",
    "authority_url": "https://catalog.example.test/",
    "allowed_hosts": ["catalog.example.test"],
    "queries": [{
      "url": "https://catalog.example.test/items?bbox=-120,33,-119,34&limit=20",
      "purpose": "metadata",
      "max_bytes": 2000000
    }]
  }]
}
```

```bash
python <skill>/scripts/discover.py /private/run.json init \
  --region REGION --bbox WEST SOUTH EAST NORTH --plan /private/plan.json \
  --source-revision SOURCE_CATALOG_REVISION --policy-revision APPLICABLE_POLICY_REVISION \
  --start-utc ACTUAL_UTC_START
python <skill>/scripts/discover.py /private/run.json status
python <skill>/scripts/discover.py /private/run.json reuse --manifest /private/previous-manifest.json
python <skill>/scripts/discover.py /private/run.json request \
  --catalog original-publisher --url EXACT_PLANNED_URL --seconds 45 --max-bytes 2000000
python <skill>/scripts/discover.py /private/run.json ingest --response 1 --adapter arcgis
python <skill>/scripts/discover.py /private/run.json finalize --reason 'finite branch complete or blocked'
```

Omit `--start-utc` to atomically record current UTC before the first request. An
explicit start cannot be future dated. `init` refuses an existing checkpoint.
Default cutoff is start +1,500 seconds and deadline is start +1,800 seconds.
After cutoff only status, recovery and finalization are appropriate. No new
queries, ingestion, cache inspection or requests can extend discovery. A second
invocation resumes the persisted counter and original absolute deadline. Clock
rollback stops active work. For windows crossing the antimeridian, explicitly
split into ordinary CRS84 windows under the same task allowance; never relabel
an invalid bbox or start another trial without authorization.

Each request runs in its own process group with a parent monotonic hard timeout,
bounded by the remaining discovery time and a 60-second per-request maximum.
The child also uses a socket timeout and an independent absolute-deadline alarm
that survives loss of its parent. The parent kills and reaps only its own
live child group. SIGTERM/SIGHUP/interrupt enters cleanup. Use a host supervisor
around the authorized trial if the whole mission must survive parent/host loss;
the helper cannot force an LLM or remote service to stop. For example, an owner
may run a prepared deterministic driver under `timeout --signal=TERM --kill-after=2s
1800s ...`; never use that wrapper to restart the checkpoint or fill spare time.

The response-body budget is decimal 250 MB, not 250 MiB. Per metadata/footprint
query max is 5,000,000 bytes. Samples also fit the total cap and require an
explicit recipe/size reason; a downloaded sample is not native qualification.
Headers advertising an oversized body are rejected before body reads. Unknown
length bodies stream to the exact cap and are rejected conservatively if they
reach it. No unbounded streaming, transparent decompression or automatic
redirects. HTTP header/TLS overhead is not measured; report counters as response
body bytes. The write-ahead reservation survives failed requests and crashes.
An exact child receipt can refund unused reservation; an uncertain failure is
charged in full. `observed_body_bytes` is separately retained and may undercount
an abrupt crash, while conservative charged bytes still protect the ceiling.

401/403 stop that catalog. 404/429/timeouts are recorded; no automatic retry.
At most two attempts per exact normalized URL, sixteen requests total, and the
second attempt requires `--changed RECEIPT` with `reason`, `evidence_url` and
`change_id` explaining genuinely changed evidence. Time passing or renaming a
task is not changed evidence. A redirect records Location but does not follow.
To follow a literal returned HTTPS link or recorded Location explicitly:

```bash
python <skill>/scripts/discover.py /private/run.json add-query \
  --response 1 --url EXACT_RETURNED_URL --purpose metadata --max-bytes 1000000
```

This consumes the original twelve-query ceiling and must use the original
catalog's preauthorized host. Relative redirect Locations resolve against the
source URL. The immutable `plan_sha256` identifies the initial authorization;
`added_queries` retains derived-link provenance. Unknown hosts are blockers,
not a reason to expand scope. A moved endpoint can remain a clear failed route.

For an original `http://` link in a successful saved response, `add-query` can
accept an explicitly requested `https://` equivalent on that catalog's already
preauthorized exact host. The original and requested path/query must match
exactly; only default ports are allowed. Credentials, signed URLs and token
query keys are rejected. The added-query receipt preserves `original_href`,
`link_normalization: explicit_http_to_https` and the saved response SHA256.
This records a proposed HTTPS URL only: it makes no request, follows nothing,
adds no host and replenishes no allowance. A later explicit request remains
HTTPS-only; failure never falls back to HTTP. The script hash pins this link
normalization revision. Candidate-evidence `method_revision` is unchanged
because source qualification semantics did not change; historical manifests
and trial receipts remain immutable and normal TTL/source/policy checks apply.

## Candidate extraction, annotation and reuse

`ingest` accepts normalized JSON, STAC FeatureCollections, or ArcGIS features.
The generic ArcGIS adapter recognizes ordinary `id/title/url` and NOAA
`NCEI_ID/SURVEY_ID/DOWNLOAD_URL`; unrecognized fields stay unknown. Missing or
nongeographic footprint CRS is rejected for overlap screening. STAC bbox uses
CRS84 while `proj:code`/`proj:epsg` supplies native CRS; these are not substitutes.
No transform or native support analysis occurs in discovery.

For a small HTML page or publisher-specific metadata shape, save bounded
normalized annotation JSON with `response_sha256` binding the saved response,
then use `ingest --response N --adapter normalized --annotation PATH`. Extract
deterministically where possible, and put source field names/short page evidence
in `field_evidence`; do not invent metadata from file extensions or geography.
Normalized candidate fields are:

```json
{
  "response_sha256": "EXACT_SAVED_RESPONSE_SHA256",
  "candidates": [{
    "publisher_id": "stable-original-survey-id",
    "title": "Original title",
    "bbox": [-120, 33, -119, 34],
    "bbox_crs": "CRS84",
    "catalog_geometry": null,
    "crs": "EPSG:26910",
    "resolution": {"value": 2, "units": "m"},
    "vertical_datum": null,
    "z_units": "m",
    "rights": null,
    "size_bytes": null,
    "source_hash": null,
    "access_url": "https://catalog.example.test/native-survey.tif",
    "alternate_of": null,
    "field_evidence": {"crs": "native_crs field in saved metadata"}
  }]
}
```

At most forty stable `catalog:publisher_id` candidates are retained. Duplicate,
malformed and truncated records are recorded. Original producer identity across
catalogs needs explicit `alternate_of` review; do not count mirror records as
independent coverage. Invalid URLs, wrong CRS and nonoverlap remain rejected
alternatives. Bbox overlap is only triage; `actual_data_support` remains null.

The source manifest retains provenance URL/response hash/request/time checked,
original IDs, metadata unknowns, catalog extent/geometry, acquisition recipe,
unacquired cache path/hash state and separate readiness blocks. Seven-day TTL
is a maximum reuse period, not permission to ignore a known upstream change.
Change `source_revision` when catalogs/data change and `policy_revision` when
applicable rights/method policy changes; the script pins its method revision.
Reuse additionally binds region, bbox and initial plan hash. Never modify old
receipts to update checked time. For a new owner-assigned acquisition plan, the
explicit scoped-import procedure in [bounded quality](bounded-quality.md)
allows validated source leads to survive a changed plan without carrying over
requests, counters or budgets. Fresh compatible leads can be reused
from a PARTIAL manifest without accepting its held candidates. A reuse miss or
invalidation should lead to one bounded external branch, not an empty-cache
conclusion. Partial reuse does not assert that all planned catalogs are complete.

The versioned [source schema](source-manifest-v1.schema.json) and `validate`
command validate the discovery contract. Reuse additionally checks metadata
proof hashes, seven-day TTL and reconstructed readiness; it never trusts saved
acceptance booleans. Cached bounded samples retain exact bytes/path/hash as
`sample_acquired_unqualified`. Source/acquisition dates, format, quality,
limitations, processing requirements and task fit remain explicit metadata.
The deterministic fitness score measures known metadata criteria only; actual
support is unknown and this score never ranks habitat or scientific quality.

## Completion and crash recovery

`finalize` atomically writes `<checkpoint-stem>-manifest.json` and closes active
work. It is idempotent and does not clear failures. PARTIAL means at least one
actionable source candidate; BLOCKED means none. `bounded_plan_finished` means all finite planned URLs were attempted.
`discovery_complete` additionally requires successful parsed responses without
truncation/malformed records. ArcGIS transfer limits and STAC next-page links
remain explicit unexamined-record limitations; do not automatically paginate.
Failed requests and unattempted queries remain separate. Neither value means mapping or rendering accepted.
All discovery candidates have `accepted:false`; selected render slices are empty.

A crash with a RUNNING intent prevents new work and finalization. Inspect the
recorded child and supervisor, stop only verified owned processes, then provide
`recover --receipt PATH`. Receipt fields are `checkpoint_sha256` (canonical
JSON SHA256, as computed by script `digest`) and `processes_stopped:true`.
Recovery refuses a still-existing recorded PID; it never signals stale PIDs.
Keep the original byte reservation, deadline and attempt. A PID-less launch
window requires actual host inspection before attesting stopped. Then finalize.

Offline verification:

```bash
python -m pytest -q tests/unit/test_coastal_source_discovery.py
```

Fixtures cover an empty-cache external candidate, CRS/nonoverlap, missing fields,
404/429/access stops, malformed/duplicate records, oversize/unknown-length streams,
partial failed transfers, actual subprocess timeout, budget expiry/resume,
manifest invalidation/reuse, HTML annotation, finite returned links, and the
separate v2 mapping acceptance contract. No real source availability or model
calibration is implied by synthetic fixtures.
