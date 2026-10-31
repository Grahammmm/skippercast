---
name: skippercast-region-review
description: Use when a region-build run folder needs its deterministic review packet and an agent first review before any human gate. Writes REVIEW-PACKET/review.json and validates REVIEW.md; never publishes.
skill_version: 1.1
---

# Region review

Machine-valid packet: review-required, not acceptance. A reviewer of another runtime family than the builder goes first.

## Inputs

- `<run>`: a private run folder from `skippercast-region-build`, outside the repository, holding `BUILD.json`,
  `candidate/` and/or `held/` outputs, and no `REVIEW-PACKET/review.json` yet.
- Optional phone captures from `scripts/phone_capture.mjs` (P8).

## Steps

1. Packet: `python3 skills/skippercast-region-review/scripts/region_review.py <run>` writes
   `<run>/REVIEW-PACKET/review.json` (exit 0 all PASS, 1 any FAIL, 2 refused).
2. Read each FAIL detail (up to 10 locations). Fix the input in a new run folder via `region_build.py`; never edit outputs.
3. Agent review: a reviewer whose runtime family differs from `BUILD.json` `run.author_family` reads the rubric
   (`cat skills/skippercast-region-review/PROMPT.md`) and writes `<run>/REVIEW.md`.
4. Validate: `python3 skills/skippercast-region-review/scripts/region_review.py --check <run>` prints `REVIEW OK <region_id> <overall>`.
5. 3D segments: not reviewed here; see `skills/coast-sign-off`.

## Outputs

- `REVIEW-PACKET/review.json` (`region-review-v1`): banner, region, build sha256, author runtime and family, thirteen
  checks (`outputs-intact`, `provenance-complete`, `datum-verbatim`, `omitted-stated`, `no-depth-crossings`,
  `size-budget`, `held-flags`, `supported-water`, `ec-receipts-intact`, `ec-no-deepening`, `ec-independence`,
  `ec-unresolved-stated`, `ec-thresholds-version` (PASS trivially with detail `no ec/ folder` when EC was not run)),
  `publishable` and `held_reason`. `REVIEW.md` is the agent's.

## Never

- Treat a PASS packet or REVIEW.md as acceptance, navigation approval, datum certification or rights clearance.
- Supply a human gate: noaa-bag acceptance (M4b), PC-4b draft promotion, 3D rights, G's phone pass.
- Judge reviewer independence from profile names, convert a datum, write anything but `review.json`, publish, or write the ledger (P9).

## Golden case

`morro-bay` (real run M2): `no-depth-crossings` PASS across all outputs together, in seconds.

## Changelog

- 1.0: first version.
- 1.1: EC checks (EC8).
