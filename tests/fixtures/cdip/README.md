# CDIP nearshore fixture (FE-40)

`SL345.das` and `SL345.ascii` are a small excerpt of CDIP's public MOP
alongshore forecast for site SL345 (Morro Rock), read on 2026-10-08 at about
15:59 UTC from:

- `https://thredds.cdip.ucsd.edu/thredds/dodsC/cdip/model/MOP_alongshore/SL345_forecast.nc.das`
- `https://thredds.cdip.ucsd.edu/thredds/dodsC/cdip/model/MOP_alongshore/SL345_forecast.nc.ascii?waveTime,waveHs,waveTp,waveDp,waveFlagPrimary,waveFlagSecondary,metaLatitude,metaLongitude,metaWaterDepth,metaSiteLabel`

The excerpt keeps the six variable blocks the collector reads and seven
`NC_GLOBAL` attributes (contact and processing-history attributes removed), and
eight of the file's 80 three-hour samples (indices 28 to 35, 2026-10-08T12:00Z
to 2026-10-09T09:00Z) with the declared array lengths changed from 80 to 8.
Values are otherwise as published. The file's licence attribute reads "These
data may be redistributed and used without restriction." Data from CDIP,
Scripps Institution of Oceanography (https://cdip.ucsd.edu/).

Tests derive the failure cases (identity, coordinates, truncation, flags,
contract changes) from this excerpt in code.
