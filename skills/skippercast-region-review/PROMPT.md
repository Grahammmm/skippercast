# Region review: agent first-pass rubric

Machine-valid ≠ accepted. You give an agent first review; the human gates stay human.

## Before you start
- Read `BUILD.json` `run.author_family`. Your runtime family must differ from it (case-insensitive); if it is the same,
  stop and hand the run back. Never judge independence from profile names or aliases.
- Inputs: `REVIEW-PACKET/review.json`, `BUILD.json`, `INTAKE.md` and any P8 phone captures in the run folder.

## For each check in review.json
- Confirm it (PASS) or RETURN it, with one line of reason. Never PASS a check review.json marks FAIL. `supported-water`
  only states a fraction; do not judge coverage from it.

## Visual row
- Open each screenshot you actually inspect and cite its file name and sha256 (`sha256sum <file>`).
- If you inspected none, write `not-visually-inspected` and say why. Never describe an image you did not open.

## Never state
Acceptance, approval for navigation, datum certification or rights clearance. These gates stay human: noaa-bag
acceptance (M4b), PC-4b draft promotion, 3D rights, and G's phone pass.

## Write `<run>/REVIEW.md` exactly in this form
```
# REVIEW <region_id> <run folder name>
Machine-valid ≠ accepted. Agent first review; human gates remain.
Build-SHA256: <build_sha256 from BUILD.json>
Reviewer-Runtime: <your actual runtime id>
Reviewer-Family: <your family>
| check | verdict | reason |
|---|---|---|
| <each review.json check id, once> | PASS or RETURN | <one line> |
| visual | PASS, RETURN or not-visually-inspected | <screenshot file + sha256 cited, or why not> |
Overall: PASS | RETURN
```
Overall is RETURN when any row is RETURN. Then run `region_review.py --check <run>`; it must print
`REVIEW OK <region_id> <overall>`. Fix only the REVIEW.md format on a rejection, never the run.
