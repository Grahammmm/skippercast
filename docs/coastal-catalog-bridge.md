# Frozen catalog to coordinator acquire bridge

`python -m skippercast.coastal.coordinator.catalog_bridge` connects governed
live discovery to the coordinator. Live discovery (#734, documented in its
`docs/coastal-live-discovery.md`) freezes a
`coastal-frozen-discovery-catalog-v1`. The bridge reads that catalog together
with an owner bridge plan. For each selected lead it writes the acquire
stage's existing input, `coastal-native-job-v1`. The coordinator's ordinary
`Store.enqueue` then queues that input at the `acquire` stage. The bridge
changes nothing in the coordinator, the stage CLI or the discovery step.

## Source-free and offline

- The bridge reads only JSON metadata: the catalog and the plan, each at most
  4 MiB. It checks a cached native source with `lstat` alone: the file must be
  a regular file under the queue root, with no symlink in its path, and its
  size must match the ref. The bridge never opens, hashes or downloads source
  bytes. The acquire stage checks the bytes against the ref's SHA-256 when it
  runs.
- The bridge makes no network request and imports no network client. A test
  enforces both.
- The bridge accepts a catalog only when the `catalog_id` still matches its
  content, `review_required` is `true`, and `mapping_accepted` and
  `execution_authorized` are both `false`. The plan pins the catalog's
  `catalog_id` and the SHA-256 of its file.

## Gates per selected candidate

A candidate is selected only if every check below passes. Any other candidate
is held, and the receipt records the reasons:

- it is in the catalog's `usable_source_ids`, has no `rejection_reasons`, and
  its terrain status is `candidate_for_qualification`;
- its `access_url` uses HTTPS with no credentials and no port, on a host that
  is an exact member of `skippercast.http.default_allowlist()`. A suffix
  wildcard never admits a host, and the bridge never adds one. A URL that
  cannot be parsed is held as `access_url_malformed`;
- its catalog `extent.bbox` (CRS84) overlaps the segment's `bbox_crs84`, and
  its `expires_at` is a UTC stamp in the future;
- its cached ref passes the `lstat` checks above. When the catalog states a
  size, the ref must match it. When the catalog states a SHA-256, the ref must
  match that too. Any other hash is recorded as `unknown`, not trusted;
- its native window is a list of four integers with at most 1,048,576 cells,
  the same bound as the Store's acquire dispatch gate.

## Caps

These caps are fixed and checked before anything is written:

- 1 to 4 selections (`MAX_JOBS`);
- `max_total_bytes` of selected cached sources, at most 2 GiB
  (`MAX_TOTAL_BYTES`, the acquire stage's default per-job ceiling);
- an acquire budget with exactly `wall_s` (at most 3,600), `memory_bytes`,
  `bytes` (at most the bridge cap, and at least the size of each selected
  source) and `requests` set to `0`.

## Commands

```sh
python -m skippercast.coastal.coordinator.catalog_bridge dry-run \
  --root QUEUE_ROOT --catalog catalog.json --plan PLAN.json --out NEW_DIR
python -m skippercast.coastal.coordinator.catalog_bridge run \
  --root QUEUE_ROOT --catalog catalog.json --plan PLAN.json --out QUEUE_ROOT/NEW_DIR
```

`dry-run` writes only `bridge-dry-run-receipt.json`
(`coastal-catalog-acquire-bridge-dry-run-v1`). The receipt lists the decision
for every candidate, the caps and the jobs the bridge `would_enqueue`.

`run` writes one read-only `native-job-NN.json` per selected lead inside the
queue root, plus `bridge-receipt.json`
(`coastal-catalog-acquire-bridge-receipt-v1`). Each job carries
`catalog_lineage`: the catalog ID and hash, the `source_id`, the access URL and
the hash binding. `catalog_bridge.enqueue(store, receipt_ref, code_sha=...,
deps_sha=...)` then queues each job at `acquire` through `Store.enqueue`. Before
that, `enqueue` checks that the Store's segment has the same `bbox_crs84` as
the bridged one. Neither command reuses an output directory. `--root` and
`--out` may be relative: the bridge resolves the output's parent before it
checks containment or writes, so every recorded ref stays relative to the
resolved queue root.

## Boundaries

A bridged job is input for the coordinator's existing gates. It is not
accepted for anything. The acquire stage still verifies the source bytes and
records zero requests. Qualification, vertical semantics, rights, mapping
review and rendering keep their own holds. For example, if a plan declares no
vertical contract, the acquire stage holds on `vertical_*` instead of
guessing one.

A cached source may be a native BAG, a GeoTIFF or a local netCDF grid (`.nc`,
such as a NOAA CRM subset). The acquire and qualify stages read a netCDF
container only when it is netCDF classic, or netCDF-4 whose whole HDF5 tree is
local (no soft or external links, no virtual or external-storage datasets), and
only as one 2-D variable. Any GDAL sidecar next to it (`crm.nc.aux.xml`,
`.msk`, `.ovr`, `.aux`, `crm.aux`, any case, including symlinks) is refused
before GDAL opens the file, because a mask or overview can point GDAL at
another dataset. A geographic (degree) netCDF grid
is read as native cells and qualified, but the map stage holds it as
`native_geographic_grid_derivatives_unsupported`: slope and rugosity need
metric spacing and the pipeline does not resample.

The bridge depends only on the catalog file's schema, not on the discovery
module. Integration with live discovery waits for #734 to merge.
