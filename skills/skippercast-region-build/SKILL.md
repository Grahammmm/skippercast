---
name: skippercast-region-build
description: Use when a region's checked INTAKE.csv must be turned into private depth-contour candidates and a BUILD.json in its run folder. Runs the preflight and the builder; never publishes or writes in the repository.
skill_version: 1.0
---

# Region build

Reads a run folder's checked `INTAKE.csv`, preflights each GeoTIFF row, then runs the depth-contour builder at most twice
(approved rows, held rows) and writes `BUILD.json`. Machine-valid output is review-required, not acceptance.

## Inputs

- `<region_id>`: the region the run folder's INTAKE was made for.
- `--run <dir>`: the private run folder from `skippercast-region-intake`, outside the repository, e.g.
  `~/agent-work/skippercast/regions/<id>/runs/<YYYYMMDD>/`. It must hold `INTAKE.csv` and no `BUILD.json`.
- `--author-runtime <id>` and `--author-family <family>`: the actual model runtime running the build (for example
  `claude-opus-5-5`, `anthropic`). Never a profile name.
- `--python <exe>`: an interpreter with the survey stack (`requirements-survey.txt`); defaults to the current one.

## Steps

1. Check the intake: `python3 skills/skippercast-region-intake/scripts/region_intake.py --check <dir>` prints `INTAKE OK <n> rows`.
2. Build: `python3 skills/skippercast-region-build/scripts/region_build.py <region_id> --run <dir> --author-runtime <id> --author-family <family> --python <exe>`.
   It repeats step 1, runs `scripts/preflight_native_grid.py` per GeoTIFF row, then `scripts/build_depth_contours.py`
   with `--output` (approved) and `--held-output` (held).
3. On exit 1, read the failing command and stderr tail. `BUILD.json` is not written; partial outputs stay for diagnosis.
   Fix the input in a new run folder; never edit a candidate by hand.
4. Read `BUILD.json` `not_built`: `skip`/`missing-file` rows, `unsupported-adapter:<a>`, `multi-file-source:<id>:<n>`, `bag-survey-id-unknown`.
5. Hand the run folder to `skippercast-region-review` (`region_review.py <dir>`).

## Outputs

- `candidate/<id>.geojson`: approved-only collection (the builder's `check_contours` passed).
- `held/<id>.geojson`: candidate or draft-region grids, stamped `publication_held`; never published.
- `BUILD.json` (`region-build-v1`): `build_sha256`, author runtime and family, `inputs`, `outputs` (sha256, held flag and
  reason, contours per depth, survey-edge metres, supported-water fraction), `not_built` and `preflight`. Deterministic.
- The two outputs are traced separately; seams between them are checked by the review, not joined here.

## Never

- Pass a `skip` or `missing-file` row, open a restricted or unresolved-licence file, download, or re-screen.
- Write inside the repository (`catalog/`, `dist/`), overwrite `BUILD.json`, or convert a datum (INTAKE text is passed verbatim).
- Treat a machine-valid `BUILD.json` as acceptance: it is review-required.
- Merge the candidate and held outputs, or build terrain.

## Terrain

Terrain is not built by this skill. See `docs/operations/coast-statewide-runsheet.md` (the OC-STATE recipe) and
`skills/skippercast-map-coast/SKILL.md`. Terrain runs need S-030 admission (Q1).

## Golden case

`morro-bay` (real run M2) over the three USGS GeoTIFFs: the features of `candidate/morro-bay.geojson` must equal the
committed `catalog/depth-contours/morro-bay.geojson` features. Any difference is a spec-gap note.

## Changelog

- 1.0: first version.
