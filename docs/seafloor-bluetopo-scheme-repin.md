# BlueTopo tile scheme re-pin (2026-11-09 scheme)

`catalog/bluetopo-sample.json` pinned
`BlueTopo_Tile_Scheme_20260924_191855.gpkg` (sha256 `62db77bd…188dcc`). NOAA
replaces the scheme object when it republishes, and that URL now returns
HTTP 404, so `reaches --fetch` and `restore-reference --fetch` could not start
from a cold cache.

## Retrieval record

- Listing: `https://noaa-ocs-nationalbathymetry-pds.s3.amazonaws.com/?prefix=BlueTopo/_BlueTopo_Tile_Scheme/`
  (the official NOAA OCS National Bathymetric Source bucket, AWS Registry of
  Open Data). It lists exactly one key, the scheme below.
- URL: `https://noaa-ocs-nationalbathymetry-pds.s3.amazonaws.com/BlueTopo/_BlueTopo_Tile_Scheme/BlueTopo_Tile_Scheme_20261109_115701.gpkg`
- Retrieved 2026-11-10T03:20:41Z: HTTP 200, `Last-Modified: Mon, 09 Nov 2026 17:11:45 GMT`,
  ETag `68787a74469b6921e184f921e8af9055`, 6,717,440 bytes.
- sha256 `0f8694701ca4c432d2d5ee174e2f3e6dfde004ee64b5770bb265c8dc5ea5bd9b`
  (an independent reviewer re-hashed the same bytes to the same value).
- Contents: one feature table `BlueTopo_Tile_Scheme_20261109_115701`, 12,638
  tiles. 34 tiles intersect the Morro Bay region bounds (33 at 4 m, 1 at
  16 m), each with a GeoTIFF link and a publisher checksum. The pinned sample
  tiles BH4545C2, BH4525C2 and BH44P5CD are present.

## Effect on the reference (measured privately, not committed)

A private rebuild with this pin (`grid.build`, no fetch, same overview
samples) gives the same 252 tiles, the same 55,544 cells and the same band area
for every one of the 46 reaches (total 3,307.514375 km²; unknown reference
5.018125 km²). Three tile records changed upstream (BC24R26X, BH4585BV,
BH4585BW: delivered date, URL and publisher checksum); their samples give the
same cells.

Hash-bound fields therefore change:

| Artifact | Field | Committed | With this pin |
|---|---|---|---|
| `dist/data/seafloor-ledger.json` | `input_hash` | `80c21708…6068b` | `ea3df150…0a0c` |
| `dist/data/seafloor-ledger.json` | `reference_cells_sha256` | `8de292a4…d490` | `60ae92cc…efd6a` |
| `dist/data/seafloor-ledger.json` | `reference.scheme_url`, `reference.scheme_sha256`, 3 tile records | old scheme | this scheme |
| `catalog/reaches.json` | `input_hash` | `80c21708…6068b` | `ea3df150…0a0c` |

Nothing else in the ledger changes.

## Boundary

This change re-pins the scheme only. It does **not** update the ledger or
`catalog/reaches.json`: the ledger is the live published artifact, and a
ledger change belongs to the ledger owner's regeneration run (the `seafloor`
workflow's ledger PR, or an attended rebuild in the pinned CI environment).
Until that regeneration lands, `restore-reference` fails closed with
"Rebuilt reference differs from committed baseline; no cache installed". This
replaces the current failure (HTTP 404 on the old scheme) and installs nothing.
The private rebuild above passed `restore.install_verified` against a ledger
patched only in the fields listed, and the committed ledger refused the same
cells. Merge this re-pin together with, or after, that regeneration.
