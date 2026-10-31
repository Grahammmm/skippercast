---
name: skippercast-region-intake
description: Use when a region's bathymetry bindings need a private, per-file intake table (licence, status, hash, screening verdict) before any build. Stdlib only; never downloads or opens restricted files.
skill_version: 1.1
---

# Region intake

Turns a region's bathymetry bindings, the source catalog, a private file-location list and the existing screening
verdicts into `INTAKE.csv` + `INTAKE.md` in a private run folder. Machine-valid output is review-required, not acceptance.

## Inputs

- `<region_id>`: a region under `regions/` with `source_bindings.bathymetry`.
- `--locations <json>`: private, never committed:
  `{"schema_version": 1, "files": [{"source_id": "...", "path": "/abs/file", "bbox": [w, s, e, n], "crs": "...", "screened_path": "/abs/derived.tif" | [...]}]}`
  (`bbox`, `crs` and `screened_path` optional; several entries may share a source id). `screened_path` names the derived
  tile(s) whose verdicts stand for the file (basename must contain the file's stem; never opened); any FLAG row for that stem, listed or not, makes it FLAG.
- `--screens <tsv>`: existing verdicts, default `~/agent-work/reports/MAP-VERDICTS.tsv`. Read only, never re-run.
- `--run <dir>`: private folder outside the repository, e.g. `~/agent-work/skippercast/regions/<id>/runs/<YYYYMMDD>/`.

## Steps

1. Run `python3 skills/skippercast-region-intake/scripts/region_intake.py <region_id> --run <dir> --locations <json>`.
2. Run `python3 skills/skippercast-region-intake/scripts/region_intake.py --check <dir>`; it must print `INTAKE OK <n> rows`.
3. Read `INTAKE.md` "Gaps and next action". For a missing source, use `skippercast-discover-coastal-sources`; the
   operator makes any download ask (host + URL).
4. Hand `INTAKE.csv` to the next unit. Rows with `use` other than `publish` are not build inputs.

## Outputs

- `INTAKE.csv`: one row per (source, file); `use` is publish / held / skip / missing-file; statuses and licences copied verbatim.
- `INTAKE.md`: row counts, out-of-bounds count and one next action per non-publish source.
- Deterministic: a re-run into a new folder is byte-identical. An existing `INTAKE.csv` is never overwritten.

## Never

- Download, add a host, or fetch a missing file.
- Open, stat or hash a restricted, unresolved or `dataset-review-needed` licence source's file.
- Re-screen, edit verdicts, upgrade `review_status`, convert datums or read raster headers.
- Write inside the repository, write `LEDGER.csv`, or commit run data.

## Golden case

`morro-bay` (the real run is unit M2). Command: `region_intake.py --check <run>` prints `INTAKE OK <n> rows`.

## Changelog

- 1.0: first version.
- 1.1: screened_path join (M5a).
