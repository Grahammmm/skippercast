# Tiny native ArcInfo GRID fixture

`abc3x1.json` encodes the seven unmodified files from GDAL's real AIG driver
fixture at commit `73115b03dceb32790d042c4538b29468786f7737`:
https://github.com/OSGeo/gdal/tree/73115b03dceb32790d042c4538b29468786f7737/autotest/gdrivers/data/aigrid/abc3x1

The base64 representation keeps the tiny fixture text-reviewable; each file has
its original SHA-256. Tests decode it into a temporary archive and exercise the
actual GDAL AIG decoder, extraction, normalization and offline cache recovery.
The upstream MIT notices are retained in `LICENSE-GDAL.txt`. This is test data,
not a California survey or evidence of geographic coverage.
