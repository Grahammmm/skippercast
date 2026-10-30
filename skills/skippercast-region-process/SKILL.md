---
name: skippercast-region-process
description: Use when taking a SkipperCast region from bathymetry bindings to a published depth-contour file. Orders the four stage skills, names the human gates and the ledger; a new region is a run, not code.
skill_version: 1.0
---

# Region process

Takes a region id through intake → build → review → publish with the four stage skills and one ledger. A new region is a
run, not code. Machine-valid output is review-required, not accepted.

## Inputs

- `<id>`: a region under `regions/` with `source_bindings.bathymetry`.
- `~/agent-work/skippercast/regions/LEDGER.csv`: one row per region (the operator creates it, step O5).
- A private locations file (`{"schema_version": 1, "files": [...]}`), never committed.
- The run folder `<run>` = `~/agent-work/skippercast/regions/<id>/runs/<YYYYMMDD>/`, outside the repository.

## Steps

1. Intake: `python3 skills/skippercast-region-intake/scripts/region_intake.py <id> --run <run> --locations <json>` ([`region_intake.py`](../skippercast-region-intake/scripts/region_intake.py)).
2. Check intake: `python3 skills/skippercast-region-intake/scripts/region_intake.py --check <run>` ([`region_intake.py`](../skippercast-region-intake/scripts/region_intake.py)); it prints `INTAKE OK <n> rows`.
3. Build: `python3 skills/skippercast-region-build/scripts/region_build.py <id> --run <run> --author-runtime <runtime> --author-family <family>` ([`region_build.py`](../skippercast-region-build/scripts/region_build.py)); runtime and family are the actual model, never a profile name.
4. Deterministic review: `python3 skills/skippercast-region-review/scripts/region_review.py <run>` ([`region_review.py`](../skippercast-region-review/scripts/region_review.py)).
5. Phone capture: `node skills/skippercast-region-review/scripts/phone_capture.mjs --mode held --run <run>` ([`phone_capture.mjs`](../skippercast-region-review/scripts/phone_capture.mjs)).
6. Agent first review, by a family different from `BUILD.json` `run.author_family`, writes `<run>/REVIEW.md` per [`PROMPT.md`](../skippercast-region-review/PROMPT.md); then `python3 skills/skippercast-region-review/scripts/region_review.py --check <run>` ([`region_review.py`](../skippercast-region-review/scripts/region_review.py)).
7. Publish: `python3 skills/skippercast-region-publish/scripts/region_publish.py <run> --repo <worktree>` ([`region_publish.py`](../skippercast-region-publish/scripts/region_publish.py)); exit 1 is held, and `PUBLISH.md` names the reason.
8. The PR opener opens the data PR from `PUBLISH.md` and pastes the output of `python3 ~/agent-work/bin/mergegate.py Grahammmm/skippercast <n> <head>`.
9. After merge: `python3 skills/skippercast-region-publish/scripts/region_publish.py --record-pr <run> --pr <n> --published-at YYYY-MM-DD` ([`region_publish.py`](../skippercast-region-publish/scripts/region_publish.py)).

## Outputs

- Run folder: `INTAKE.csv`, `INTAKE.md`, `BUILD.json`, `candidate/`, `held/`, `REVIEW-PACKET/`, `REVIEW.md`, `PUBLISH.md`.
- Ledger row columns: `region_id, stage, state, held_reason, last_run, build_sha256, review_verdict, reviewer_runtime, pr, published_at`.
- `state` is one of `not-started, intake, built, reviewed, held, published, blocked`.
- `held_reason` is one of `none, source-candidate:<id>, source-not-approved:<id>, region-draft, region-status:<s>,
  missing-file:<id>, 3d-rights, no-buildable-input, no-publishable-output, publication-held, review-missing,
  review-sha-mismatch, review-family, review-return, review-invalid, build-output-changed, build-not-reproducible,
  build-sha-mismatch, build-touched:<path>`.
- A held region is parked, not failed. Re-run publish after the blocker clears.

## Gates

| Gate | Who clears it |
| --- | --- |
| Deterministic checks (steps 2, 4) | Model: Terra (`luna-worker`) or the card's assignee |
| Agent first review (step 6) | Model of the other family, read from run metadata |
| Source acceptance (catalog `review_status`) | Human only |
| Draft-region promotion (PC-4b, t_6dd54ee3) | Human only |
| 3D rights | Human only |
| G's phone pass | Human only |
| Merge of the data PR | Standing approval: required CI green on the exact head plus an independent review |

Machine-valid is not accepted. Open data PRs one at a time. Never judge reviewer independence from profile names.

## Never

- Download. A missing file is one ask to G with the full list.
- Open `restricted` or unresolved-licence files.
- Convert a datum.
- Edit `review_status`.
- Hand-edit `catalog/depth-contours/*` or `dist/`.
- Re-run the screening queue.
- Run terrain without S-030 admission.
- Write region-specific code. A needed change is a **spec-gap**: log it in that stage skill's Changelog and give it its own unit.

## Golden case

`morro-bay` (unit M2). The intake → build → review run must reproduce the committed contour features, and publish must
report no change.

## Changelog

- 1.0 — 2026-xx-xx: first version (P10). The PR fills in the merge date.
