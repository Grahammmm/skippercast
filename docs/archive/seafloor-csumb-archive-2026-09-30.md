# Original CSUMB archive adapter — September 30, 2026

Original Big Sur South grids use gzip tar archives hosted at NOAA under
`platforms/ocean/ships/harold_heath/`. The existing ArcInfo GRID decoder accepted
only USGS `.tgz`, preventing these originals from entering the native pipeline.

The fetcher now accepts `.tar.gz` only for that reviewed NOAA prefix and the
`arcgrid` format. Other ships, hosts and formats remain rejected. The same exact
member selection, checksum verification, 4,096-entry / 2 GB expanded-byte limits,
unsafe-entry rejection and AIG decoder apply. Private recovery preserves the
original `source.tar.gz`; extracted grids remain reproducible scratch.

## Actual original proof

Cached [BSS Block03](https://www.ngdc.noaa.gov/ships/r_v_harold_heath/BSS_Block03_mb.html)
archive: 179,158,386 bytes; SHA256
`0414c642e74e52773ebe4c36d01220cfef5bf7f5f71d8cb2627a399863e64e83`.
Exact grid: `BSS_Block03/Bathymetry/ArcViewGrids/bss03_2mbathy`.
The decoder retains native 2 m NAD83/UTM10 spacing and the raster mask:
5,630,223 valid pixels, all nominally within 300 ft in the source datum.
These are source pixels, not deduplicated geographic expansion.

The source review must still reconcile original NAVD88/Geoid09 metadata,
interpolation uncertainty and [current CSUMB use terms](https://csumb.edu/undersea/sfml-data-library/).
Public display is permitted by that policy; for-profit use requires express
permission. This format change grants no license, qualifies no catalog row and
publishes no habitat. The normalized draft remains private pending review.

Existing USGS ArcInfo sources retain identical scientific raster identities and
valid/shallow pixel counts. Offline regressions cover native decoder parity,
allowed cache paths, disallowed hosts/formats and malicious/oversized archives.

## Cache-key review

The adapter implementation hash changed intentionally. Re-ingestion retained
USGS SGF raster identity `61c7cc0b37b6e6d07e15029e9b78ec8f8f922bd5ba9e54e7176c7f9812771f65`
(6,801,023 valid / 1,006,190 shallow pixels) and SUR identity
`7b578659dbd15e190c5012b182b077799dfabb2e3d025c8c0cbc34e4e4461e69`
(9,947,888 valid / 2,806,415 shallow pixels). Their existing manifest reviews
accept these exact scientific identities across lossless container encodings.
The pinned cache-key test is updated with this parity proof, not bypassed.
