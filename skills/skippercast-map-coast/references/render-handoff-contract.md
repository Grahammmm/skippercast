# Incremental mapping-to-render handoff, version 2

Use the mapping skill's [schema](../assets/render-handoff-v2.schema.json) and
[validator](../scripts/validate_handoff.py). Keep one manifest in the existing
private output/coverage store. The schema is a portable **manifest contract**;
existing scientific, geometry, rights and restriction reviews remain authoritative.

```bash
python <mapping-skill>/scripts/validate_handoff.py /private/handoff.json \
  --root /private/artifact-root
```

Requires the repository's existing `jsonschema` dependency. It does not fetch,
render, publish or execute `preview_argv`. Exit zero means a valid manifest;
inspect `selected_slice_ids` and status before doing work. A valid BLOCKED
manifest selects nothing. Verification reads exact accepted assets, capped at
50 MB per file by default; set a reviewed resource bound explicitly for larger
assets. Do not rehash a whole survey archive just to consume small derived tiles.

## Status and incremental identity

- READY: every supplied slice has exact website-display acceptance and no deferred
  work. Both terrain and paired aligned imagery remain required for each slice.
- PARTIAL: at least one complete accepted slice, with other blocked/deferred work.
  Render only selected slices. Partial geographic coverage is not partially
  qualified terrain or permission to omit imagery.
- BLOCKED: no accepted slice. Preserve completed private artifacts and missing
  prerequisites, then stop rendering. No remapping or alternate region by default.

Slice IDs are stable source-lineage/window IDs, independent of polygon splitting
or task names. `coverage_manifest` has disjoint added/updated/removed IDs and a
previous-manifest hash for changes/removals. Added/updated identify exactly the
supplied slices. Consumers retain unchanged accepted slices from the pinned
previous manifest, apply removals, replace updated IDs and deduplicate source
lineage. A delta manifest does not authorize unioning stale acceptances; recheck
expiry and relevant changed policy for retained slices. Never sum overlapping
slice areas or count unsupported rectangles as measured support.

## Required evidence

Each slice names source identities/citations/attribution, confidence, limitations
and quality flags. Coverage uses CRS84 longitude/latitude bounds and RFC7946
geometry conventions, with native support masking, method and separate window
and valid-support areas. The native terrain preserves CRS, XY/Z units, vertical
sign/datum, resolution and NoData; unknown accuracy/datum remains explicit.
A support-mask asset preserves holes and valid pixels. No fill or interpolated
geometry gains measured credit.

Artifact descriptors carry root-relative path, SHA-256, bytes and format.
The root may be an existing shared remote parent so large datasets stay in place.
Accepted paths cannot escape it, including via symlinks. Imagery requires its
own CRS and a hashed alignment receipt. Do not substitute an unapproved service.
The consumer records loader/version, explicit preview argv and a fixed camera.
Treat paths and argv as untrusted data; inspect before invoking a scoped command.

A separate, hashed JSON website review receipt must bind every referenced
artifact hash (except itself), exact source IDs, reviewer and current expiry:

```json
{
  "scope": "website-display",
  "decision": "accepted",
  "reviewer": "designated independent reviewer",
  "acceptance_context_sha256": "...",
  "artifact_sha256s": ["..."],
  "source_ids": ["..."],
  "rights_accepted": true,
  "restrictions_accepted": true,
  "loader_accepted": true,
  "valid_until": "2026-10-07T23:59:59Z"
}
```

Before review, use `--context-for SLICE_ID` to compute the canonical proposed
acceptance digest. It binds the entire slice except its website review descriptor,
plus source hashes/citations/attribution, upstream revision, schema and scope.
It grants no approval. The reviewer records that digest only after reviewing
the payload; changing terrain sign/datum, support area, loader, limitations,
habitat status or source identity invalidates the old acceptance. The receipt's
own hash goes in the manifest afterward, avoiding circular identity.

Choose expiry from the applicable evidence/policy, not a copied example.
Acceptance includes scientific/geometry/support-mask checks appropriate to
display, exact display rights, restrictions, and loader compatibility. The
validator checks schema, identifiers, bounds, size/hash and receipt bindings;
it cannot establish factual accuracy or the reviewer's authority. A manifest
does not replace independent review or grant a new scientific/legal clearance.

Keep habitat qualification separate using `habitat.status`, optional artifact,
claims and its own review receipt. Provisional, rejected or unassessed habitat
cannot assert accepted ranks/search-area/interpreted claims. A website-accepted
terrain slice confers no fishing recommendation, precise export or new native
coverage credit.

## Reuse and preview

Pin the manifest hash, loader revision and fixed camera in the rendering
checkpoint. Compare source/method/policy identities before reusing completed
artifacts and previews; skip unchanged compatible work. Revalidate only affected
acceptance when input or applicable policy changes. Reuse mapping review rather
than re-running native qualification. Unsupported schemas/loaders stop with an
exact compatibility blocker; do not fabricate a conversion or silently downgrade.

The renderer's first output should be a reproducible local preview using these
assets, masked unknown areas, uncertainty labels and source attribution. Record
before/after cameras, viewport, loader/assets hashes, checks and screenshot paths.
No live deployment is implied. Show optional visual polish only after an honest
supported preview exists.

Legacy v1 receipts remain immutable evidence. Do not relabel them READY or
auto-fill missing fields during migration. Create a new v2 BLOCKED manifest
with the legacy receipt's identity and exact missing prerequisites, or a reviewed
v2 accepted slice when evidence actually exists.
