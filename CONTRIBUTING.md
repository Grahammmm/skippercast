# Contributing

SkipperCast is source-available for personal use under [LICENSE](LICENSE). Contributions must be original work you can offer under those terms; preserve all applicable third-party notices. This is not an OSI open-source project.

## Get oriented

Read [README.md](README.md), the [architecture](docs/architecture.md), and the [quickstart](docs/quickstart.md). Core runtime code uses Python 3.11+ and the standard library. Keep the dated atlas and reusable software separate.

## Check a change

From the repository root:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
PYTHONPATH=src python3 -m skippercast demo
python3 scripts/check_repository.py
```

Tests and CI must remain offline. Use synthetic fixtures for provider edge cases. Check missing values, coverage, units, issue times, returned grids, and delivery-state semantics when changing the monitor. An attractive screen is not evidence that a trip qualifies.

When changing atlas data, document the source, date, rights, datum, method, exclusions, and validation scope. Regenerate exports into a temporary output folder first and review the changes. Source checks and current on-water/legal conditions are different claims.

## Keep the public repository clean

Do not commit credentials, account/chat identifiers, private messages, delivery records, personal trip logs, large downloaded surveys, or third-party content with unresolved reuse terms. `.gitignore` is a convenience, not a guarantee; inspect the staged diff before publishing.

Use an issue to describe a concrete bug or proposed change. Include a minimal synthetic reproduction for bugs. Pull requests should explain the resulting behavior, evidence, and relevant tests. Record material changes in [CHANGELOG.md](CHANGELOG.md).
