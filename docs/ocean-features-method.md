# Colour edges, model eddies and sea-surface height: method note

This note describes the merged pipeline methods for [roadmap 05 (R1–R3)](research/specs/05-chlorophyll-edges-eddies-ssh/spec.md), not the planned Chart wiring. Publication status refers to the scheduled habitat path in [`refresh_regions.py`](../scripts/refresh_regions.py) and [`habitat_dynamics.run`](../src/skippercast/pipeline/habitat_dynamics.py). These are physical conditions, not estimates of catch odds.

## Colour edges (observed chlorophyll)

**Scheduled refresh: not published.** It collects `chlorophyll-observation` and runs a separate publisher for SST fronts, but does not run the `chl-edges` builder.

[`chl_edges.py`](../src/skippercast/pipeline/chl_edges.py) detects ridges in one observed chlorophyll grid. It takes `log10` of positive chlorophyll in mg/m³. Along each grid axis it takes the absolute difference between the two immediate neighbours in log space and divides by two cells. An axis with a missing neighbour has no support. The larger score (longitude wins ties) must meet `MIN_LOG10_CHANGE_PER_CELL = 0.3` log10 units per cell, inclusive with a round-off allowance.

On that axis a ridge cell must score strictly higher than the preceding cell and at least as high as the following cell. This keeps the first cell of a two-cell step ridge. Adjacent ridge cells form lines; diagonal links require both intervening orthogonal cells to be observed. No cloud or land gap is filled. `MIN_EDGE_CELLS = 5` counts cells on the line, not kilometres. Each line carries its observation time and mean ridge score. Its band half-width is the mean of half a native cell measured across the ridge (longitude spacing scaled by the cosine of latitude). This is positional uncertainty from grid spacing, not a measurement error or confidence interval.

[`chl_edges_feed.py`](../src/skippercast/pipeline/chl_edges_feed.py) takes `max_age_hours` from the caller: it must be positive and finite, and the builder has no default. It counts refused tile frames under `refused_frames`: `missing_time` (absent or null), `unparseable_time`, `future` (later than `now`) and `stale` (older than the limit; exactly at the limit is usable). The builder selects the newest usable timestamp and pools tiles from that observation only; their resolutions must agree.

| `withheld` reason | When it applies |
| --- | --- |
| `no-usable-frame` | No tile frame passes the time rules. |
| `too-little-clear-water` | The matching regional metadata gives `valid_cells / total_cells`, rounded to three decimals, below `MIN_OBSERVED_FRACTION = 0.2`. The floor is provisional pending tuning on real regional fixtures. |

The coverage fraction comes from regional metadata, not just the cells present in the supplied tiles. If it cannot be established because matching metadata or a positive cell total is absent, it is null and the floor does not withhold the observation. A usable observation with no qualifying ridge has an empty edge list and no withhold reason. The builder does not fall back to an older observation when the newest is withheld.

## Eddies (WCOFS model output, not observed)

**Scheduled refresh: not published.** `habitat_dynamics.run` can publish `wcofs-surface-forecast`, but it does not derive or publish `wcofs-eddies`.

[`eddies.py`](../src/skippercast/pipeline/eddies.py) calculates Okubo–Weiss on each regular surface-current grid separately. For eastward velocity `u` and northward velocity `v`, it uses centred differences over local east and north distances (longitude spacing scaled by the cosine of latitude). It computes normal strain `sn = u_x − v_y`, shear strain `ss = v_x + u_y` and vorticity `ω = v_x − u_y`, then `W = sn² + ss² − ω²`. The centre and all four stencil neighbours must have finite velocities; no derivative crosses a gap.

Candidate cells satisfy `W < −0.2 × σ_W` (`_THRESHOLD_SIGMAS = 0.2`), where `σ_W` is the population standard deviation of all valid W values in that frame's subset. Cores are connected by shared cell sides and must span at least `_MIN_CORE_SPAN = 4` cells in both axes. Cores that touch the outermost *computable* row or column are dropped: the stencil cannot confirm closure there. Exposed cell edges must trace a single closed `[lon, lat]` ring; holes and corner pinches are refused. Sense comes from vorticity at the minimum W in the core (`ccw` for positive, `cw` otherwise). Diameter in kilometres is that of a circle with the same summed cell area, not the widest distance across the outline.

[`eddies_tile.py`](../src/skippercast/pipeline/eddies_tile.py) encodes one frame per tile, with `frame_time` and a `features` list. It writes an aware frame time as UTC to seconds with `Z`; the reader requires a parseable ISO datetime ending in `Z` or `+00:00`. Each feature has exactly `outline`, `sense`, `diameter_km` and `ow_min`. The ring must have at least five positions including the repeated first point, with finite longitude in [−180, 180] and latitude in [−90, 90]. Sense is `cw` or `ccw`; diameter is finite and positive and `ow_min` is finite and negative. Encoding rounds coordinates to five decimal places, diameter to two, and `ow_min` to four significant digits; invalid rounded diameter or W is rejected. The encoder sorts by descending rounded diameter, then outline. The tile codec sets no feature-count, byte-size or forecast-window cap.

## Sea-surface height (WCOFS model output, not altimetry)

**Scheduled refresh: not published.** `habitat_dynamics.run` does not read `zeta` or include `wcofs-ssh` in `habitat-dynamics.json`.

[`wcofs_zeta.py`](../src/skippercast/pipeline/wcofs_zeta.py) requires one matching DDS declaration for `zeta[time = 1][ny][nx]`, with the two sizes matching the grid dimensions read independently of the `zeta` declaration. The DAS `zeta` block must declare metre units (`m`, `meter` or `meters`). A supplied `long_name` must describe the `free-surface` (case-insensitive substring check), and a supplied `_FillValue` must parse as a number. The subset helper addresses `zeta[0]` with ordered, nonnegative integer bounds, inclusive at stride one. The row helper requires positive dimensions and exactly `ny × nx` values in row-major order.

[`wcofs_ssh.py`](../src/skippercast/pipeline/wcofs_ssh.py) checks metre units, grid shape against the axes and finite coordinates. It omits missing, non-numeric, boolean, non-finite and fill values. A remaining value with absolute magnitude **greater than 20 m** rejects the frame before mean removal; a frame with no valid cells is also refused. Each valid cell's `ssh_cm` is its height minus the unweighted mean of all valid regional cells in that frame, multiplied by 100 and rounded to one decimal place. This is relative to the regional frame mean, not absolute elevation. There is no spatial or temporal gap filling.

[`wcofs_ssh_layer.py`](../src/skippercast/pipeline/wcofs_ssh_layer.py) assembles `wcofs-ssh` from **1–169** preloaded frames. It requires a timezone-aware issue time, two resolution steps each in `(0, 0.25]` degrees, and unique integer epoch-second frame times. It sorts by frame time; the first and last times define the validity bounds. The layer metadata describes an approximately 4 km WCOFS model with three-hour output and at most a 72-hour forecast; the assembler itself does not enforce the cadence or horizon.
