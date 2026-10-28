# C1 Morro Bay M/D discovery, 2026-10-20

Task: `t_7b09857c` (R-C1-D1), selected pilot cycle 1.
Mode: source evidence only, not mapping or public release.

## Frozen result

The task's private evidence archive contains the original governed
checkpoint's frozen `live/catalog.json`; sha256
`508cfc88e1f2595a493b053adfb4b80c0d93972cf658ac10fb27075616d6aa49`.
`receipts/coast-c1-discovery.json` pins its raw manifest and receipt.
The archive's `live/assessment.json` retains source-specific holds and
PC-3's regular-pyramid resolutions and citations. Raw outputs retain private
host paths and are deliberately not committed to the repository. The committed
summary is sanitized metadata; it is not a replacement frozen catalog.

One discovery30 checkpoint, 2026-10-21T00:10:46.868118Z through
2026-10-21T00:12:15.004913Z, used 7 requests and 71,161 response-body bytes;
receipt elapsed time is 88.173 seconds, within_caps=true. Limits remain
1,800 wall seconds / 1,500 discovery seconds, 250,000,000 bytes, 4 catalogs,
12 queries, 16 requests and 40 candidates. Two catalogs and seven queries
(including one supported literal redirect query) were used. No native source
was downloaded, no mapping was enqueued and no host allowlist was changed.

The existing host wrapper's bare listing adapter cannot express the USGS
FGDC fields. The task-local orchestration therefore used its unchanged
`check_plan`, the unchanged bounded discovery script's supported normalized
annotations / `add_query` / `finalize`, and the unchanged frozen-catalog
writer. Original plan bytes and canonical JSON plan hashes are separate
identities in the summary and raw receipt, respectively. The raw manifest
retains the added query and original authorization hash.

The original DOI query returned HTTP 302. Its exact on-list CMGDS Location
was followed within the same checkpoint and returned HTTP 200, confirming the
literal bathymetry ZIP link. The failure is not erased: bounded_plan_finished
is true, discovery_complete is false and manifest_status is PARTIAL. The
release HTML was used as link evidence, not ingested as another candidate.

## Claims and holds

- Cal DIG I v2 bathymetry: GeoTIFF in ZIP, 10 m native grid, 15,227 rows by
  11,242 columns, NAD83 / UTM 10N. Vertical datum is null with explicit
  "not stated" evidence, never inferred from horizontal NAD83. Its producer
  says small voids were filled; this is not blanket raw-measured support.
- H13089, H13151, H13152 and W00479 each have two literal live VR BAG links
  (MLLW and Ellipsoid filename variants). All eight files are explicitly VR,
  held P10 as original inputs. File labels do not establish inspected datum,
  horizontal CRS, refinement spacing, source rights or measured-cell support.
  PC-8 derived-output admission and its independent gates remain separate.
- W00431/W00433/W00444 have 8/16/32/64/128 m regular pyramids;
  W00443/W00447 have 16/32/64/128 m. These are PC-3 metadata evidence, not new
  live listings in this run. PC-3 says in-C1 cells are not_established for all
  five, so none was admitted to the frozen candidate list or acquisition.
- The producer abstract spells H1309. Preserve it, rather than silently
  changing it to H13089. H13089 is independently confirmed by PC-3 and NOAA.
- Historical 91,044,551 valid cells are a prior committed native audit, not a
  new native scan. Metadata bounds are envelopes, not valid-cell footprints.

All outputs remain review_required=true; semantic, mapping and publication
acceptance are false. Everything is not for navigation. The unstated-datum
G3 contract and native-header check belong to the later bridge, not this
metadata discovery.

## Reproduce offline verification

Use an existing survey runtime with jsonschema and pyproj, from the worktree:

    PYTHONPATH=src:. <survey-python> research/scripts/check_coast_c1_discovery.py \
      --receipts var/coast-pilot/t_7b09857c
    PYTHONPATH=src:. <survey-python> -m pytest -q \
      tests/unit/test_coastal_live_discovery.py \
      tests/contract/test_research_boundary.py tests/contract/test_receipt_manifest.py

The private evidence archive attached to the task includes the raw response
bodies, normalized annotations, original checkpoint and manifest, frozen
outputs, upstream PC-3 scope and all SHA256SUMS pins. Absolute response paths
in the original evidence are preserved rather than silently rewritten. If
the worktree is no longer present, restore those paths locally before running
the original manifest's native validator. Do not rerun discovery to repair a
missing copy; retrieve the task attachment.

Review path: pre-created local tier-1 screen -> tier-2 packet -> V-R-C1-D1
(`t_e9538cd3`, different-model reviewer `opus-coder`). Completion of this
implementation card releases that chain, not semantic acceptance. Cal DIG I
bridge task `t_6fe43227` is explicitly dependency-gated on V-R-C1-D1.
The regular-pyramid bridge remains ineligible absent valid-cell evidence.
No next discovery, acquisition, mapping, merge or publication is performed
by this card.
