---
name: skippercast-recent-intel
description: Refresh and review recent public fishing discussions for a SkipperCast region using the pinned last30days research engine. Use for dated local report discovery, watchlist changes, source health, and promotion of verified evidence.
---

# Recent local fishing intelligence

Start with `catalog/recent-intel-watchlist.json`, `docs/recent-intel.md`, and the selected `regions/<id>/region.json`. The daily GitHub workflow runs `scripts/collect_recent_intel.py` with a pinned upstream last30days checkout. Its output is `recent-intel.json` on the data branch. Do not install an unpinned copy or put API keys, browser cookies, private catch logs, or vessel histories in the public workflow.

For a new region, add focused local queries and geographic terms, then test the collector with the pinned engine. Review `checks` and actual `source_status`: `no-results` is a complete empty search, while partial, timeout, auth, and schema errors are coverage gaps. Inspect representative results for irrelevant matches and stale uploads before treating a search as useful. Update the region's query set and selectors based on observed local names; never silently widen a region from a search term alone.

Each item is a **candidate link**. Before making a factual catch observation, open the original source and record the actual fishing date, species identification, first- or secondhand nature, effort if stated, place precision, method, and reuse rights. The posting date is not a fishing date. Preserve unknown fields as null. Reposts count as one trip. A port name does not locate a catch; a broad island report supports only an island-scale note. High engagement or high search relevance is not catch evidence.

Promote reviewed observations through the existing regional data contracts and validation path. Keep unreviewed candidates out of catch rates, species ranking, GPS points, drift guides, and comfort or safety scores. Public agency rules and MPA geometry stay on their own authoritative refresh path. Record the review decision and evidence URL, then compare repeat reports with the existing charter totals without double counting one trip.

The scheduled job is a discovery cadence, not a promise of a fresh catch report every day. If all searches fail, report the failure, retain the previous dated feed, and investigate the pinned engine and source responses. Update the pinned commit only after checking its JSON contract, permission preflight, representative local search, and collector tests.
