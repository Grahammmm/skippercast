# Governed live coastal discovery

`python -m skippercast.coastal.live_discovery` is the host step that runs one
bounded live discovery attempt and freezes its result. It wraps the reviewed
script `skills/skippercast-discover-coastal-sources/scripts/discover.py`
(loaded in place, not copied). That script still owns the request mechanism:
durable write-ahead byte reservation, an owned child process per request,
per-request timeouts, attempt ceilings, access stops and no redirects.

## Gates added by the host step

- Plan schema `coastal-governed-live-discovery-plan-v1`: `region`, `bbox`,
  `source_revision`, `policy_revision`, `byte_limit` and the script's
  `catalogs`. Each query may name an `adapter` (`arcgis`, `stac` or `listing`).
- Every `allowed_hosts` entry must be an exact member of the repository's
  reviewed source allowlist (`skippercast.http.default_allowlist`). Suffix
  wildcards never admit a host, and the step never adds one. Authority and
  query URLs must be HTTPS on the catalog's own hosts.
- Caps are fixed: `byte_limit` at most 250,000,000 response-body bytes, the
  `discovery30` profile (1,800 wall seconds, 1,500 discovery seconds). The sum
  of planned per-query ceilings must fit `byte_limit` before any request. A
  supervisor monotonic ceiling skips remaining queries at the cutoff.
- The output directory must not exist. It is never reused, so a spent attempt
  cannot be replayed into a fresh allowance.

The `listing` adapter keeps only literal links to native-looking files on the
catalog's own hosts (`.bag`, `.bag.gz`, `.tif`, `.tiff`, `.zip`, `.xml`, `.nc`).
A `.nc` link is kept only as a plain file download: under THREDDS that is the
HTTPServer path (`/thredds/fileServer/...`); OPeNDAP (`dodsC`), NetcdfSubset
(`ncss`), WCS, WMS and ISO endpoints for the same file are services and are
dropped. A file name is not metadata: footprint, CRS, datum and
rights stay unknown, so such leads remain `blocked` until resolved.

## Commands and outputs

```sh
python -m skippercast.coastal.live_discovery dry-run --plan PLAN.json --out NEW_DIR
python -m skippercast.coastal.live_discovery run --plan PLAN.json --out NEW_DIR \
  [--previous PREVIOUS_CATALOG_OR_MANIFEST.json]
```

`dry-run` makes no request. It runs the script's `init` on a checkpoint in
`NEW_DIR` to prove the plan and caps are accepted, and writes
`dry-run-receipt.json` with the schedule and allowlist decisions.

`run` writes the script checkpoint, responses and manifest, then three
read-only files created exclusively:

- `catalog.json` (`coastal-frozen-discovery-catalog-v1`): candidates from the
  finalized manifest, bound to its SHA-256, with `catalog_id`;
- `catalog-diff.json` (`coastal-frozen-discovery-diff-v1`): added, removed and
  changed source IDs against `--previous` (a frozen catalog or a finalized
  `coastal-source-v1` manifest);
- `receipt.json` (`coastal-governed-live-discovery-receipt-v1`): script and
  module hashes, caps, request rows, charged and observed bytes, elapsed time,
  `within_caps` and output hashes.

## Boundaries

The coordinator is unchanged. Its discover stage reads only an explicit
`coastal-local-discovery-plan-v1` of cached candidates; a frozen catalog does
not enqueue work, acquire sources or admit execution. Every candidate keeps
`accepted=false`, and the catalog carries `review_required=true`: machine-valid
output is evidence for review, not scientific acceptance.
