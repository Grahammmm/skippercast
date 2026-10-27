# Vessel field provenance at the history cap

Spec SP-15-v1; candidate SP1506-FIELD-PROVENANCE.

## Behavior and compatibility

`vesselDetail` now reads current fact provenance independently of its historical
fact page. The current-fact query excludes superseded rows and preserves the
old query's ordering among current rows. The original JavaScript value equality,
admin precedence, confidence comparison, recency comparator, and stable tie
behavior are unchanged. A missing current matching fact still yields null.
No stored vessel value, fact, pin, registry operation or decision is changed.

Historical output remains capped at 1000 facts with its existing order. Fetching
one extra historical row determines the additive `facts_truncated` boolean:
false for 0 through 1000 rows, true for more than 1000. The extra row is not
returned in `facts`. Existing small outputs retain their facts and pins.

The separate current query deliberately has no display cap: imposing the same
cap there would recreate the defect, including for many current different-value
facts of one field. It fetches only the six columns used by winner selection.
This preserves the exact existing JavaScript ranking rather than translating
`localeCompare` into a potentially different SQL collation. Current-fact memory
and CPU still scale with the number of current rows; this change does not claim
a total database-work cap, D1 performance qualification or snapshot isolation
across the detail route's multiple reads.

## Synthetic qualification

The complete real module is dynamically imported after offline network guards
and synthetic build globals. The request function receives an existing
migration-backed in-memory SQLite D1 adapter. No planner functions, preselected
winning rows, real stores, records, downloads or model calls are used. A wrapper
refuses non-SELECT product statements and snapshots vessel/fact tables around
each request. Build globals and network globals are restored after the test.
The original fleet-admin selector is run unchanged with process-scoped network
guards; its own Worker/session fixtures retain their original lifecycle.

The first setup attempt did not reach either assertion because a build global
was absent. Its failed receipt is retained outside the repository, never
relabeled as a reproduced baseline. Under the operator's standing adoption of
the recommended harness-only correction, synthetic pre-import configuration was
added without changing either test assertion or product code. The next baseline
executed exactly `primary regression` and `healthy control`: the primary failed
at the required year_built fact-ID assertion and the healthy control passed.
That is BASELINE_GAP_REPRODUCED, not repair success. The test and fixture bytes
were frozen at this baseline and are identical in final focused runs.

Acceptance mapping in `tests/test_sp1506_field_provenance.mjs`:

- A1: primary regression names the exact year_built=1999 fact after 1000 beam_ft
  historical rows; the identical fact without the history is the healthy control.
- A2: own-field large histories, both superseded and current different-value,
  cannot hide the matching winner. Superseded-admin and wrong-value-admin facts
  cannot win.
- A3: admin precedence, confidence, recency, stable fact-ID ties and absent
  matching facts; values and provenance remain honestly unknown when absent.
- A4: exactly 1000 and 1001 facts distinguish truncation without losing winning
  provenance; a small fixture retains full original fact output, JSON/null
  provenance and pins.

## Reproduction and evidence

Run from this repository using installed runtimes; no dependency installation:

    python3 scripts/accept_sp1506_field_provenance.py --suite focused --output ../out/reviewer-focused
    python3 scripts/accept_sp1506_field_provenance.py --suite regression --output ../out/reviewer-regression
    python3 scripts/accept_sp1506_field_provenance.py --suite repository --output ../out/reviewer-repository
    python3 scripts/accept_sp1506_field_provenance.py --suite typecheck --output ../out/reviewer-typecheck
    python3 scripts/accept_sp1506_field_provenance.py --suite build --output ../out/reviewer-build

Each command runs separately. Every invocation creates a fresh unique child
under its requested output root and records actual child argv/cwd/runtime,
exit, TAP counts where applicable, source identity, and separate stdout/stderr
hashes in `receipt.json`. Repository checks use only the credential-scan Python
from the operator's candidate-root SOURCE-MANIFEST.json, without a fallback.
Typecheck runs all three admitted tsconfigs as separate commands; build uses
the existing local `pnpm build` without deployment. Baseline mode is restricted
to unchanged pinned product bytes and expects only the exact semantic red pair;
do not run it against the fixed product or rewrite its retained receipts.

Material author: actual gpt-6.1-sol / openai-codex on sol-reviewer, runs 1852
(partial harness) and 1978 (harness correction, implementation and handoff).
The sole independent reviewer is actual Claude Opus 5.5 on opus-coder-bopus.
All material commits use a Signed-off-by trailer. Exact final head and the
post-execution frozen source/test/fixture and output hashes live in the
candidate's external handoff manifest, avoiding a self-referential commit hash.

Scoped green is REVIEW REQUIRED. Full-repository Node/Python discovery,
survey/GIS accounting, browser/e2e, dependency audit, exact-head CI, publication
and release remain with the operator and are OWED. This offline change grants
no live/source/hold release or human/legal/scientific/navigation acceptance.
