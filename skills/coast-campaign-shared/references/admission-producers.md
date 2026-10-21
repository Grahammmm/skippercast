# Admission producer adapters and PC-9 serialization

Correction task t_3bbf6e30; sole design rev4 SHA256 c8fabf7e2e1451af762ee9c9e52c32cab5831877e34cae3f7a5a98b00bb6d433. Structural validation is review-required, never scientific acceptance or permission to execute.

## Exact admission encoding (unreleased v1 correction)

The shared admission serializer adopts the existing PC-9 input contract rather than widening the driver. Its inspected head is 16ef63c635ba8f38ac87bdb19eca16087893030f; bridge_run.py SHA256 4e6445c9a11ce50fb42f46b5b204c70fb151bf3dc06b3a2b3abfb4a78918060f. Relevant native checks are _context lines 234-236 and 287-331.

- windows[].pixel_window is [col_off,row_off,width,height], exactly the bridge selection.window, not an object. idx is 0 for the current single-selected adapter.
- grids[] is exactly {source_id,grid_sha256,definition,cols,rows,total}. cols=rows=total=1.
- definition is exactly {source_sha256,raster_crs,affine_transform,width,height,tile_width,tile_height,tiling_version,pixel_window}. affine_transform is [a,b,c,d,e,f], with x=a*col+b*row+c and y=d*col+e*row+f. tiling_version is single-selected-v1; pixel_window is the exact four-element selected window.
- grid_sha256 is the existing producer digest(definition): sorted compact finite JSON, UTF-8, WITHOUT newline. The source identity, raster size/transform and selected pixel window all affect it. Never infer adjacency between separate single-selected grids.
- preconditions is exactly {exclusive_writer:true,attested_by:nonempty-string}. This is an actual operator attestation, not an inferred model/profile identity. PC-9's separate COAST_EXCLUSIVE_WRITER invocation requirement is unchanged. Synthetic fixture attestations authorize nothing live.

The old flat-grid/object-window/array-preconditions shapes are rejected, not alternate execution spellings. Fixtures and downstream hashes are regenerated. No released implementation is migrated; this is an unreleased-v1 contract correction. No bridge caps, Store gates, queue paths or execution APIs change. PC-6 multi-window tiling remains held pending its separately reviewed adapter.

## Campaign and discovery ownership

coast-campaign-v1 is this workflow's strict campaign contract: common non-plan header, campaign_segment_id, bbox_crs84, lane, unique source_inventory IDs and unique intended_windows keys. A window key pins source ID + full grid definition digest + global idx. Campaigns may cover many lattice records/plans; an admission still pins one complete record from segments.from_bbox(campaign.bbox_crs84,region=campaign_segment_id). Validation bounds expansion to 4096 lattice records before constructing the list; larger inventories need a separately reviewed validation bound, not unbounded memory allocation.

coast-discovery-evidence-v1 is a strict workflow evidence envelope with the common non-plan header, catalog Ref and evidence Ref list. It pins the ORIGINAL frozen discovery catalog bytes and retained metadata evidence. It does not rename or rewrite producer bytes, fetch URLs, fabricate discovery success or accept candidates. Unsupported discovery checkpoint/receipt schemas still refuse as JSON graph nodes: a later producer adapter must explicitly enumerate their directory-relative references; never flatten them into queue-relative refs or disguise them as text. The envelope is the admitted bounded discovery evidence contract for this correction.

## Enumerated original namespaces

All native refs below retain their ORIGINAL queue namespace (including during archive resolution). Typed workflow refs retain their explicit namespace; fixture raw provenance uses raw:campaign. Producer source/access URLs and digest-only catalog descriptors are metadata, not file refs and never fetched.

Native adapter | File-reference slots
--- | ---
coastal-segment-v1 | none
coastal-frozen-discovery-catalog-v1 | none; catalog_id is recomputed with check_catalog
coastal-catalog-acquire-bridge-plan-v1 | selections.*.source, selections.*.review, selections.*.source_row, selections.*.rights.evidence.*
coastal-catalog-acquire-bridge-dry-run-v1 | decisions.*.source
coastal-catalog-acquire-bridge-receipt-v1 | decisions.*.source, jobs.*.input_manifest

Existing native-job/observation/result/mapping adapters remain enumerated in NATIVE_FIELDS. Native ref objects allow only path,sha256,bytes,contract,kind; unknown nested refs/path-bearing fields refuse. Serialized bridge files have NO API-return-only output field; that return descriptor is not persisted producer content or a self-reference.

Every admission always validates typed campaign/segment/catalog/plan/dry/discovery edges, regardless of filename extension. There is no opaque text or suffix-based admission bypass. Validation verifies catalog full-file SHA vs plan, producer plan digest vs admission/dry, exact segment lattice/projected/CRS84 bindings, dry would_enqueue LIST count and native-job digests, selected/held IDs and caps, source hot-cache pins, complete declared window population, grid digest/selection binding and centre ownership. Densified geographic footprints and overlapping frozen records are checked, with 1e-10 degree comparison tolerance for transformed footprint bounds. Held windows remain in admission.windows even when would_enqueue is empty.

## Offline evidence limits

The fixture uses real segments.from_bbox output, exact SC-3 frozen_catalog()/plan() serialization and actual catalog_bridge.dry_run()/run() file output. Cached BAG bytes are explicitly synthetic placeholders: no acquire, raster read, source download, network request, Store insertion, queue tick or scientific acceptance is claimed. Regenerate via PYTHONPATH=src python -m tests.coast_contract_factory; test with tests/unit/test_coast_contracts.py and tests/unit/test_coast_real_admission.py. A machine-valid graph still requires independent different-model review.
