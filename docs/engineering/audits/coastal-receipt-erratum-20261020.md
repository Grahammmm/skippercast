# Erratum: two retained-byte figures in the 2026-10-20 four128 rerun receipts

Status: erratum only. No receipt was edited. Only byte counts are copied from the
private receipts; receipt paths are relative to the private `outputs/` directory.

## What needs correcting

Each rerun receipt carries two different retained-output byte figures. Readers
(including the T15c-c report v2 and `coastal-pipeline.md`) quote one of them
without saying which, and the two differ by about 4 MB. They measure different
things:

| Run | Receipt (SHA-256 prefix) | `du` observed bytes (`retained_bytes_du`, `du_bytes`) | Charged bytes (`retained_charged_bytes`, `charged_bytes`) |
| --- | --- | ---: | ---: |
| rerun1 | `t15-four128-rerun1-20261020/receipt.json` (`fad41b67c39a`) | 6,080,575 | 10,013,494 |
| rerun2 | `t15-four128-rerun2-20261020/receipt.json` (`ddc6845b8158`) | 6,080,170 | 10,013,089 |

`COAST-PROD-report-v2.md` (lines 76-77) quotes the charged figures
(10,013,494 B and 10,013,089 B). Those are the correct charge. The `du` figures
are an observation of disk use and are not the charge.

Source bytes charged are unchanged: 294,060,544 B in both receipts, consistent
with `coastal-pipeline.md` ("Each charged 294,060,544 source bytes").

## Which figure governs

The charged figure governs. The ruled retained-charge rule is: a run's retained
output is charged as complete entries' actual bytes plus still-open reserved
bytes, per the managed-output ledger (`managed-output.json`). It is not the `du`
reading and not the writer's ceiling-plus-overhead audit figure. Writer
`_audit` ceiling-plus-overhead figures are informational only.

- Ruling: `decisions/G-DECISIONS.log` line 14, entry dated 2026-10-20 03:15Z
  (Mon 20:15 PDT), decision (2): "Retained-output accounting rule for failed
  attempts is RULED: complete entries' actual bytes + still-open reserved bytes
  per managed-output.json ledger". The same entry says the retained charge is
  not refundable (standing no-refund rule).
- Scope note: that entry states the rule for failed attempts of the T08 series.
  The receipts' own `rule` field (rerun1 line 842, rerun2 line 1072) states the
  same wording, "complete actual_bytes + open reserved bytes (managed ledger)",
  and both reruns' charged figure is computed under it. This erratum applies the
  ruling's wording to the rerun receipts on the strength of that identical rule
  text; it does not claim a separate ruling naming the reruns. If G wants a
  separate ruling for the reruns, that is a separate decision.

## What is not changed

- Neither receipt, nor any hash cited for them, changes.
- `coastal-pipeline.md` needs no change here (its source-byte statement matches).
- Nothing is published from the private outputs.
