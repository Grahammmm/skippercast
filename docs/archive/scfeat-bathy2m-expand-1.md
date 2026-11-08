# SCFEAT-BATHY2M-EXPAND-1 — first private sector slice

Del Norte (`del-norte`, order **1** in `catalog/coast-seafloor-inventory.json`).
This deliberately follows the inventory's north-to-south order, not proximity to
Morro Bay. Stacked on the actual MAPSTYLE-3b pipeline in
`claude/mapstyle-2-relief` (PR1750 merged there, not main; PR1743 still open).

## What the viewer sees

`research/scripts/map_style/del-norte-test.html` shows retained NOAA F00562
bathymetry with **medium relief**, transparent unsupported cells over tan, native
spacing, acquisition dates, original source link and datum limitations. The
public application is unchanged. **PRIVATE RESEARCH PREVIEW — NOT FOR NAVIGATION.**

The first slice uses one already-cached, hash-checked **1 m** native grid (finer
than the inventory's 2 m tier). No downloads or resampling to pretend a coarser
source is native 2 m. BAG band 1 is positive-up elevation in metres; its
compound CRS's depth-axis label is not a reason to negate storage values.
The horizontal CRS is retained for rendering; no vertical transformation occurs.
Native nodata and the nominal 0–91.44 m depth mask are applied before averaging
into display pixels. An entirely empty EPSG:3310 background prevents accidental
Morro coverage or invented deeper context in this sector.

## Source and measured build

- Original: [F00562_MB_1m_MLLW_1of2.bag](https://data.ngdc.noaa.gov/platforms/ocean/nos/coast/F00001-F02000/F00562/BAG/F00562_MB_1m_MLLW_1of2.bag).
- Source SHA256: `f81742d79f90e306167d140e9de4133bb5bf449ab19a95d3957c8d0abd85458f`;
  source and embedded metadata digests checked against the retained native-depth audit.
- Acquired **2008-11-18 to 2008-11-23**, not newly surveyed. Release date unknown.
- Nominal **MLLW**, realization not verified; no tide correction, sounding accuracy
  or navigation-qualified/current depth claim. Uncertainty is not qualified here.
- **757,393** valid shallow native cells; **757,393 m²** nominal cell area. This
  is a single grid's cell sum, not continuous sounding support, geographic growth
  credit, deduplicated regional coverage or a percentage of the sector.
- Private archive: **214,384 bytes**, **18 tiles**, z8–15. z8/9/10/11: one tile
  each; z12: two; z13/14/15: four each.
- Archive SHA256: `b38b96ecce7ca25686cb521d0fe2fe3f22a9ed845b2f7a2f4bb672554d59bd36`.
- Actual Chromium readback: tiles loaded, no map/page errors; screenshot inspected.
  Pronounced striping and seam-like patterns remain. They are **not** claimed as
  seabed structures or habitat. No scientific artifact acceptance is implied.

## Reproduce privately

Use the existing survey environment and retained original BAG; this script has
no acquisition/network path:

```sh
python research/scripts/map_style/build_del_norte.py --bag /local/F00562_MB_1m_MLLW_1of2.bag
python research/scripts/map_style/serve_range.py 18782
```

Open `/research/scripts/map_style/del-norte-test.html` on that local server.
Outputs and detailed receipt stay under ignored `var/seafloor/bathy-del-norte/`.
The archive deliberately keeps the existing guarded basename in its sector
subdirectory, so the unchanged public-build exclusion still rejects it even if
copied into `dist`. No tiles, raw data or machine-local source locators are committed.

## Verification and remaining scope

Test-first regression failed on the old exact-2/5 m restriction, then passed.
The tile suite passes **25 tests**; the client-build/public exclusion suite
passes **10 tests**. Local repository checker reports **ALL PASS**.

This is the bounded **bathymetry-only** first slice, not completion of the large
recommendation. Hard-bottom classes need actual classified-source evidence and
independent interpretation review; terrain shade is not substrate. Numeric
source depth at the cursor, additional Del Norte grids, wider coverage and the
next sector (`crescent-city-humboldt`) remain future work. No public publication,
ranking, fishing export or live map integration is included.
