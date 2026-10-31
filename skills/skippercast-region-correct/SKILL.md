---
name: skippercast-region-correct
description: Use when a region run folder has a checked INTAKE.csv and its survey grids must be error-corrected before the build. Runs detect, apply and second-survey verify per file in batches of three, writes receipts, never decides a depth.
skill_version: 1.0
---

# Region correct (EC stage)

Sits between `skippercast-region-intake` and `skippercast-region-build`. Machine-valid receipts are review-required,
not acceptance. The operator runs commands and routes one-line results; every depth decision is inside the
deterministic tools. Shoal-biased: no fix ever makes a cell deeper.

## Inputs

- `<region_id>` and `--run <dir>`: the private run folder outside the repository (for example
  `~/agent-work/skippercast/regions/<id>/runs/<YYYYMMDD>/`) with a checked `INTAKE.csv` and no `EC.json` yet
  (resuming a partial `ec/` folder is allowed).
- `--author-runtime <id> --author-family <family>`: the actual model running this (e.g. `qwen3.8-27b`, `qwen`), never a profile.
- `--python <exe>`: an interpreter with the survey stack (`requirements-survey.txt`); the tools run as subprocesses.
- `--batch 3` (default and maximum): files treated per invocation. Rows with `use` other than `publish`/`held`, an
  adapter other than `geotiff` (BAG is wave 2) or several files per source are `not_corrected` and left as they are.

## Steps (local model alone: 1–6; Terra or the card owner: 7–8)

1. `python3 skills/skippercast-region-intake/scripts/region_intake.py --check <dir>` must print `INTAKE OK <n> rows`.
2. `python3 skills/skippercast-region-correct/scripts/region_correct.py <region_id> --run <dir> --author-runtime <id> --author-family <family> --python <exe>`
   treats up to 3 untreated rows, one line each: `EC <source_id> PASS|FIX|VERIFY|UNRESOLVED <counts>` or `EC <id> REFUSED <reason>`.
   Re-run the same command after `EC BATCH-DONE <treated>/<total>` until it prints `EC ALL-DONE <n> rows`.
3. Any exit 1 of `region_correct.py`: paste the stderr line (`EC STOP <source_id> <tool> <reason>`) in a card comment and stop. Do not edit a
   grid or delete `ec/`; the next run redoes that row from detect. Retry at most once.
4. `python3 skills/skippercast-region-correct/scripts/region_correct.py --check <dir>` must print `EC OK <n> rows`.
   It validates every `DONE`, receipt (schema, hashes, `ec_version`, no deepening) and `INTAKE-EC.csv`; writes nothing.
5. `cat <dir>/EC.md`. Copy its `Operator asks` list into the card comment verbatim (missing second survey, refused
   file, datum question). Never download; a missing second survey is one ask line.
6. Hand the run folder to `skippercast-region-build` (`region_build.py <region_id> --run <dir> …`).
7. (Terra / card owner) If `EC.md` asks for a second survey and an independent file exists on the box, add it to the
   private locations file and start a **new** run folder from intake (`region_intake.py`); this run is not edited.
8. (Terra / card owner) Escalate only on: a `REFUSED` row bound `publish` (custodian question), a `datum-suspect` line
   (human datum decision), or two stops on the same row (Opus medium per the ladder), with `region_correct.py --check <dir>` output.

## Outputs

- `ec/<source_id>/EC-DETECT.json`, `EC-APPLY.json`, `corrected.tif`, `provenance.tif`, `ENTRIES.json`,
  `verify/EC-VERIFY.json`, `verify/provenance.tif`, `verify/shoal_hint.tif` and `DONE` (sha256 of every file).
  A `REFUSED` row holds the detect receipt only. A row is treated when its `DONE` still matches.
- `EC.json` (`region-correct-v1`): author runtime/family, per source `status`, code counts, `second_surveys` tried
  (`independent`, `reason`, `comparable`), `second_survey_needed_cells`, `not_corrected`, `operator_asks`, `inputs`,
  `outputs` and `ec_sha256`. Deterministic; written once, when every row is done; never overwritten.
- `EC.md`: one line per source, then `Operator asks`.
- `INTAKE-EC.csv`: `INTAKE.csv` columns plus `ec_status`, `ec_path` (`ec/<id>/corrected.tif`, or the original path),
  `provenance_path` (`ec/<id>/verify/provenance.tif`, or empty). `REFUSED` rows get `use` `skip`, `held_reason` `ec-refused:<reason>`.

## Never

- Decide, type or edit a depth; edit a grid, receipt or `INTAKE.csv`; delete or rename anything under `ec/`.
- Download, add a host, open a `skip`/`missing-file`/restricted or unresolved-licence file, or re-screen.
- Treat two files or two resolutions of one survey, or a compilation (BlueTopo, NBS, GEBCO, GMRT), as a second survey;
  the tool refuses them and the operator does not override.
- Convert a datum, flip a sign, or fill a hole larger than the tool's threshold by hand.
- Treat `EC OK` as acceptance: it is review-required; the review (`region_review.py`, EC checks) and human gates follow.
- Run more than 3 files per invocation or more than two invocations after a stop.

## Golden case

`morro-bay` (run M2's three USGS grids): `region_correct.py --check` prints `EC OK 3 rows`; `EC.json` reports `filled`
≤ 3,300 cells in total and `pit` ≤ 80 cells, `verified` 0 (no independent second survey in the run), and no `REFUSED` row.

## Changelog

- 1.0: first version (EC4; draft by Fable, t_e5c1a99e).
