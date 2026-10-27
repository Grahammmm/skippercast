# SP1811 Report Count Sanitization

Scope: `get_port_report` serializes skipper-report counts from `counts_json`. `kept` and `released` are preserved only when each value is a JavaScript numeric safe integer greater than or equal to zero. Zero is meaningful and remains zero. Each invalid side becomes `null` independently; its valid sibling remains unchanged. No rounding or coercion is performed.

This change does not alter intake, stored records, daily summaries, landing-feed counts, freshness, boat verification, metadata clipping, row ordering, or the twelve-entry cap. The integration tests use only the migration-backed synthetic advisor database and the committed fixture in `tests/fixtures/sp1811_report_counts/counts.json`.

## Verification

Run the acceptance launcher from the staged repository with a unique output root per phase:

- `python3 scripts/accept_sp1811_report_counts.py --phase baseline --output <unique-out-root>` records the pre-fix A1 failing assertion and healthy control. The expected disposition is `BASELINE_GAP_REPRODUCED`; do not convert the original red receipt to green.
- `python3 scripts/accept_sp1811_report_counts.py --phase focused --output <unique-out-root>` runs A1-A7 and the healthy control against the fixed source.
- `python3 scripts/accept_sp1811_report_counts.py --phase regression --output <unique-out-root>` runs the unchanged advisor-tools and advisor-reports compatibility suites.
- `python3 scripts/accept_sp1811_report_counts.py --phase repository --output <unique-out-root>` uses the staged manifest's credential scanner runtime.
- `python3 scripts/accept_sp1811_report_counts.py --phase typecheck --output <unique-out-root>` runs the root, web and coast TypeScript projects separately.
- `python3 scripts/accept_sp1811_report_counts.py --phase build --output <unique-out-root>` runs the existing local build only.

The launcher stores command arguments, working directory, runtime, elapsed time, test counts where available, exit status, and SHA-256 hashes of raw stdout and stderr in a unique child directory. A scoped pass is review-required only: it is not full-repository acceptance, semantic/legal acceptance, CI approval, publication, or release authority.
