---
name: skippercast-add-region
description: Create or extend a SkipperCast regional data package and verify that shared maps, forecasts, regulations, species evidence and bottom views work with geographically appropriate sources. Use for rollout to a new harbor or coastline.
---

Choose an available Python 3.11+ interpreter for the commands below (`python` is shorthand). If system Python is unavailable, use the runtime configured for the workspace. Keep that local executable path out of public region data.

Read `docs/regions.md` and `catalog/data-needs.json` in the user's SkipperCast repository. Use the current region as a structural example, not as the new region's data. Preserve the user's chosen extent, target species, depth, boat and departure harbor unless they request a change.

Read `docs/region-pipeline.md` for the complete rollout and model-use policy. Routine collection and validation use deterministic code; a small/fast assistant may prepare candidates and notes, while ambiguous legal, rights or scientific changes require explicit review. Do not make routine refreshes depend on an LLM.

For California, begin with `docs/statewide-buildout.md` and the matching entry in `catalog/coastal-sectors.json`. The dated NOAA survey-discovery feed lists intersecting BAG survey leads, not verified bottom coverage. Inspect exact native BAG cells and the original report before considering any lead for a target. Keep the sector status as discovery even if one partial package has point candidates within it.

Create `regions/<id>/region.json` with explicit WGS84 bounds, timezone, jurisdiction, forecast sample points, marine zones, observation/tide stations, boat preferences, asset paths and ordered source bindings. Region identifiers are stable; model grids, source IDs and habitat IDs retain their own namespaces.

Inspect primary sources for this geography. Populate the coverage ledger by need; a binding without regional coverage is a gap. A new region starts in preview until its fishing geometries pass the required depth, rights and closure checks. Preview can expose researched context and regional conditions while explaining unavailable features; never populate empty maps with invented fishing coordinates.

For local rules, follow `docs/regulations.md`. Bind the exact jurisdiction, authority hosts and watched URLs; review every active species and area-access dependency using `skippercast.pipeline.regulation_review collect` and an explicit hash-bound decision. A shared season does not establish identical gear rules, MPAs, health restrictions or military access. Keep pending proposals separate from effective law. Confirm the first per-region `regulations-health.json`; live access clearance is separate from unchanged rule text.

For every species offered in the regional selector, verify its ecology scope and reviewed primary fishing strategy. Update `catalog/primary-strategies.json` where a new target is introduced, run `python scripts/build_primary_strategies.py`, and inspect `dist/regions/<id>/strategies.json`. A region cannot inherit a different coast's tactic as a local claim without evidence.

Run `PYTHONPATH=src python -m skippercast.platform validate --region <id>` and the region/package build commands in `docs/regions.md`. Check native units/datums, geometry exclusions, complete datasets, timestamps, source identity, publication size and independent forecast models. Verify one actual region-specific observation and a failure case. Confirm that changing region updates map extent, labels, sources, forecasts, tides, regulations, exports and evidence without leaking the old region's selection or cached feed.

Check the mobile map and a selected target/area. Show one bottom view only when supporting data exist; source gaps must be visible. Avoid new sidebar lists or dense landing content. Keep code changes in shared components and data differences in the regional package.

Use the existing publishing and update workflows within the task's authorization. Document rollout readiness, withheld capabilities, data refresh ownership and rollback. Do not call a region fully covered because the shared software can load it.

For ocean intelligence and private alerts, follow `docs/regional-intelligence.md` and `docs/production-operations.md`. Bind each intelligence role to an approved provider; check actual HFR/current coverage and horizon. Add an adapter when the provider differs. Verify station coordinates, sensor height, ecology scope and the deployment’s immutable GitHub identity policy. Preview conditions do not qualify new fishing targets.
