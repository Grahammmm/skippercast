# Data contracts

SkipperCast asks what it needs before choosing a supplier. A region binds those needs to specific reviewed sources; a source's reputation does not establish regional coverage or current freshness.

| Contract | Location | Purpose |
| --- | --- | --- |
| Data needs | `catalog/data-needs.json` | Questions, required variables/units, update cadence, capability gates and invalid inferences |
| Source registry | `catalog/sources.json` | Original producer, adapter, rights, documentation, limits and review state |
| Discovery candidate | `catalog/source-candidate.schema.json` | A lead with observed access, geographic precision, timing and evidence; never automatic approval |
| Region | `regions/<id>/region.json` | Extent, harbor, boat, stations, jurisdiction, sources, assets and per-need coverage |
| Jurisdiction | `jurisdictions/<id>.json` | Reusable official regulation sources and reviewed rules asset |
| Published manifest | `dist/regions/<id>/manifest.json` | Public asset identities, sizes and SHA-256 digests |
| Runtime feed | `data` / `conditions` Git branches | Region ID, source receipts, original timestamps, validated units and failure state |

Machine-readable shapes for these contracts and for every published feed live in [`schemas/`](../schemas) as JSON Schema (draft 2020-12): region, source and source catalog, data needs, jurisdiction, daily feed, live conditions feed, regional intelligence feed, feed regions index, published region index and package manifest, coverage report, and the forecast index, model manifest and tile. They check required keys, types and enums; cross-references (a binding names a catalog source, a legal watch matches the registry) stay in `platform/contracts.py` and `pipeline/regulations.py`. Objects that providers or reviewers legitimately extend allow extra keys, and each schema's `description` says so. Validate a file with `PYTHONPATH=src python -m skippercast validate <kind> <path>` (`feed` detects daily, live or intelligence); it needs the optional `jsonschema` package from `requirements-test.txt` and exits 2 with an install hint without it. `tests/contract/test_schemas.py` validates every committed region, jurisdiction and catalog file, the generated `dist/regions/*` packages and trimmed samples of the live feeds in `tests/fixtures/feeds/`. Change the schema in the same pull request as the writer.

**Validate on write.** The writers check the schema before their first write and raise `ContractError` (a `ValueError`) instead of publishing a bad shape: regional daily and live `latest.json` and the feed `regions/index.json` (`scripts/refresh_regions.py`), `intelligence.json` (checked before its verification archive is written), the single-region daily CLI, and the generated `dist/regions/*` region, coverage and manifest files plus `dist/regions/index.json`. `atomic_json(path, value, kind=...)` and `skippercast.validate.check(kind, value)` do this. A region whose feed fails the check is recorded as failed in the index and keeps its previous publication. Validation runs when `jsonschema` is installed (the `publish` extra and `requirements-publish.txt`, which the daily and live jobs install) and is skipped with one warning otherwise; set `SKIPPERCAST_VALIDATE=off` only to publish past a schema bug in an emergency. `validate_region` uses `schemas/region.schema.json` for shape and keeps the cross-reference checks (bounding-box order, time zone, catalog targets, ecology dossier, legal notices, forecast points, context zones, source bindings, assets, public URLs); without `jsonschema` it runs equivalent imperative shape checks, and `tests/contract/test_region_contract.py` proves the two agree. Schema `pattern`s are matched with ECMA-262 semantics (`$` is end of string), as in browsers.

The registry has **approved**, **candidate**, **restricted**, and **unavailable** states. Approved means the documented use has passed a source/rights review, not that all data from the organization are reliable or licensed for every use. Regional coverage separately has **ready**, **partial**, **research**, **missing**, or **not-applicable** states. Runtime source status separately records **ok**, **stale**, **retained**, **failed**, or **missing**. Confidence belongs to a specific claim and method, not to a provider logo.

Every imported observation must retain producer and dataset identity, requested and returned coordinates, horizontal/vertical reference, units, native resolution or position uncertainty, source observation/issue/model-initialization time when supplied, retrieval time, source URL, transformation version, rights, and raw-response digest. Unknown fields stay null. A HTTP Last-Modified header is transport metadata. Open-Meteo is an access service; NOAA GFS and ECMWF are model producers.

Reject duplicate JSON keys, nonfinite numbers, unknown identifiers, escaping paths and non-public URLs. Validate units before conversion, forecast array lengths and actual populated times, finite coordinates, geometry completeness and MPA exclusion. A complete file may still have geographic or temporal gaps. Masked seabed cells remain masked. Never promote a coarse contour into a precise sounding, surface current into bottom current, AIS loiter into catch evidence, or an old landing total into today's bite score.

An adapter has four responsibilities: acquire a bounded response; retain a receipt; normalize its actual fields; validate before publishing. Provider-specific parsing belongs in `src/skippercast/pipeline/`; choosing an approved regional provider belongs in `pipeline/settings.py`. Add a new parser only when the source's actual contract differs. An alternate ERDDAP grid with the same semantics can be selected through `pipeline_sources` and the source registry's request specification. New model families need explicit unit, coverage and identity handling; do not label them as an existing model.

Source-page watches detect content changes. They do not interpret a changed legal rule automatically. The reviewed regulation fingerprint is updated only after reading and checking the change. A stale or changed critical source withholds the applicable season-open claim. The public app does not issue harbor entrance clearance or a catch probability.

Raw archives stay outside the public checkout unless redistribution is reviewed and a minimal public artifact is useful. Credentials, private catches, alert delivery state and machine paths never enter a public artifact. Public receipts may contain documentation URLs, timestamps, hashes, provider metadata and concise facts. An audit of documentation access cannot approve an underlying dataset.

```bash
PYTHONPATH=src python -m skippercast.platform needs --region cambria-san-simeon
PYTHONPATH=src python -m skippercast.platform candidate --file /tmp/source-candidate.json
PYTHONPATH=src python -m skippercast.platform.source_audit --output var/source-access.json
```

New regions need overlapping-source checks and independent validation, not an average of incompatible data. Preserve both candidates when they disagree, then explain which claim each supports. Keep the selected source version stable until its replacement passes the same checks.
