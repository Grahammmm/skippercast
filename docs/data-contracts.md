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
