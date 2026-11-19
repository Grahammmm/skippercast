# Reviewed relief releases

`catalog/relief/<region>.json` is the public, repo-authenticated pointer to a
reviewed regional relief archive. Its contract is `pointer.schema.json`
(JSON Schema Draft 2020-12). Do not add a pointer manually or commit local
release artifacts, QA packs, approvals, private inputs, or absolute paths here.
This directory does not itself enable a region.

## Build and review locally (R6–R8)

Run from the pinned source checkout with the existing `survey` or `publish`
extra (for JSON Schema validation). Paths in the release and envelope are POSIX
and relative to `OUT/<region>`, not to the manifest containing them.

1. Build the inventory JSON from the current producer receipts (no hand edits, no copies):

   ```sh
   python scripts/relief/region.py digests --out OUT --region ID
   python scripts/relief/region.py inventory --out OUT --region ID
   ```

   `OUT/ID/inventory/manifest.json` has `region`, `bounds: [west, south, east, north]`
   (WGS84, clipped to `regions/<region>/region.json`), `minzoom`, `maxzoom`,
   `sources`, `detail_summary`, `native_support_by_zoom`, and `layer_paths`.
   The metadata has the same fields and types as the pointer: sources retain
   catalog IDs, labels, credits, dates, datum and rights; `detail_summary`
   contains the transparent-nodata mask and depth bands; per-zoom support comes
   from the layer producers. Neither a source label nor a nominal spacing
   can certify a cell. The QA stage checks the emitted spatial evidence.
   Use only sources with `rights_class: "public"` and a matching approved
   catalog row with `rights.public_display: "allowed"` and matching licence.
   Pending CSUMB rows are not public; MBARI is always excluded.
2. Each producer owns its own leaf: the archive is `layers/public/tiles/relief.pmtiles`
   (tiles), the digest index `layers/public/relief.digests/` (digests) and the zone
   layers `layers/public/zone/` (zone). The inventory lists every file of those
   leaves except the tiles coverage sidecar. Depth contours (`layers/contours/`) are
   not part of the relief release; they ship through the repository contour channel.
   Pass the current producer receipts and the inventory receipt (repeat `--upstream`):

   ```sh
   python scripts/relief/region.py package --out OUT --region ID --manifest OUT/ID/inventory/manifest.json \
       --upstream tiles:public --upstream digests --upstream zone:public --upstream inventory
   ```

   With `--upstream inventory`, package refuses a manifest that is not the
   inventory stage's current output.
   This writes `OUT/ID/release/<gen>/release.json` (`sc-relief-release/1`), where
   `<gen>` is the package receipt's generation. It includes the exact sorted
   inventory of `{path, sha256, bytes}`, the producing `code_sha`, zooms, bounds,
   the source and detail metadata, `private: false`, and `NOT FOR NAVIGATION`.
   There is no QA path or hash in the release. QA can run before the digest
   producer is installed; such a release cannot produce a public pointer.
3. The QA stage writes `OUT/ID/qa/<gen>/qa.json` and its stage receipt. A passing
   report must include `status: "PASS"` and `release_sha256` equal to the SHA-256
   of the exact on-disk release JSON bytes. With current package and QA receipts:

   ```sh
   python scripts/relief/region.py envelope --out OUT --region ID --generation GEN
   ```

   This writes `OUT/ID/review/<gen>/envelope.json` (`sc-relief-envelope/1`), with
   region, release generation, `release` and `qa` `{path, sha256}` records and
   the exact layer list from `release.json`. `package` and `envelope` write
   `stages/package.json` and `stages/envelope.json` respectively. The latter has
   its own receipt generation; `review/<gen>/` uses the **package** generation.

## Check the approval, then prepare the pointer (R9–R10)

The trusted queue writes `approval.json` from the designated review card. Its
fields include `envelope_sha256`, `verdict`, `card_id`, `reviewer` and `time`.
The `verdict` must be exactly `APPROVED release <id> envelope=<sha256>`.

`skippercast.relief.envelope.verify_chain(approval_path, envelope_path)` returns a
`VerifiedRelease` (region directory, envelope hash, release hash and validated
release document) or raises `ReleaseError`. It rehashes the actual envelope, QA,
release and every listed layer file, checks layer sizes and verifies that the
release and QA still describe the approved generation. This is byte binding,
not reviewer authentication or permission to upload. Callers must check current
receipts and the publication scope separately; the upload stage must also hash
exactly the bytes sent and verify each full object on read-back.

`skippercast.relief.envelope.build_pointer(approval_path, envelope_path,
previous=old_pointer)` makes a schema-validated candidate dictionary. It does not
write to the repo or upload. `sha256` and `bytes` identify the whole relief archive
at `tiles/relief/<region>/<sha256>.pmtiles`; `digest_root_sha256` is the hash of the
index root layer (never inferred from the archive header). `release_sha256`
and `envelope_sha256` refer to the actual JSON bytes. `previous` is `null` for a
first pointer, otherwise the previous same-region pointer's `generation`,
`release_sha256`, `envelope_sha256` and archive `sha256`. It is rollback lineage,
not an automatic fallback; the full previous pointer is preserved in git.
The data-PR stage checks the three digests against the upload receipt before
writing the candidate to `catalog/relief/<region>.json`.
