# Avila Point to Estero atlas: export consistency

| Check | Result |
| --- | --- |
| R1. File integrity | All six payloads match the manifest by SHA-256 and byte size. The manifest does not list itself. |
| R2. Content | 132 waypoints, 107 reef outlines, 31 drift lines. No unexpected missing, extra, or duplicate IDs. All 132 spot notes agree with their GeoJSON and GPX counterparts. |
| R3. Dates, versions, and positions | Data and exports agree on positions and the edition where it is recorded. The README names the older edition, and the methodology still asserts MLLW despite the September 27 datum correction. |
| R4. Follow-up | One documentation-only correction; no export rebuild indicated by this comparison. |

Evidence is from offline reads on 2026-11-21 (PST) at local `origin/main` `34761911d5c44a903873867426f316c7f1e5911c`, the card baseline. File references below are relative to `atlas/avila-point-estero-2026-09-20/` unless they start with `docs/`, `src/` or `tests/`. This checks the checked-in package, not live downloads, device imports, source surveys, or present conditions.

## R1. Hashes and byte sizes

Run from the repo root:

```sh
cd atlas/avila-point-estero-2026-09-20/exports
sha256sum *
wc -c -- *
nl -ba manifest.json
```

| File in `exports/` | Measured SHA-256 | Manifest SHA-256 | Measured bytes | Manifest bytes | Both match? | Manifest lines |
| --- | --- | --- | ---: | ---: | --- | --- |
| `atlas.geojson` | `e82d2fd5c00ebf2314af154ef0db7cb83ef222082e7323f5bcf90c9ff92c5b1a` | `e82d2fd5c00ebf2314af154ef0db7cb83ef222082e7323f5bcf90c9ff92c5b1a` | 580368 | 580368 | Yes | 14–16 |
| `complete.gpx` | `56c2c1eb960bc02a53b9b8fdaa3a1f5f9ba3dd7d5e608edf26d0680467f724c0` | `56c2c1eb960bc02a53b9b8fdaa3a1f5f9ba3dd7d5e608edf26d0680467f724c0` | 612911 | 612911 | Yes | 19–21 |
| `drift-lines.gpx` | `6a3f3227220aff2a4b5875b6e6962c4071193cf86f110c0d3da2ce38ecffb60b` | `6a3f3227220aff2a4b5875b6e6962c4071193cf86f110c0d3da2ce38ecffb60b` | 22066 | 22066 | Yes | 24–26 |
| `manifest.json` | `ff177d53045499e4cb2cbe914a31f312505026572ff0422a31c7de836c04f9de` | Not listed | 1194 | Not listed | N/A | 12–43 |
| `reef-outlines.gpx` | `ff96b81dad6e40ed8e17bf8b13ace612297e9125424984d15ff2b8e11811fbf5` | `ff96b81dad6e40ed8e17bf8b13ace612297e9125424984d15ff2b8e11811fbf5` | 362064 | 362064 | Yes | 29–31 |
| `spot-notes.html` | `99c6014072bbf74804d3f89eaf804e89fab7f1675367c79b055bdb18a7ca5825` | `99c6014072bbf74804d3f89eaf804e89fab7f1675367c79b055bdb18a7ca5825` | 202388 | 202388 | Yes | 34–36 |
| `waypoints.gpx` | `204b969fe7ae3277016244bb295d46c471b554ea6241b62327a9ca53706e45e5` | `204b969fe7ae3277016244bb295d46c471b554ea6241b62327a9ca53706e45e5` | 230877 | 230877 | Yes | 39–41 |

No unlisted payload or missing manifest member: the 2026-11-21 read returned `Missing/extra manifest entries (excluding manifest itself): set()`. The exporter lists files before writing the manifest and does not hash the input JSON or README (`src/skippercast/atlas/export.py:326–344`, `README.md:17–18`).

## R2. Counts and IDs

| File | Waypoints / targets | Reef outlines | Drift lines | Source IDs absent from this file |
| --- | ---: | ---: | ---: | --- |
| `data/atlas.json` | 132 | 107 | 31 | Reference sets: `targets`, `areas`, `drifts` (lines 38, 7058, 35728) |
| `exports/manifest.json` | 132 | 107 | 31 | Only counts, no per-feature IDs (lines 2–9, 12–43) |
| `exports/atlas.geojson` | 132 `Point` | 107 `Polygon` | 31 `LineString` | None |
| `exports/complete.gpx` | 132 `wpt` | 107 `trk` | 31 `rte` | None |
| `exports/drift-lines.gpx` | 0 | 0 | 31 `rte` | All 132 target IDs and all 107 outline IDs, by design |
| `exports/reef-outlines.gpx` | 0 | 107 `trk` | 0 | All 132 target IDs and all 31 drift IDs, by design |
| `exports/waypoints.gpx` | 132 `wpt` | 0 | 0 | All 107 outline IDs and all 31 drift IDs, by design |
| `exports/spot-notes.html` | 132 articles | 0 geometries | 0 geometries | No missing target articles; outlines and lines are referenced in prose, not exported as shapes |

**How IDs were matched.** Read JSON arrays by `id`, GeoJSON by `geometry.type` and `properties.id`, and GPX 1.1 XML by top-level `wpt`, `trk`, and `rte`. Join each GPX waypoint `<name>` to `targets[].name` to recover its canonical `id` (e.g., `SC26-001-A` → `SC26-001`, `data/atlas.json:39–43`); track and route names are already IDs. Count each track once, not once per ring, and each route once, not once per endpoint. Read notes by `<article id>`. These mappings and component choices are visible in `src/skippercast/atlas/export.py:179–218,258–275,333–337`; the download descriptions are at `README.md:11–18`.

**Read-only result, 2026-11-21 13:57 PST:** for each included class in the table, `dup [] extra [] unexpected missing []`; no duplicate, export-only, or missing IDs. The component union equals `complete.gpx` by class and ID. `complete.gpx` and the matching component files had `298` track segments (6,317 vertices, including ring closures) and `62` route endpoints. GeoJSON has 270 features. The source counts by survey are `MorroBay: 47, PointEstero: 45, PointBuchon: 40`; grade counts are `A: 35, B: 74, C: 23` (agree with `README.md:3,24,28`, `exports/manifest.json:2–9`, and the 132-target ranking scope at `docs/atlas-methodology.md:27`).

**Spot notes, same read:** `parsed and literal article count 132 132`; `HTML title text mismatches: []`; `note area/drift linked IDs differ from data: []`. After decoding HTML entities and mapping `<br>` back to newlines, the per-ID note texts matched GeoJSON `properties.note` and both waypoint-bearing GPX `<desc>` fields (`notes differing from GeoJSON: False` for each). The notes are not additional waypoints or geometries. The shared note builder uses source year, legacy ID, edition, and associated area/drift IDs (`src/skippercast/atlas/export.py:137–169,187–196,258–275`).

## R3. Dates, version words, and coordinate ranges

| Statement and location | Comparison to the data and exports |
| --- | --- |
| `README.md:5`: edition `2026-09-20-public-1` | **Mismatch.** `data/atlas.json:3` and `exports/manifest.json:11` say `2026-09-27-datum-audit-2`; so does `exports/spot-notes.html:6`. The September 20 folder name is not the edition field. |
| `README.md:5,24`: 200-foot personal limit; surveys acquired in 2008; September 27, 2026 correction withdrew MLLW and chart-depth qualification | **Agrees.** `data/atlas.json:6–8,13–17,22–26,31–35` records the 200-ft limit, 2026-09-27 validation date, and 2008 surveys with unresolved output datum. A recorded numeric limit is not qualification; see a target's flags at `data/atlas.json:74–90` and `exports/manifest.json:10`. |
| `docs/atlas-methodology.md:3,41`: September 2026 research effort and source checks dated September 20, 2026 | Research timing is consistent with the September timeline; September 20 is described as the original screen, not the date in the current `source_validation_date` field (September 27, `data/atlas.json:7–8`). The bundled data does not independently confirm the date of the original screen. |
| `docs/atlas-methodology.md:39`: public subset uses MLLW-referenced grids | **Mismatch.** Data says `unverified source datum` at `data/atlas.json:14,23,32,59`; the September 27 withdrawal is explicit at `data/atlas.json:8` and `README.md:24`. The exported notes say unverified (`exports/spot-notes.html:6`); the manifest does not grant depth clearance (`exports/manifest.json:10`). |
| `docs/atlas-methodology.md:35,39,41`: original 150–400 m alignments, at least 70% mapped rough habitat in a 25-m half-corridor; ≤195 ft conservative geometry screen, ≥500 m margin | **Recorded measurements only.** November 21 read: 31 half-widths of 25 m, minimum recorded fraction `0.7058823529411765`; lengths about 200–400 m (11 values exceed 400 by less than `0.000000001` m; validator accepts 150–401 m, `src/skippercast/atlas/export.py:124–131`). Largest recorded maxima about 189.99 ft (outline) and 191.54 ft (drift); smallest recorded clearances about 505.00 and 506.36 m respectively. Target center and neighborhood maxima were about 180.25 and 190.18 ft. These are rounded summaries of `recorded_validation` fields, not new depth or clearance measurements (`data/atlas.json:38,7058,35728`; checks at `src/skippercast/atlas/export.py:73–81,100–110`). |
| `README.md:38`: coordinates to six decimal places; `README.md:24,26`, `docs/atlas-methodology.md:55`: public coverage excludes Cambria | Six places in GPX and notes; GeoJSON preserves the input precision, including more than six places for outline/drift vertices (`src/skippercast/atlas/export.py:187–216,258–275`). The source count by area in R2 agrees with the coverage words; data names the span and exclusion at `data/atlas.json:5`. None of the README, manifest, or methodology asserts numeric geographic min/max bounds (coverage/precision at `README.md:22–38`; all manifest fields at `exports/manifest.json:1–44`; positions section at `docs/atlas-methodology.md:37–41`). |
| Version and date fields in the package | `schema_version: 1` is the data schema (`data/atlas.json:2`, validated at `src/skippercast/atlas/export.py:51–54`); `version="1.1"` and `creator="SkipperCast 0.1.0"` are GPX format and writer labels (line 2 of each GPX), not edition IDs. November 21 read: all 132 notes in each of GeoJSON, complete GPX, waypoints GPX and HTML carry `2026-09-27-datum-audit-2`; outline/drift-only GPX files contain no waypoint notes. No GPX `<time>` or `<bounds>` elements were found. GeoJSON has `type` and `features`, with edition text in point notes, not a collection-level version field (`src/skippercast/atlas/export.py:167,179–218,258–267`). The manifest has an edition but no separate timestamp, schema version, or bounding box (`exports/manifest.json:1–44`). |

**Measured coordinate extents** (degrees; signed longitude first, then latitude). The 2026-11-21 read reduced coordinates by class, taking min/max over every point, every vertex of every ring, and both endpoints of each drift. Ordered positions matched by ID with zero differences: decimal equality for GeoJSON, equality after formatting data to six places for GPX and notes. All are within the validator's global WGS84 limits (`src/skippercast/atlas/export.py:29–36`); these measured extents are not claimed survey boundaries.

| Class (observed positions) | Data and GeoJSON longitude | Data and GeoJSON latitude | GPX longitude | GPX latitude |
| --- | --- | --- | --- | --- |
| Targets (132; spot notes match GPX) | −121.114515 to −120.788686 | 35.145341 to 35.540362 | −121.114515 to −120.788686 | 35.145341 to 35.540362 |
| Outlines (6,317) | −121.11784081615909 to −120.78555852043647 | 35.1452700528978 to 35.54199198251036 | −121.117841 to −120.785559 | 35.145270 to 35.541992 |
| Drift lines (62) | −121.10082203508337 to −120.78719429944931 | 35.1523628062749 to 35.511702678755285 | −121.100822 to −120.787194 | 35.152363 to 35.511703 |

## R4. One possible follow-up

**Synchronize the atlas documentation with the checked-in datum-audit edition** (estimate: 45 minutes). In a separate docs-only change, update `atlas/avila-point-estero-2026-09-20/README.md:5` to match the recorded edition, clarify at `README.md:38` which formats use six decimal places, and reconcile `docs/atlas-methodology.md:39–41` with `data/atlas.json:6–8,13–17`: distinguish the original screen from the later audit and the recorded thresholds from depth qualification. As an offline acceptance check, compare those statements to the data header, README correction and manifest edition; run `python scripts/check_repository.py` and require a diff limited to those two docs. No exporter or data change is warranted for the discrepancies in R3.

Existing coverage is different: `tests/contract/test_atlas.py:23–34,42–47` checks scope and rejects a reintroduced MLLW claim in the data; `tests/contract/test_atlas.py:57–80,89–96` checks freshly generated contents and equality with the shipped exports, not the README edition or methodology wording. No decision on publication, rights, privacy, or use on the water is part of this report.
