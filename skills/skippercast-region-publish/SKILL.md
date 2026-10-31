---
name: skippercast-region-publish
description: Use when a region-build run has a cross-family REVIEW.md and its depth-contour candidate may go into the repo. Enforces the publish rule, copies the candidate into a work tree, proves the build reproduces and drafts PUBLISH.md; never commits or deploys.
skill_version: 1.1
---

# Region publish

## Inputs

- `<run>`: a reviewed run folder outside the repository (`BUILD.json`, `candidate/<id>.geojson`, `REVIEW.md`).
- `--repo <worktree>`: a disposable work tree of main, outside `<run>`. `--ledger <csv>` defaults to `~/agent-work/skippercast/regions/LEDGER.csv`
  and needs the plan header and the region's row (else `missing LEDGER.csv row <id> (operator step O5)`). `--python <exe>` runs build and review check.

## Steps

1. `python3 skills/skippercast-region-review/scripts/region_review.py --check <run>` prints `REVIEW OK <id> PASS`.
2. `python3 skills/skippercast-region-publish/scripts/region_publish.py <run> --repo <worktree>`: exit 0 ready, 1 held or refused.
   Point 6: when `<run>/ec/` exists (or `BUILD.json` `ec` is not null), both must exist, `region_correct.py --check <run>` must print `EC OK`,
   `BUILD.json` `ec.ec_sha256` must equal `EC.json` `ec_sha256` and every `EC-APPLY.json` must have `deepened_cells` 0; the PR body then
   states the error-correction counts. A run without `ec/` and with `ec: null` publishes exactly as before.
3. Held: read `<run>/PUBLISH.md` (`HELD: <reason>`, detail, `Next:`) and fix upstream; the work tree is unchanged. Exit 2 is `REPO NOT RESTORED`: stop, tell the operator.
4. Ready: only `catalog/depth-contours/<id>.geojson` and `dist/` change. Sol medium (or the assigned PR opener) opens the data PR from PUBLISH.md.
5. Paste `python3 ~/agent-work/bin/mergegate.py Grahammmm/skippercast <n> <head>` in the PR; after merge run `region_publish.py --record-pr <run> --pr <n> --published-at YYYY-MM-DD`.

## Outputs

`<run>/PUBLISH.md` (never overwritten); on a pass the copied catalog file and rebuilt `dist/`. Only the region's LEDGER row changes: pass `stage=publish, state=reviewed`
(verdict `PASS (visual not inspected)` without a capture); held `state=held, held_reason`; `--record-pr` sets `pr`, and with a date `state=published`, `published_at`.
Held reasons, in check order (they extend the plan's ledger enum): `no-publishable-output`, `build-output-changed`, `publication-held`, `source-candidate:<id>`,
`source-not-approved:<id>`, `region-draft`, `region-status:<status>`, `build-sha-mismatch` (canonical sorted output path/hash identity changed; rebuild and re-review), `review-missing`, `review-sha-mismatch`, `review-family`, `review-return`, `review-invalid`,
`ec-receipt-invalid`, `ec-deepened:<id>`, `build-not-reproducible`, `build-touched:<path>`. A refused `publish` source with no other output stays
`no-publishable-output`, and `Next:` names `ec-refused:<id>:<reason>` from `EC.json` `operator_asks` (a custodian decision).

## Never

- Treat machine-valid output as accepted, or merge: merging to main is publishing and stays with the standing approval (CI green on the exact head + independent review).
- Run git, the GitHub CLI, a deploy or any network call from the script, or weaken a gate or supply a human gate (PC-4b, noaa-bag acceptance, 3D rights, G's phone pass).

## Golden case

`morro-bay` (M2 run): the candidate equals the committed file, so publish reports "no change" and the work tree stays clean.

## Changelog

- 1.0: first version.
- 1.1: publish rule point 6 (EC9).
