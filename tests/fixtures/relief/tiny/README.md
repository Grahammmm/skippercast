# `tiny` relief fixture

Synthetic inputs for the relief pipeline (`src/skippercast/relief/`, card E2E-01).
Nothing here is survey data and nothing here may be published.

`tiny_region.py` writes three small GeoTIFFs with a pure-Python writer (no GDAL, so the
bytes are identical on every machine and no binary file is committed):

| File | Size | Cells | CRS | Nodata |
|---|---|---|---|---|
| `projected_1m.tif` | 24 x 24, 1 band Float32 | 1 m | EPSG:26910 (UTM 10N), no vertical datum | -9999, 3 x 3 hole |
| `geographic_1m.tif` | 24 x 24, 1 band Float32 | about 1 m (1.1e-5 x 9.0e-6 deg) | EPSG:4269 (NAD83) | -9999, 2 x 3 hole |
| `bluetopo_like_3band.tif` | 16 x 16, 3 bands Float32 (Elevation, Uncertainty, Contributor) | 4 m | EPSG:26910 + NAVD88 height keys | 1000000, 2 x 4 block |

It also builds a four-stage stand-in receipt chain (`inventory` -> `normalize` -> `select`
-> `mosaic.public`) that only lists and hashes files, so the receipt rules and
`region.py status` can be exercised end to end:

```bash
python3 tests/fixtures/relief/tiny/tiny_region.py "$TMPDIR/relief-out"
python3 scripts/relief/region.py status --region tiny --out "$TMPDIR/relief-out"
```

Tests import it with `importlib` from `tests._support.FIXTURES` and write only under `tmp_path`.
