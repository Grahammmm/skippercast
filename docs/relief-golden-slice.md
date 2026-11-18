# Relief golden slice (SC-MAP-GOLDEN-1)

One command proves the whole relief pipeline on a small fixed slice before anything runs at statewide scale.
Run it **after every stage merge**; a red or unwired run blocks the next stage card.

```
python3 scripts/relief/golden_slice.py [--work DIR] [--max-wait-min N] [--forecast-km2 KM2]
```

- **Slice.** Box W -120.872, S 35.368, E -120.850, N 35.380 (about 2.7 km2 around Morro Rock). Six held rasters
  are read in place and read-only: NOAA MRR22_089/090/093/094 (1 m), NCMP 2015 10SFE9416 (1 m, geographic) and
  BlueTopo BH4585BW (4 m), all under `/mnt/agentorange-backup/seafloor-data`. Nothing is committed from there.
- **Stages.** inventory, normalize, select, mosaic, tiles, contours, release, qa. The table prints each stage as
  `REAL` (repo code) or `THIN` (stand-in kept in `golden_slice.py`). Today mosaic, tiles and contours are real
  (`coast_mosaic.py`, `build_bathy_tiles.py`, `build_depth_contours.py` plus `coast_contours.py`); the rest are thin.
  Preview needs a browser and is reported SKIPPED.
- **A merged stage must be wired.** If `src/skippercast/relief/<stage>.py` exists and the stage is not in
  `REAL_ADAPTERS`, the stage shows `UNWIRED` and the run is RED. Add an adapter that calls the real stage, drop
  the thin function, rerun.
- **Receipts and rerun.** `<work>/stages/<stage>.json` (schema `sc-golden-receipt/1`: generation, upstream
  generations, wall seconds, peak RSS, output sha256s). A rerun with unchanged inputs and code reports every stage
  `DONE (no work)`; a changed code or input hash reruns that stage and everything downstream. Two failed attempts
  on one generation hold the stage.
- **Known gaps.** The E2E-PROOF-1 findings are named checks: `XFAIL` is expected and printed every run; a check
  that starts to pass prints `FLIPPED`, the signal that its card landed (move it into the must-pass list). The
  exit code ignores XFAIL and FLIPPED, never hides them, and is non-zero for any failed stage or must-pass check.
- **Runtime forecast.** The last table prints seconds per km2 per stage; `--forecast-km2` multiplies it. It is a
  floor (fixed overhead is included, overlap and memory growth are not).
- **Load rules.** Each stage runs at `nice 19` and `ionice idle`, one at a time, and waits (default 10 minutes)
  while load5 is at or above 24 or free disk is under the floors (`/` 250 GB, backup 400 GB). Nothing is
  downloaded, uploaded or published; `/mnt/privatevault` is refused. The default work dir is
  `$HOME/agent-work/golden-slice/w1`.
- **Interpreter.** Needs numpy and rasterio; it re-executes under the shared skippercast venv python
  (`$GOLDEN_VENV_PY`, default `~/repos/skippercast/.venv/bin/python`) when the current interpreter lacks them.

## Candidate text for the mapping skill (not installed; for the policy owner)

> **Required check after every relief stage merge.** From the merged `main`, run
> `python3 scripts/relief/golden_slice.py` and paste its stage table, the must-pass checks and the known-gap
> list into the merge card. It must exit 0. Read the REAL/THIN column: if a stage you just merged still shows
> THIN or UNWIRED, wire it into the golden slice in the same card. A known gap that prints FLIPPED belongs to a
> card that landed: promote it to a must-pass check. Never start a statewide run while the golden slice is red.
> The runtime rates feed the compute forecast; do not guess statewide time from anything else.
