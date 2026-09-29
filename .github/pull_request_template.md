## What changed

<!-- One or two sentences on the resulting behavior. -->

## Why

<!-- The problem or goal. Link the issue if there is one. -->

## How it was checked

- [ ] Full test suite (`SKIPPERCAST_REQUIRE_GIS=1 python -m pytest`, Python 3.13 + survey stack)
- [ ] `python -m pytest -m "not gis"` (no GIS packages)
- [ ] Generated files rebuilt from source, not hand-edited (`platform.build`, `build_search_plans.py`, `pnpm build`)
- [ ] `check_repository.py` and `check_web.py`
- [ ] Viewed in a browser (for app changes)

## Claims and data

<!-- Did any user-facing claim change (depth qualification, "ready" status, datum, catch or hotspot language)? What evidence supports it? New data sources: license and commercial-use status. -->

## For the reviewer

<!-- Anything the reviewer or owner must decide. Author: codex or claude. -->
