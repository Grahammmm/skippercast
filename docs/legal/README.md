# Legal and commercial documents

Working documents for making SkipperCast legally launchable as a paid product. None of this is legal advice; items marked for counsel need a lawyer before launch.

| Document | What it answers | Status |
| --- | --- | --- |
| [data-rights-register.md](data-rights-register.md) | May a paid SkipperCast use each dataset and runtime service? Licence, attribution, commercial use, where it is used, action and owner. | First pass 2026-09-28; six launch blockers open |

Planned here (guide §8): `disclaimers.md` (the canonical user-facing caveats), `privacy-and-retention.md`, `threat-model.md`, and a link to the licensing ADR.

Related:

- [`catalog/sources.json`](../../catalog/sources.json) holds the machine-readable `rights.commercial_use` and `rights.attribution_required` fields.
- [`tests/contract/test_commercial_sources.py`](../../tests/contract/test_commercial_sources.py) is the CI gate that keeps the register and the shipped assets in step.
- [`NOTICE.md`](../../NOTICE.md) and [`docs/data-sources.md`](../data-sources.md) hold attribution and processing notes.
