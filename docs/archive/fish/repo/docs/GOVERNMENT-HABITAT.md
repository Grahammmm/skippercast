> **Historical archive (copied 2026-10-11, SkipperCast FE-62).** This is `docs/GOVERNMENT-HABITAT.md` from the retired Fish (SLO Fish Report) repository at commit `68d7b44` (2026-10-06). It records how Fish worked and what was checked at the time, is not maintained, and may describe services, data and claims that no longer exist. SkipperCast's own documentation is the live truth: start at the [archive index](../../README.md) and [front-end design § 15](../../../../plans/front-end/design.md#15-retiring-fish). Links to Fish code, configuration or data that were not archived are shown as plain text, and identifiers that could not be published were redacted.

# Fish-owned government habitat releases

**Live update adapter:** the reviewed importer now promotes immutable consumer manifests, exact curated details and species profiles alongside both archives in private R2. The serving Worker resolves the selected set without rewriting bundled assets. See [parallel upgrades, CAS promotion and cloud activation](SKIPPERCAST-UPDATES.md). The original v1 bundled pin/storage record below remains the migration and historical verification contract.

Fish can run its separately rebuilt government habitat release without modifying SkipperCast's mixed release or its publisher Worker. This is a private storage adapter and an explicit reviewed input scope. It does not convert a mixed archive into a commercially reusable archive by deleting restricted polygons afterward.

## Scientific and import boundary

The owned engine selects `government-only` inputs before coverage, terrain, substrate selection and calibration. Its root-bound scope marker prevents using scoped processing in another working tree. Original catalog rows and source bytes remain pinned; excluded source lineage cannot be relabeled as government data. Run receipts identify the actual source scope and implementation. The importer separately checks physical contributors, calibration-only contributors and substrate dependencies against the full catalog, all regional reach receipts and their output hashes.

The normal publication gates still apply: actual archive and canonical export checksums; complete original polygon geometry; screened/exportable Tier 2 habitat; nominal depth and native resolution limits; quality and calibration dependencies; complete spatial screening; original producer rights; current source clocks and the earliest screening expiry. Unsurveyed gaps remain gaps. Fish presence, successful catches and catch probabilities are not measured by this habitat layer.

`scripts/import-government-habitat.mjs` reads the owned engine, validates **both** supported regions, retains full canonical exports and scientific reviews privately, then creates a public curated detail subset. It stages immutable objects, performs full byte checksum read-back, and selects the entire set with one final control write. A failed build, missing region, failed read-back or expiry during staging leaves the prior selected control intact. A release never falls back to the mixed upstream archive after withdrawal.

## Exact storage and provenance contract

The private `HABITAT` R2 binding uses the `fish-habitat` bucket. It requires no public bucket URL. Keep R2 public access and bucket custom domains disabled.

| Object | Role |
| --- | --- |
| `habitat-government/current.json` | Selected set control, read on every gated request |
| `habitat-government/<releaseId>/release.json` | Original immutable ready control bytes |
| `habitat-government/<releaseId>/<regionId>.pmtiles` | Original government-scoped archive |
| `habitat-government/<releaseId>/<regionId>.canonical.geojson.gz` | Full original polygon export, private |
| `habitat-government/<releaseId>/<regionId>.review.json` | Bound source/science review, private |

The ready control has `schemaVersion:1`, `sourceKind:'fish-government'`, `status:'ready'`, `ready:true`, a 64-character hexadecimal `releaseId`, `sourceScope:'government-only'`, `sourceUse:'for-profit'`, the exact 40-character `producerCommit`, `catalogSha256`, `expiresAt`, and exactly two `regions`: `morro-bay` and `cambria-san-simeon`.

Each region has its exact `regionId`, ready status, `commercialArchivePermitted:true`, `license:'public-domain-us-gov'`, `expiresAt`, fixed `archiveKey`, `archiveSha256`, `archiveBytes`, `archiveETag:'"sha256-<archiveSha256>"'`, and `reviewReceiptSha256`. Additional scientific provenance is retained rather than discarded. The set expiry cannot exceed either region's expiry.

The public `/data/skippercast-manifest.json` pins the control's exact byte SHA as `releaseManifestSha256`, the source/provenance fields, and both region hashes, sizes, receipt hashes and expiry clocks. Its top `sourceManifestUrl` is `/api/habitat/release`. Each public region's `archiveUrl` is `/api/habitat/tiles?region=<regionId>`, with the same release URL for `sourceManifestUrl`. The importer writes identical initial bytes for the ready current control and immutable release control. Any change to current control, including `status:'held'`, invalidates the public pin immediately.

R2 objects are installed with `customMetadata.sha256`; full original byte checksums are verified during staging. Runtime checks the pinned control's actual bytes plus immutable release metadata and **both** archive HEAD metadata before serving either region. SHA metadata is an integrity assertion made by the private reviewed publisher, not a substitute for the importer's full byte read-back. Native R2 ETags are independently pinned for each range fetch. Runtime does not reread and hash entire PMTiles archives for each tile.

## Runtime transport

`src/government-habitat-proxy.ts` provides the adapter. The existing upstream adapter is unchanged.

- Every request checks the full two-region set, expiry, public import provenance, exact control digest and private R2 object sizes/SHA metadata. There is no release-manifest cache.
- `HEAD /api/habitat/tiles?region=…` validates both regions and returns pinned size/ETag without downloading archive bytes.
- `GET` requires one closed or suffix `Range`, at most 2 MiB. Open, multiple, oversized, invalid and complete-archive ranges are rejected with 416. Archives are bounded to 32 MiB per region.
- Client `If-Match` is checked against the exposed strong SHA ETag; mismatches return 412. R2 GET also pins the native R2 ETag with `onlyIf`, and the returned size, SHA metadata, native ETag, actual range and body length must match.
- After reading a range, the adapter rereads the current control and checks expiry again. Withdrawal or expiry during transfer returns 503 without exposing the range.
- `/api/habitat/release` returns validated public metadata, with no archive or private review route. A held or incomplete set returns 503.
- Direct curated `/data/skippercast-habitat.geojson` and `/data/skippercast-species.json` requests use the same complete release gate. Successful responses are `no-store`. The public import manifest remains readable so a client can explain withdrawal.
- Private archive/receipt prefixes have no static route. Percent-encoded, repeated slash and backslash aliases of protected asset paths are rejected before ASSETS fallback. Generated private objects must never be copied into `public/` or `dist/public`.

Gated responses use `Cache-Control:no-store`; a browser's displayed habitat must still honor the existing periodic all-region availability checks. A physical USGS bathymetry raster remains a separate independently reviewed layer and does not inherit habitat eligibility.

## Runnable local preview

Use an owned engine with reviewed scientific implementation committed and completed government-scoped output for both regions. Do not stage another SkipperCast worktree's artifacts.

```sh
node scripts/import-government-habitat.mjs artifacts/government-engine --stage-local
npm run check
npm test
npm run dev
```

The local importer uses Wrangler's `getPlatformProxy` with the dedicated `wrangler.habitat-local.jsonc` writer configuration and `remoteBindings:false`. It writes the private `HABITAT` binding with SHA metadata, reads back every immutable object's complete bytes and promotes the set control last. The CLI now uses the live conditional promotion described in the upgrade contract. The earlier exported local file-install helper remains covered by rollback tests for v1 installations. The standard local preview uses the persisted Wrangler local R2 store. Wrangler CLI `r2 object put --local` alone does not provide this custom metadata contract.

Then test actual `HEAD`, a 127-byte PMTiles header `Range:bytes=0-126`, a representative binary tile range, suffix ranges, incorrect `If-Match`, expired/held control, and loss of either region. Verify both raw archive prefixes and encoded curated aliases fail closed. Transport fixtures cover these gates; they do not establish visual map quality or complete live release acceptance.

## Cloud deployment prerequisite

`wrangler.jsonc` declares the private `HABITAT` binding. A cloud deployment needs the dedicated private bucket provisioned and a reviewed uploader using the same immutable objects, SHA metadata, full read-back and atomic final control promotion. Local staged objects are **not** uploaded by `wrangler deploy`. Do not advertise cloud availability based on local R2 alone. Missing private binding or objects must remain a visible unavailable habitat layer.

A producer release hook must build under the same input scope, refresh and verify spatial screening, review both complete regions, stage new immutable releases, then promote one whole-set control. Maintain producer review/CI requirements separately; this adapter does not authorize a direct push, bypass normal engine review or replace the existing SkipperCast release.

## Verification scope

`tests/government-habitat-proxy.test.ts` checks two-region atomic gating, receipt/path/rights/scope provenance, exact control bytes, immutable release presence, archive metadata, HEAD, bounded ranges, suffix/clamping, both ETag layers, incorrect body/range metadata, mid-transfer withdrawal/expiry, Worker dispatch, curated asset gates and encoded static bypasses. Importer tests independently cover calibration-only restrictions, source lineage and failed/expired staging. Actual local R2 acceptance is recorded below. Actual local map rendering and reef interactions are recorded in [browser acceptance](../research/visual-acceptance-2026-10-03.json).


## Reviewed implementation and actual local release — October 3 UTC

The engine input-scope change was independently reviewed, passed 1,110 Python tests (14 expected private-archive skips and 4,511 subtests) and merged through [SkipperCast PR 209](https://github.com/Grahammmm/skippercast/pull/209). This Fish release pins producer commit `0978207dd12cc4f0591302f7458f8db75fdfc782`; the normal merge commit is `db19844a3086243d40637faa82d72fa2d01dc997`. All 12 government-scoped reaches were actually processed and published. Restricted sources were excluded before scientific processing, rather than removed from a mixed finished archive. Existing SkipperCast working trees and publication namespaces were not changed.

The locally selected release is `cbbb5c6cf0e6858f4d4ece9468f4fc12716f8d33aa2f4d0155cd729a74ab8158`. It contains 2,868 full polygons and 12,453 coverage cells across both regions, plus 45 exact public detail geometries within 1,979,799 bytes. Private review receipts bind original manifests, canonical bytes, all run/input/output hashes, original source receipts and source lineage. Its earliest screening expiry is November 5, 2026 UTC; missing survey coverage remains unknown.

Actual serving-Worker checks at 01:40 UTC returned matching HEAD identities and exact 16,384-byte 206 ranges for both regions. Incorrect `If-Match` returned 412. Holding the private control immediately made both archives and both curated files return 503; restoring it recovered both regions. Private archive prefixes and encoded curated aliases returned 404. See the [committed runtime and science receipt](../research/government-habitat-release-2026-10-03.json).

To repeat the bounded transport/storage acceptance with the local server running and this owned engine present:

```sh
node scripts/verify-government-habitat.mjs
```

This verification deliberately holds and restores the local control in a `finally` block; run it only against this local preview. The Fish suite has 172 passing tests, both TypeScript configurations pass and the production build passes. Exact-head GitHub CI is a separate save gate. **No cloud habitat objects have been uploaded. Actual local desktop/mobile visual and interaction evidence is now available in the browser acceptance record.**
