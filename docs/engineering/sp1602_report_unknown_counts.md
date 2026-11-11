# Advisor count display semantics

The advisor formatter must distinguish a valid nullable count from a measured zero. A row where both `kept` and `released` are null has no measured catch and is omitted from the rendered counts text. Explicit numeric zero remains visible, as do kept counts, released-only counts, and mixed kept/released formatting. Remaining measured rows retain their original order and the existing HTML escaping boundary.

This is display-only behavior. It does not change intake validation, species aggregation, storage representation, or catch policy. `countLines` continues to represent missing/non-finite values as null.

Offline regression fixtures use the producer-shaped `counts_json` list in `tests/fixtures/sp1602_report_unknown_counts/counts.json`. Focused coverage also exercises `reportsTable`, the actual advisor report-table consumer, to confirm measured labels remain HTML-escaped there. Run the ordinary offline regression checks directly:

```bash
node --test tests/test_sp1602_report_unknown_counts.mjs
node --test tests/test_advisor_pages.mjs
```

The historical staged acceptance launcher for this card is retired (it remains in git history). These commands do not recreate its old baseline receipts or reproduce its expected-red baseline, and a pass is not full repository or semantic acceptance.
