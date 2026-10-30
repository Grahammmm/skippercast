---
name: skippercast-region-publish
description: Use when a region-build run has a cross-family REVIEW.md and its depth-contour candidate may go into the repo. Enforces the publish rule, copies the candidate into a work tree, proves the build reproduces and drafts PUBLISH.md; never commits or deploys.
skill_version: 1.0
---

# Region publish

## Inputs

- `<run>`: a reviewed run folder outside the repository (`BUILD.json`, `candidate/<id>.geojson`, `REVIEW.md`).
- `--repo <worktree>`: a disposable work tree of main, outside `<run>`. `--ledger <csv>` defaults to `~/agent-work/skippercast/regions/LEDGER.csv`
  and needs the plan header and the region's row (else `missing LEDGER.csv row <id> (operator step O5)`). `--python <exe>` runs build and review check.

## Steps

1. `python3 skills/skippercast-region-review/scripts/region_review.py --check <run>` prints `REVIEW OK <id> PASS`.
2. `python3 skills/skippercast-region-publish/scripts/region_publish.py <run> --repo <worktree>`: exit 0 ready, 1 held or refused.
3. Held: read `<run>/PUBLISH.md` (`HELD: <reason>`, detail, `Next:`) and fix upstream; the work tree is unchanged. Exit 2 is `REPO NOT RESTORED`: stop, tell the operator.
4. Ready: only `catalog/depth-contours/<id>.geojson` and `dist/` change. Sol medium (or the assigned PR opener) opens the data PR from PUBLISH.md.
5. Paste `python3 ~/agent-work/bin/mergegate.py Grahammmm/skippercast <n> <head>` in the PR; after merge run `region_publish.py --record-pr <run> --pr <n> --published-at YYYY-MM-DD`.

## Outputs

`<run>/PUBLISH.md` (never overwritten); on a pass the copied catalog file and rebuilt `dist/`. Only the region's LEDGER row changes: pass `stage=publish, state=reviewed`
(verdict `PASS (visual not inspected)` without a capture); held `state=held, held_reason`; `--record-pr` sets `pr`, and with a date `state=published`, `published_at`.
Held reasons, in check order (they extend the plan's ledger enum): `no-publishable-output`, `build-output-changed`, `publication-held`, `source-candidate:<id>`,
`source-not-approved:<id>`, `region-draft`, `region-status:<status>`, `review-missing`, `review-sha-mismatch`, `review-family`, `review-return`, `review-invalid`,
`build-not-reproducible`, `build-touched:<path>`.

## Never

- Treat machine-valid output as accepted, or merge: merging to main is publishing and stays with the standing approval (CI green on the exact head + independent review).
- Run git, the GitHub CLI, a deploy or any network call from the script, or weaken a gate or supply a human gate (PC-4b, noaa-bag acceptance, 3D rights, G's phone pass).

## Golden case

`morro-bay` (M2 run): the candidate equals the committed file, so publish reports "no change" and the work tree stays clean.

## Changelog

- 1.0: first version.
