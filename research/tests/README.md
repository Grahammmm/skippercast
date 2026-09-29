# Claims pins and research tests

Every module here pins a statement the app, the docs or a receipt makes to the
committed evidence behind it (`research/receipts/`, research outputs under
`dist/data/`, `research/catalog/`), or tests the research script that produced
that evidence. pytest marks everything in this folder `claims`; modules under
`gis/` also need the survey stack and are marked `gis`. See
[docs/engineering/testing.md](../../docs/engineering/testing.md).

- **Run:** `python -m pytest -m claims` (all), `python -m pytest research/tests --ignore=research/tests/gis`
  (without GIS packages, as CI's `check` job does via `-m "not gis"`), or one module with
  `python -m unittest research.tests.gis.test_<name>` as the research workflows do.
- **Paths:** import `ROOT` from `research.lib.paths` and receipts through
  `research.lib.receipts.RECEIPTS`/`locate()`; never from `__file__` or `sys.path`.
- **Changing a pin** means the evidence changed: update the receipt and the pin in
  the same PR and explain it under **Claims and data**.
- **Private caches.** A test that re-derives a receipt from gitignored originals
  (`var/`, original survey archives) skips when they are absent; its exact reason
  must be allow-listed in `scripts/pytest_report.py`, and a committed-output twin
  must still run in CI.
