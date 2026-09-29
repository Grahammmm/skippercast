# Research tooling (not product)

Everything under `research/` is dated audit and research tooling: source audits,
screens, triage queues, discovery crawls, reviews and one-off dataset builders.
It records *how* evidence was checked. It is not part of the app, the Worker or
the scheduled product feeds.

- **Not product.** Nothing in `src/`, `server/`, `dist/` or `scripts/` imports or
  runs anything here. `tests/test_research_boundary.py` enforces that, and also
  fails if a new `audit_*`/`screen_*`/`triage_*`/… script is added to `scripts/`.
- **Dated.** Each script pins the sources, hashes and review dates it was written
  against. A script that no longer matches today's sources is a finding to review,
  not a product outage.
- **Kept runnable.** History was preserved with `git mv`. Scripts run from the
  repository root exactly as before, with the new path:

  ```bash
  PYTHONPATH=src:. python research/scripts/audit_nbs_modeling_tile.py --help
  PYTHONPATH=src:. python -m research.scripts.audit_point_conception_4m_access
  ```

  Most need the survey packages (`pip install -r requirements-survey.txt`).

## Layout

| Path | What it holds |
| --- | --- |
| `scripts/` | Audit, screen, triage, review, discovery, inspect, summarize, queue, compile, reconcile and measure scripts, plus one-off builders for research datasets and manually refreshed app data (for example `build_habitat_regions.py`, `export_web_targets.mjs`). Maintained by Codex. |
| `lib/` | Helpers shared by several research scripts, so they need not import an unrelated audit for them (`lib/paths.py`: repository `ROOT`). |

Research scripts may import product code (`skippercast.*`, and product tools in
`scripts/` such as `scripts.discover_noaa_surveys`); the reverse is not allowed.
Cross-imports between research scripts use `research.scripts.<name>`; when a
helper is shared by several of them, move it into `research/lib/`.

## Where things stay in `scripts/`

`scripts/` keeps only tools that a product workflow, the build, the deploy or a
product module runs or imports: the Worker build and fingerprinting, deploy and
smoke tests, feed publishers, the live and daily collectors whose outputs the app
loads, and the repository checks CI runs.
