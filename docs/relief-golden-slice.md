# Relief golden slice (SC-MAP-GOLDEN-1)

Run this offline check after a relief stage merges. A failed or unwired stage
makes the run RED. A green synthetic run checks the pipeline, not survey
accuracy, browser rendering, publication, or production capacity.

```sh
~/agent-work/bin/memcap -- python3 scripts/relief/golden_slice.py --work /path/to/fresh-work
```

- **Default: `--slice synthetic`.** On the fixed Morro Bay box (W -120.872,
  S 35.368, E -120.850, N 35.380; about 2.7 km²), rasterio generates six
  seeded 128×128 rasters in `<work>/fixture/`: four projected NOAA-like 1 m
  grids, one geographic NCMP-like grid at about 1 m, and one projected BlueTopo-like
  4 m, three-band grid. No held pixels are copied or read, including the CSMP
  ZIP inventory; the default does not inspect the backup mount. No binaries are committed.
- **Heavy mode: `--slice morro-bay` is unavailable by design.** Before any
  stage or held-data access, `/proc/self/cgroup` must name a `mapjob-` systemd
  service and `pgrep -f` must find no competing `coast_mosaic.py`,
  `build_bathy_tiles.py`, or `run_bounded.py` process. Missing or failed admission
  is a non-zero exit, without waiting or retrying. The installed `localmapq`
  has no golden-slice dispatch, so there is no supported launch path. Only
  the scheduler owner can add one. The process check is a snapshot, not a
  host-wide lock: a launcher bypassing `localmapq` could start after the check.
  The original heavy load5 and disk floors still apply if a dispatch is added.
- **Stages:** inventory → normalize → select → mosaic → tiles → contours →
  release → QA → preview. `REAL` runs repository code; `THIN` is a stand-in.
  Preview is `SKIPPED` only while `src/skippercast/relief/preview.py` is absent.
  Any merged stage module without a `REAL_ADAPTERS` entry produces `UNWIRED`
  and RED. Its wiring card should supply the real adapter and update the stage test.
- **Rights and support are separate.** The selector reads the exact DEM
  catalogue rows. The local public scope requires an approved row, commercial
  use and public display allowed, and `publication_allowed: true`; it does
  not publish anything. Only two synthetic grids carry positive per-cell
  support evidence. The tiler and QA use their masked native copies for
  detail; valid but uncertified cells (including interpolated geographic
  cells) remain estimated background. The legacy tiler can still paint
  background in a detail tile. QA counts this as outside measured support, not
  as measured coverage. Held inputs have no admitted per-cell evidence here.
- **Receipts:** `<work>/stages/<stage>.json` records input generations, output
  hashes, wall time and peak RSS. An unchanged run reuses valid receipts.
  Default work is `$HOME/agent-work/golden-slice/w1/<slice>`; use separate work
  directories for the two modes. Stages run sequentially with `nice 19`, idle
  I/O priority where available, and one compute thread. Synthetic work needs
  1 GiB free on its own work volume. Use a GIS interpreter with numpy, rasterio,
  and the repository survey dependencies; `GOLDEN_VENV_PY` can select a fallback
  interpreter if the invoking Python lacks numpy/rasterio.
- **Known gaps:** `XFAIL` is an observed mismatch, `FLIPPED` a pass, and
  `UNKNOWN` inconclusive. The equal-resolution probe compares the actual mosaic
  contributor with the actual tiler winner using identical synthetic source IDs.
  A synthetic `FLIPPED` is evidence for that case, not automatic promotion to a
  mandatory check. Synthetic runtime does not forecast production runtime.

## Candidate text for the mapping skill (not installed; for the policy owner)

> **Required check after every relief stage merge.** From merged `main`, run
> `~/agent-work/bin/memcap -- python3 scripts/relief/golden_slice.py`. Paste the
> stage table, must-pass checks and known gaps into the merge card. It must exit
> zero. If the just-merged stage is unwired, add its real adapter in the stage
> card. Review any flipped gap before promoting it. Do not use synthetic timing
> or green status as approval to start a statewide run.
