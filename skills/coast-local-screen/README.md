# coast-local-screen (tier 1) scripts

COAST-LOCALSCREEN (t_6438ac24). The tier-1 first pass over EVERY window of one finished window-set
plan, on the local GPU model, before any cloud model looks at it. Design: COAST skills design rev 3,
sections 3.3 and 5.4. The SKILL.md that wraps these scripts is the B2 card's (t_de9b2254); this file is
the operating reference until then.

It flags; it never accepts. `flagged-windows.json` carries `review_required: true`, `accepted: false`,
and `summary.must_examine`: every flagged or held `window_key`. The tier-3 (V-) review must examine all
of those in addition to its random sample.

## Inputs (read-only)

- `--plan-dir $COAST_ROOT/<seg>/plans/<plan-id>` (absolute). The queue root is two levels up.
- The latest PC-9 run summary `runs/run-NN.json` (`coast-run-summary-v1`, written by
  `python -m skippercast.coastal.coordinator.bridge_run run`), or `--run-summary <absolute path>`.
  The design-3.2 fixture shape (`run-summary-NN.json` with `terrain_ref`/`support_ref`/`cells_ref`) is
  read through a small adapter.
- Everything the summary pins: admission, bridge and enqueue receipts, catalog, and per window and stage
  the input manifest, `result.json` and products (`terrain.tif`, `support.tif` = the map run's `mask`
  output, `cells.json`, `run.json`, the qualification handoff). Every ref is re-hashed (H1).

Real field names used (PC-9 `bridge_run._lineage`): `windows[].window_key` (`<source_id>#<grid_sha256>#<idx>`),
`state` (`map_done | held | failed_terminal | ... | unfinished`), `stages.qualify.support.{valid_cells,
mask_sha256}`, `stages.map.{native_valid_count, depth_m}` (cells.json `{count,min,max,mean,p80}`,
`'unknown'` -> null), `stages.map.products.{terrain,mask,cells}`; admission `windows[].{window_dir,
grid_sha256, idx, pixel_window}`.

## Commands

Run from the checkout with its survey venv (numpy + rasterio are needed for `stats`):

```
export SC_REPO=$HOME/skippercast-data/2026-10-07-pge-south/repo SC_PY=$SC_REPO/.venv/bin/python
export COAST_ROOT=$HOME/skippercast-data/coast-campaign
export COAST_AUTHOR_PROFILE=local-worker COAST_CARD_ID=<card> COAST_CODE_COMMIT=$(git -C $SC_REPO rev-parse HEAD) COAST_SKILL_COMMIT=$(git -C $SC_REPO rev-parse HEAD)
P=$COAST_ROOT/<seg>/plans/<plan-id>
$SC_PY skills/coast-local-screen/scripts/local_screen.py stats    --plan-dir $P
$SC_PY skills/coast-local-screen/scripts/local_screen.py text     --plan-dir $P --endpoint http://127.0.0.1:8003/v1 --model qwen3.8:27b-thinkingcap-q6 --slots 1
$SC_PY skills/coast-local-screen/scripts/local_screen.py vision   --plan-dir $P --endpoint http://127.0.0.1:8003/v1 --model qwen3.8:27b-thinkingcap-q6 --slots 1
$SC_PY skills/coast-local-screen/scripts/local_screen.py assemble --plan-dir $P
# or all four in order:
$SC_PY skills/coast-local-screen/scripts/local_screen.py all      --plan-dir $P --slots 1
```

Outputs, each written once (O_EXCL, canonical JSON), under `$P/review/tier1/` (or `--out <absolute dir
under $P/review/>` for a re-screen; an existing file is never overwritten):

- `stats.json` (`coast-tier1-stats-v1`): deterministic results, thresholds in force, plan-level ref checks;
- `windows/<window_dir>/stats.json` and `hillshade.png` (256 x 256);
- `text.json`, `vision.json` (`coast-tier1-text-v1` / `-vision-v1`): per-window verdicts, raw replies,
  tokens, latency, endpoint, model alias and tag, prompt sha256, slots;
- `flagged-windows.json` (`coast-tier1-screen-v1`): the tier-1 result; it pins the three files above.

Post `flagged-windows.json`'s sha256 (printed by `assemble`) in the handoff; it does not contain its own
hash (H2). Handoff line: `tier1 <plan-id>: N windows, M flag, K held, H hash mismatches, U derived unavailable`.

## What it checks, in fixed order

1. Deterministic (no model can overrule): every ref re-hashes (`HASH_MISMATCH`; a plan-level receipt
   mismatch flags every window), pipeline hold (`HOLD` -> tier1 `held`, holds copied, not screened),
   other unmapped states (`NOT_MAPPED`), producer fields copied verbatim, derived statistics from the
   verified terrain + support bytes (valid/nodata/edge-valid fractions, depth median/p99, slope p99 using
   cells.json `native_resolution_m`), `COUNT_MISMATCH` (producer vs raster valid cells),
   `VALID_FRACTION_LOW` (< 0.5), `EDGE_VALID_LOW` (< 0.5), `SLOPE_P99_HIGH` (> 60 deg), `DEPTH_RANGE_OUT`
   (only when the catalog row states `metadata.depth_range_m`; otherwise `depth_range_plausible: null`,
   `catalog_range_unavailable`), `NEIGHBOUR_STEP` (|median shared-edge step| > 2 m against an adjacent
   mapped window of the same grid; adjacency from `pixel_window` edges, never across sources or rows).
   A null statistic never passes: `DERIVED_UNAVAILABLE`. Thresholds: built-in design 5.4 defaults, or
   `--thresholds skills/coast-campaign-shared/config/tier2-thresholds.json` once B1a lands.
2. Text model on each mapped window's stats line (`prompts/text.md`).
3. Vision model on each mapped window's hillshade (`prompts/vision.md`): azimuth 315, altitude 45,
   true cell size, linear depth stretch over the window's own range, nodata transparent, deterministic bytes.

A window passes only when all three pass. Any model reply whose first word is not `pass` is a flag; the
raw reply is kept. Endpoint down (after 2 retries 60 s apart) -> `ENDPOINT_UNAVAILABLE` in
`summary.flags`, no further calls, every mapped window flagged. A missing thumbnail is a vision flag.

## Local-only

The endpoint must be `http://` on 127.0.0.1 / localhost / ::1 (refused otherwise, before any call);
proxies are ignored. No other network access, no cloud model, no writes outside `--out`, no job dirs
touched, no stage re-run.

## Bake-off fixtures

`fixture-eval --text-fixtures ~/agent-work/bakeoff/testset/build/screen_text.json --vision-fixtures
~/agent-work/bakeoff/testset/build/screen_vision.json --out <absolute new file>` runs the same prompts
over the bake-off screening fixtures (their receipt names are adapted to the stats line) and reports
tp/fp/fn/tn, recall, precision, F2 and p95 latency per suite.

## Tests

`PYTHONPATH=src python -m pytest tests/unit/test_coast_local_screen.py` (raster tests are marked `gis`;
one of them screens a real PC-9 run summary produced by the real acquire/qualify/map producers).
