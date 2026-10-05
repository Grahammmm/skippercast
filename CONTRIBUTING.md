# Contributing

SkipperCast is source-available for personal use under [LICENSE](LICENSE). Contributions must be original work you can offer under those terms; preserve all applicable third-party notices. This is not an OSI open-source project.

## Developer Certificate of Origin

Every commit from a contributor other than the repository owner and the project's own agents must carry a `Signed-off-by:` line certifying the [Developer Certificate of Origin 1.1](https://developercertificate.org/): that you wrote the change or otherwise have the right to submit it under this project's license, and that the contribution and your sign-off are recorded permanently. Add it with `git commit -s`; the name and email must match the commit author. To fix earlier commits on your branch, run `git rebase --signoff origin/main` and force-push your branch.

The [DCO workflow](.github/workflows/dco.yml) (`scripts/check_dco.py`) enforces this on every pull request. On branches of this repository it exempts the owner (`Grahammmm`, including Codex commits authored as the owner), Claude (`noreply@anthropic.com`) and Dependabot (`dependabot[bot]`) dependency updates. Pull requests from forks get no exemptions: every commit must be signed off, because commit authorship is only an email address that anyone can set.

Licensing and ownership may change before a paid launch; see [ADR 0004](docs/engineering/adr/0004-licensing.md). A sign-off does not transfer copyright; if the project moves to a proprietary license, outside contributors may also be asked to sign a contributor agreement.

## Get oriented

AI agents (Codex, Claude) and people follow the branch, pull-request and rebuild rules in [AGENTS.md](AGENTS.md).

Read [README.md](README.md), the [architecture](docs/architecture.md), and the [quickstart](docs/quickstart.md). Core runtime code uses Python 3.11+ and the standard library. Keep the dated atlas and reusable software separate.

## Check a change

From the repository root:

```bash
python3 -m pip install -e ".[test]"
python3 -m pytest -m "not gis"
PYTHONPATH=src python3 -m skippercast demo
python3 scripts/check_repository.py
```

Tests and CI must remain offline. Use synthetic fixtures for provider edge cases. Check missing values, coverage, units, issue times, returned grids, and delivery-state semantics when changing the monitor. An attractive screen is not evidence that a trip qualifies.

When changing atlas data, document the source, date, rights, datum, method, exclusions, and validation scope. Regenerate exports into a temporary output folder first and review the changes. Source checks and current on-water/legal conditions are different claims.

## Keep the public repository clean

Do not commit credentials, account/chat identifiers, private messages, delivery records, personal trip logs, large downloaded surveys, or third-party content with unresolved reuse terms. `.gitignore` is a convenience, not a guarantee; inspect the staged diff before publishing.

Text Advisor transcripts, photos, videos, contact data (phone numbers, Instagram ids and handles) and data exports are private records: they never enter the repository, not even as a test fixture. Fixtures are synthetic, with numbers from the fictional 555 series and handles listed in `catalog/advisor/fixture-handles.json`; `scripts/check_repository.py` enforces both ([02 § Privacy invariants](docs/plans/text-advisor/02-data-model.md#privacy-invariants-tested-in-teststest_advisor_privacymjs)).

Use an issue to describe a concrete bug or proposed change. Include a minimal synthetic reproduction for bugs. Pull requests should explain the resulting behavior, evidence, and relevant tests. Record material changes in [CHANGELOG.md](CHANGELOG.md).
