# MAPSTYLE-3b — Morro–Avila native shallow bathymetry

Candidate/test-page only. The live app map is untouched. Stacked on PR 1743,
`claude/mapstyle-2-relief` at `ad10ae19fb17ccf1ec08bce289d7d4d733dfbfb2`;
the PR base is that still-open branch, not main.

## Built, measured result

- Default: the G-selected **medium** relief, both CLI/build and test page.
- Private PMTiles: **61,129,842 bytes**, **837 tiles**, z8–15.
  z14: 33 tiles; z15: 107 tiles, only tiles containing native 2 m shallow support.
- 2 m takes priority over 5 m, which takes priority over the existing 10 m raster.
  Only nominal native elevations −91.44 to 0 m enter the shallow tier. Deeper
  cells retain the 10 m background. Elevations are smoothstep-feathered across
  40 m of overlap, with a larger halo covering feather plus shading kernels.
- Unique sampled support on a 2 m equal-area grid: **76.205260 km² at 2 m**,
  plus **0.672544 km² of 5 m-only support**;
  total **76.877804 km²**. This is a categorical boundary-sampled
  area, not an exact survey polygon or datum-qualified chart-depth area.

| Native grid | Spacing | Nominal 0–300 ft area (km²) | Extracted grid bytes |
|---|---:|---:|---:|
| `csumb-pge-avila-blocki-2m-native` | 2 m | 43.083036 | 77,808,088 |
| `csumb-pge-avila-blocki-5m-native` | 5 m | 43.268800 | 14,275,415 |
| `csumb-pge-avila-blockj-2m-native` | 2 m | 35.277764 | 70,624,332 |
| `csumb-pge-avila-blockj-5m-native` | 5 m | 35.783075 | 14,234,405 |

Per-source areas overlap: do not add that table. See the deduplicated area above.
The four grids come from NOAA-hosted CSUMB `PGE_AvilaBay_additional_products.tar.gz`
(**938,065,756 bytes**), SHA256
`6227d55f46cc5754fc871852d9444a2d619b38edf9b99114be2d8a15f0d78fab`. Used members are the I/J
`2mbthy` and `5mallbt` ArcView grids. The existing 10 m background is
`c1-t_229826b7-v2/elevation.tif` (**265,612,503 bytes**), SHA256
`525d26a42e42d4f9afbeb747e14c0f5f04ac0c8d52ce8339e430d6093dbed319`. Each extracted file has its own byte count and
SHA256 in the local `morro-avila-source-manifest.json` receipt.

Source URL: https://data.ngdc.noaa.gov/platforms/ocean/ships/ventresca/PGE_AvilaBay/multibeam/data/version2/products/PGE_AvilaBay_additional_products.tar.gz

## Evidence and honest limits

Six fixed-camera 1280×800 screenshots are in
`/home/user/agent-work/reports/mapstyle-3/`: `avila-1` and `avila-2`, each with
`before`, `control-10m`, and `after` suffixes. All use medium relief at displayed z15.
The existing 10 m archive has **no coverage at these Avila cameras**. The before
images honestly show that absence. A separate, explicitly labelled **derived
10 m control** averages the same native I survey to 10 m cells, renders at z13,
and overzooms at the same z15 cameras. It is not the pre-existing 10 m survey and
must not be presented as one. Browser evidence: all six views loaded without
page/map errors, `tilesLoaded=true`, default variant `medium`.

Native relief is visible at both cameras, with finer irregular features than
the derived control. Survey striping/ribbing remains conspicuous and must not be
called seabed structure. Image inspection found no obvious regular tile grid or
large void cliff in the native views, but did flag suspect angular rims and a
vertical seam in the derived control. This is not a scientific accuracy approval.
Synthetic tests verify monotonic offset blending without invented extrema,
transparent unsupported cells, depth gating, native grid validation/ordering,
z15 native output, and identical planar tier/tile joins. A real native-edge probe
measured 8,246 overlap pixels,
max feather adjustment 1.187831 m;
that single probe is not regional proof of artifact-free joins.

The source catalog's SCC Block25 is outside Morro–Avila and is excluded. The added
native data are catalogued Avila I/J slices, not region-wide 2 m coverage. Block J's
native 2 m datum remains unknown; I and the 5 m companion metadata declare NAVD88
Geoid03. The 10 m background has mixed references. No datum correction, sounding
accuracy, habitat interpretation or navigation qualification is claimed. Per-cell
uncertainty and interpolation masks remain unknown. Rights were not re-audited,
as directed; tile archives stay private and MAPSTYLE-1's public guard is unchanged.

## Rebuild

Use the survey environment. Extract the listed ArcView grid members, verify the
archive/component hashes against the local receipt, and create a local JSON list:
`[{"id":"csumb-pge-avila-blocki-2m-native","path":"/local/cc_bi_2mbthy","resolution_m":2,"source_file":"PGE_AvilaBay_additional_products.tar.gz","archive_sha256":"6227d55f46cc5754fc871852d9444a2d619b38edf9b99114be2d8a15f0d78fab"}]`
with all four grids. Local paths must not be committed. Then:

```sh
python scripts/build_bathy_tiles.py --source /local/elevation.tif --native-manifest /local/native-manifest.json --maxzoom 15
```

Private output, source manifest, coverage/edge diagnostics, browser receipts and
screenshot driver remain in the local report/scratch directories, not the public
build. The retained source cache is untouched. Task-owned extracted raw grids and
the derived raw control are deleted after tiling and diagnostics.
