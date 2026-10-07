# Research tooling (not product)

Everything under `research/` is dated audit and research tooling: source audits,
screens, triage queues, discovery crawls, reviews and one-off dataset builders.
It records *how* evidence was checked. It is not part of the app, the Worker or
the scheduled product feeds.

- **Not product.** Nothing in `src/`, `server/`, `dist/` or `scripts/` imports or
  runs anything here. `tests/contract/test_research_boundary.py` enforces that, and also
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
| `lib/` | Helpers shared by several research scripts, so they need not import an unrelated audit for them (`lib/paths.py`: repository `ROOT`; `lib/receipts.py`: `RECEIPTS`, `locate()`). |
| `catalog/` | Dated research pins and review bindings (source screens, triage profiles, sample tiles, hazard scopes) that only research scripts and tests read. Product catalogs stay in the top-level `catalog/`; `platform.build` never reads this folder. |
| `receipts/` | Audit receipts (JSON/GeoJSON) that used to ship in `dist/data/`. `receipts/manifest.json` pins each file's sha256; regenerate it with `python -m research.lib.receipts` after a reviewed change. |
| `tests/` | Claims pins and research-script tests, run by pytest in CI with the product suite (marker `claims`; `tests/gis/` also `gis`). See [tests/README.md](tests/README.md). |

Research scripts may import product code (`skippercast.*`, and product tools in
`scripts/` such as `scripts.discover_noaa_surveys`); the reverse is not allowed.
Cross-imports between research scripts use `research.scripts.<name>`; when a
helper is shared by several of them, move it into `research/lib/`.

## Private native bedrock window proposals

`research/scripts/plan_bedrock_windows.py` creates an offline, private planning
JSON from a locally qualified reach and classified-bedrock policy. It uses the
reviewed source-context checks, cached normalized depth, and already-extracted
ArcGrid terrain support only (`fetch=False`),
then reports one-pixel-inset native windows, valid nominal 25–300 ft depth
counts, resource use, and held-window reasons. It uses same-region prior
classified and held geometry in whole-window overlap exclusions, with source
path and hash receipts in the result. Each neighboring reach is marked verified,
incomplete, or unprocessed. Missing outputs, missing receipts, or absent private
bedrock-quarantine audits make the foreign-occupancy assessment incomplete;
those states never mean empty occupancy. A nonempty quarantine is not imported
without its native geometry and authentication context. Resolve these flags
before any separate activation.

The command requires an explicit output path and will not overwrite an existing
file:

```bash
PYTHONPATH=src:. python research/scripts/plan_bedrock_windows.py \
  --root /local/qualified/workroot --reach REACH_ID \
  --policy-id REVIEWED_POLICY_ID --output /private/proposal.json
```

One pinned, authenticated legacy San Simeon physical/native identity has no
per-component quarantine branch. The proposer recognizes that reviewed case
only when its implementation, source identity, current receipt and all four
current outputs match. A screen-only refresh can retain this physical identity;
the assessment explicitly does not certify current legality. Missing or changed
physical identity, native geometry, code, or audited/mixed profiles remain
incomplete. No empty quarantine audit is created.

The configured target-policy windows are recorded as read-only context, not
foreign occupancy, to prevent the policy from excluding itself. This does not
allow the proposal to replace or expand that policy. Before any separate
activation, compare prior output IDs and geometries and preserve them. The
result is a research proposal only: the script does not qualify a source, edit
policies, source catalogs, caches, reaches, screens or publication outputs,
and it makes no habitat, fish-presence, depth-datum, measurement or ranking
claim.

## Workflows

Research runs only in `.github/workflows/research-*.yml`, each with a read-only
token and results uploaded as workflow artifacts:

- `research-daily.yml`: NOAA BAG head triage, bounded ENC danger reviews and USGS
  map-block/DOI discovery and XML audits, after each `daily-data.yml` run
  (formerly steps inside it); incremental state lives in the Actions cache.
- `research-substrate.yml`, `research-fish-survey.yml` (formerly `monthly-*.yml`):
  the monthly source re-verifications, on their original schedules.

`tests/contract/test_research_boundary.py` fails if a product workflow references
`research/` or a research workflow can publish.

## Receipts and their historical paths

Receipts, catalog bindings (`catalog/surveys.json` evidence pointers, review
input lists) and ledgers name each other as `dist/data/<name>`. Those strings are
hashed evidence, so they were not rewritten when the files moved. Code that
follows such a reference resolves it with `research.lib.receipts.locate(path)`,
which returns `research/receipts/<name>` for a moved receipt and the path itself
otherwise. Tests read receipts through the single `RECEIPTS` constant. New
receipts are written to `research/receipts/` directly.

`dist/data/` keeps only what the product uses: files the app or Worker loads,
files named as provenance by a file the app loads (so published links resolve),
and the few platform-build and seafloor inputs/outputs read by `src/`.

## Where things stay in `scripts/`

`scripts/` keeps only tools that a product workflow, the build, the deploy or a
product module runs or imports: the Worker build and fingerprinting, deploy and
smoke tests, feed publishers, the live and daily collectors whose outputs the app
loads, and the repository checks CI runs.
