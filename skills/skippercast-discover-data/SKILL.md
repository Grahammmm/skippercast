---
name: skippercast-discover-data
description: Find and evaluate regional marine data sources for SkipperCast by matching provider-independent data needs to authoritative local datasets, coverage, precision, rights and update methods. Use when expanding or enriching a fishing region.
---

Choose an available Python 3.11+ interpreter for the commands below (`python` is shorthand). If system Python is unavailable, use the runtime configured for the workspace. Keep that local executable path out of public region data.

Start from the requested region and fishing methods, not a familiar provider. Locate the SkipperCast repository from the user's project, then read `catalog/data-needs.json`, the selected `regions/<id>/region.json`, and relevant entries in `catalog/sources.json`.

Run `PYTHONPATH=src python -m skippercast.platform needs --region <id>` from that repository. Address the most consequential gaps first: legal geometry and native depth for bottom targets; actual forecast/observation coverage for conditions; effort and sampling for catch claims.

Search primary publisher catalogs using the data need plus geographic names, coordinates, management area, harbor and species scientific names. A neighboring region's source is a discovery lead, not evidence of coverage. Inspect exact dataset footprints and variables before binding a source. Distinguish the original producer from a mirror or API broker. Read [source-review.md](references/source-review.md) when evaluating candidates.

Record new leads as candidate records outside published app data until reviewed. Use `catalog/source-candidate.schema.json` and validate with `PYTHONPATH=src python -m skippercast.platform candidate --file <file>`. Include the exact documentation and access URLs, observed access outcome, original date, precision, variables, datum, license, limitations and supporting evidence links. Inaccessible sources remain inaccessible; search snippets can identify leads but cannot establish downloaded-data quality.

Return a need-by-need gap report, recommended source binding order, rejected alternatives with reasons, and the smallest useful next import. When two services distribute one underlying model or survey, count one independent source. Do not fill a critical gap by averaging unrelated evidence.

Preserve the current task's publishing authorization. Source discovery alone does not authorize a purchase, a provider-account signup, contacting operators, or publishing private catch histories. A missing license is a dataset issue to resolve, not an automatic request for user approval of routine research.

For ensembles, currents and species, record native resolution, horizon, member semantics, assimilation dependencies and life stage/method/geographic limits. Match `catalog/data-needs.json`; consult `docs/regional-intelligence.md` for adapter roles. A new footprint needs a regional review rather than an alias to a familiar source.
