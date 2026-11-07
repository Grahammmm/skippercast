# MAPLAYER-WIND-1 — private real-data particle preview

Open `/research/scripts/map_style/wind-test.html` using the existing loopback
`serve_range.py`. This is a separate MAPSTYLE test page, **not the live app map**.
Raw GRIB, decoded JSON and source receipts live only in ignored
`var/maplayer-wind-1/`; the retained base is in `var/seafloor/tiles/`.
No build entry, public asset, live feed, scheduler or canonical store changes.
The existing MAPSTYLE public-copy guard remains intact.

## Source and captured evidence

Source identity follows `catalog/layer-inventory.json` → `wind-gfs-ecmwf` →
`noaa-gfs` (GFS only, no ECMWF substitution). Direct NOAA NOMADS 0.25° UGRD/VGRD
at **10 m above ground**, forecast lead 6 h, run **2026-11-07 12:00 UTC**,
valid **2026-11-07 18:00 UTC**. Retrieved **2026-11-07 20:22:39 UTC**.
This is a real numerical model forecast, not station observations.

The exact URL, raw SHA256, retrieval/run/valid times and base checksum are in
the task's private `reports/maplayer-wind-1/source-receipt.json` under agent-work.
The current crop spans longitude -123..-119 and latitude 34..37: 17 × 13 nodes,
0.25° spacing (~23 km east–west and 28 km north–south at Morro Bay).
Two browser screenshots at zooms 9.5 and 11 and browser-acceptance.json are in
that same private report directory. Data are not checked into git.

## Refresh / reproduce (explicit local action only)

With the candidate-bound runtime and installed dependencies already staged:

```
.venv/bin/python research/scripts/map_style/fetch_wind.py --run 2026110712 --hour 6
.venv/bin/python research/scripts/map_style/build_wind.py
python3 research/scripts/map_style/serve_range.py 18786
```

The fetch command is a reproducible example of the captured field, **not an
instruction to refetch it now**. NOMADS retains a short rolling window. For a
later refresh explicitly select an available GFS 00/06/12/18 UTC cycle and a
valid time at or before now. The crop is bounded to 6° × 6° maximum, 2 MB and
two attempts; exact errors are retained and failure preserves the previous
validated field. There is no automatic fallback, synthetic wind or third retry.
The offline builder revalidates raw checksum, level, units, component pair and
GRIB run/valid timestamps against the receipt before writing the preview.

Update plan: GFS cycles six-hourly; explicitly refresh this private preview
on that cadence when evaluating it. No new timer is installed. Page age is
measured from **model run**, never receipt/download time; an invalid, future
valid time or run older than 18 h hides the wind. The page rechecks each minute
and the animation checks freshness each frame. Missing/malformed JSON fails
closed. Reload after replacing a field; no silent background refresh occurs.
For another sector use `--bounds WEST SOUTH EAST NORTH` and the existing page
`?lon=…&lat=…&zoom=…` parameters; the grid/renderer are not Morro-node-specific.

## Style and interpretation

Reuses study `layers.py::wind(3)`: WCM seven-stop blue/cyan/green/yellow/orange/
red/magenta ramp normalized to 0–30 kt (end colours clamp), 22 fading trail
segments, 0.9 px round strokes, darkened medium seafloor base. Wind components
are physically east/north; bilinear sampling never extrapolates outside the
crop. Canvas particles animate **toward** the wind, with speed-to-knots legend
and click samples. 1,600 visual tracers and bounded lifetimes keep work bounded.
Motion is exaggerated 900× and is not a parcel/path forecast. Randomness seeds
only tracer positions/lifetimes, **never the wind data**.

The retained 50,493,781-byte medium archive is reused unchanged; SHA256
`538267f0cc6342a5e37b48487e06c731d28dfc869b06cbd5239e466978073e4f`
matches the merged SST receipt. It is not the different MAPSTYLE-3b archive.
Hard-edged gray/tan gaps are the retained survey footprint, not missing wind
or a land mask. The 72%-dark tint follows wind(3), but retains the medium
survey relief underneath. This page intentionally shows land **and** sea
model winds; it does not infer a coastline from absent bathymetry.

**RESEARCH PREVIEW — NOT FOR NAVIGATION.** Coarse GFS misses harbor, headland,
gust and fine topographic effects. Fine-looking trajectories do not add
resolution. Wind is atmospheric 10 m wind, not ocean current. Seafloor survey
coverage is patchy, vertical references vary, and the base is not a nautical
chart. Source attribution: NOAA / NCEP GFS; medium survey provenance follows
the retained MAPSTYLE/SST receipt. No alerts, forecasts or assets published.
