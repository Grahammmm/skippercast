# Coast pipeline adversarial tests (2026-10-22)

- **Scope:** `main` at `8a1c2c7`. New tests only; no source changed. Synthetic rasters only, no network, no real or private data. Outputs stay **NOT FOR NAVIGATION**.
- **Run:** `COAST_ADVERSARIAL=1 python -m pytest tests/adversarial_repro -p no:cacheprovider` (needs `[test,survey]`). Without the variable all 61 tests skip, so the normal suite stays green.
- **Result:** 61 tests, **8 fail on current main**, 53 pass. Findings already in `2026-10-22-skippercast-opus-audit.md` (branch `claude/audit-skippercast`: feet, sign and scale in `seafloor/raster.py`) are not repeated, except where a different reader has the same flaw.

## Names in the brief that do not exist on main

`coast_mosaic.py`, `coast_contours.py`, `coast_qa.py`, a rights-page generator, MVT output and terrain-RGB output are not in this repo. I tested the real equivalents:

| Brief | Tested instead |
| --- | --- |
| coast_mosaic | `src/skippercast/seafloor/grid.py` (`mosaic_reference`, `classify_reference`, `merge_reference`, `assign_reaches`) |
| coast_contours | `scripts/build_depth_contours.py`, `src/skippercast/platform/depth_contours.py` |
| coast_qa | `src/skippercast/coastal/vertical.py` (`to_depth`), `src/skippercast/seafloor/raster.py` |
| tile-edge continuity (MVT / terrain-RGB) | marching-squares seam test; `seafloor/habitat_tiles.windows` partition test |
| rights page | not tested (no generator found) |

## Failing tests (8)

| # | Test | Where | Impact (plain English) | Minimal fix | Confidence |
| --- | --- | --- | --- | --- | --- |
| 1 | `test_contour_builder.py::test_feet_grid_is_not_read_as_metres` | `scripts/build_depth_contours.py:84` | A grid in feet is read as metres. A 100 ft floor is drawn as 328 ft (3.28x wrong). | Read units and sign with `coastal.vertical`; refuse anything but metres. | High (code); low that a current source is affected |
| 2 | `::test_packed_scale_offset_is_applied` | `build_depth_contours.py:84` | Scale and offset are ignored. Stored -2000 at scale 0.01 (20 m) is drawn as 6561 ft. | Same as 1: apply `to_depth` or refuse non-unit scale/offset. | High (code); low (reach) |
| 3 | `::test_integer_grid_does_not_crash_the_reader` | `build_depth_contours.py:84` | An int16 grid with nodata dies with `TypeError` (`filled(np.nan)` on integers). Fails closed, confusing error. | Cast to float64 before `.filled(np.nan)`. | High |
| 4 | `::test_south_up_grid_matches_its_north_up_twin` | `build_depth_contours.py:48-58, 99-112` | A south-up grid dies with "negative dimensions are not allowed". Nothing checks orientation, unlike `seafloor/raster.py`. Fails closed. Rotated grids not tested. | Refuse `transform.e >= 0` or rotation with a clear message. | High |
| 5 | `::test_lattice_for_refuses_absurd_extent` | `build_depth_contours.py:76-77, 99-112` | Two small grids 2,000 km apart ask for a 125,004 x 125,004 block lattice (about 16 GB float64 plus 16 GB int8). Out of memory. No size cap. | Cap `width * height` (for example 250 M) and raise `ValueError`. | High |
| 6 | `::test_trace_treats_nan_as_invalid_like_none` | `src/skippercast/platform/depth_contours.py:137-139` | `trace` treats only `None` as a gap. A `NaN` corner gives `NaN` coordinates. The builder converts NaN to `None` first, so only direct callers are hit. | Treat any non-finite value as invalid. | High (code); low (reach) |
| 7 | `test_vertical_and_reference.py::test_to_depth_nodata_sentinel_survives_float32_rounding` | `src/skippercast/coastal/vertical.py:349` | `raw != nodata_value` is an exact compare. Float32 data with nodata -99999.9 (a float64 in the header) is not matched, so the sentinel becomes a valid 99,999.9 m depth. BAG callers pass `1e6`, which is exact, so no current caller is hit. | Compare in the raster's dtype, or mask from the dataset. | High (code); low (reach) |
| 8 | `::test_assign_reaches_nan_centre_is_unowned_not_a_crash` | `src/skippercast/seafloor/grid.py:54` | A `NaN` cell centre raises `GEOSException` and aborts the whole reach build. Centres come from finite indices today. | Filter non-finite x/y before locating; return `-1` for them. | High (code); low (reach) |

Severity: 1 and 2 are the only ones that could put wrong numbers on a public line. They share the root cause of the earlier audit's finding 1, now seen in a third reader (the contour builder). 3 to 8 fail closed or need unusual inputs.

## Passing tests (guards worth keeping)

- **Overlap and seams:** first listed source wins each cell, in either order. Corner-touching sources share no block. Different cell size, CRS or phase is refused.
- **Edges and values:** one nodata cell voids only its own block. NaN and +/-inf are never water. 0 m is land. Single-pixel and 8 x 4096 rasters do not crash.
- **Windows:** `bounds_window` handles a single pixel, a zone 10/11 boundary, disjoint and corner-touching requests, NaN and inf bounds, south-up and rotated rasters. The `read_native` cap is exact at 1,048,576 pixels. Bad uncertainty and flags do not leak.
- **Marching squares:** levels exactly on cell values give finite lines. Two tiles with a shared column reproduce the whole grid's segments. Output is deterministic.
- **Reference mosaic:** the finer source wins even when older, in either order. A tile wholly outside is skipped, an all-NaN tile stays unknown, and single-pixel and zone 11 tiles land correctly.
- **`to_depth`:** NaN, inf and masked cells never become 0. Feet, scale and offset compose correctly. Non-finite scale or offset is refused. Overflow is masked.
- **Tile windows:** `habitat_tiles.windows` covers every cell exactly once for `(1,1)`, `(1,100000)`, `(100000,1)`, `(0,7)` and a halo larger than the grid.
- **Idempotence:** `read_native`, block merge, `to_depth` and the reference mosaic give byte-identical output on a second run.

## Not covered

- **Antimeridian:** `platform.contracts.bbox` rejects `west >= east` by design, so no region can cross 180. I only checked that `to_lonlat` on UTM 60N does not wrap (passes). The mosaic is hard-coded to EPSG:3310.
- **Whole `ingest()`:** needs a hash-pinned catalog row, so COG idempotence end to end was not run.
- **MVT and terrain-RGB:** no such code exists. Add tests when it lands.
- **Real data:** none used or reachable.
