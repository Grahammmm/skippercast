# SP1505: port page daily answer keeps text before a self-link on a new line

Spec SP-15-v1, card SP1505-PORT-ANSWER-LINES (kanban t_5e600d8a). Staged base
`Grahammmm/skippercast` main at 8a805820.

## Defect

`withoutSelfLink` in `server/advisor/pages/port.ts` removes the trailing
`/ports/<id>?s=txt` link and its lead-in ("Full picture:") from the daily answer
shown on the port page. It found the last sentence end only as a literal
`. `, `! ` or `? `. When the lead-in started on a new line (LF, CRLF, a blank
line or a tab after the sentence end), no boundary was found, the whole text
before the link was treated as the lead-in, and because it ended in a colon the
page rendered an empty "Today's report" paragraph. This was reproduced on a
synthetic input; production frequency of newline-formatted stored answers is
UNVERIFIED.

## Change

The boundary is now the last `.`, `!` or `?` followed by any whitespace, or the
last line break. The kept text is the original bytes up to that boundary,
trimmed; internal line breaks are not rewritten. No-link input, the
period-space and bare-link forms, and a link in the middle of the text behave
as before.

## Tests

`tests/test_sp1505_port_answer_lines.mjs` with synthetic inputs in
`tests/fixtures/sp1505_port_answer_lines/cases.json`:

- baseline pair: `primary regression` (Quiet day., LF, Full picture link) and
  `healthy control` (the same with a space);
- A1 LF forms, A2 CRLF/blank-line/tab/`!`/`?`/Spanish forms, A3 unchanged
  behavior (also passes on the unchanged module), A4 the named request function
  `portPage` over real migrations in in-memory SQLite with a synthetic stored
  `advisor_daily_answers` row in English and Spanish, feeds as a throwing double.

Offline sentinels (network, child processes, file writes, on-disk SQLite) are
installed by `bootstrap.mjs` before any product import.

`scripts/accept_sp1505_port_answer_lines.py --suite <baseline|focused|regression|repository|typecheck|build> --output <candidate>/out/<label>`
writes a fresh receipt directory per run. Baseline is only valid while
`port.ts` still has its pinned bytes. Scoped green is REVIEW REQUIRED; full
repository CI and browser checks stay with the operator.
