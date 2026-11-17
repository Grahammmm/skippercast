# Source review: NOAA Digital Coast DEM datasets admitted as reviewed original URLs

Status: proposed in a draft PR; needs an independent (Codex) review before merge.
Reviewed 2026-11-09 by opus-coder-bopus (SEAFLOOR-RUN-2). Listings retrieved
2026-11-10T03:2x UTC from the public bucket index pages below.

## What changes

`src/skippercast/seafloor/fetch.py` admits seven exact dataset folders of the
public NOAA Office for Coastal Management bucket
`https://noaa-nos-coastal-lidar-pds.s3.amazonaws.com/dem/<dataset>/`
(AWS Registry of Open Data: <https://registry.opendata.aws/noaa-coastal-lidar/>):
five NCMP folders as reviewed originals (`DIGITAL_COAST_DEM_PREFIXES`) and two
CoNED folders as inspect-only compilations (`COMPILATION_PREFIXES`).
The rest of the bucket (other DEMs, `laz/` point clouds) stays refused, and
the existing `bluetopo` and `/modeling/` refusals are unchanged.

| Folder | Dataset (bucket index title) | Public listing | Metadata |
|---|---|---|---|
| `USACE_CA_DEM_2009_9488` | 2009 USACE NCMP Topobathy Lidar DEM: California | [index](https://noaa-nos-coastal-lidar-pds.s3.amazonaws.com/dem/USACE_CA_DEM_2009_9488/index.html), [Data Access Viewer 9488](https://coast.noaa.gov/dataviewer/#/lidar/search/where:ID=9488) | [InPort 67050](https://www.fisheries.noaa.gov/inport/item/67050) |
| `USACE_CA_DEM_2010_9438` | 2010 USACE NCMP Topobathy Lidar DEM: California | [index](https://noaa-nos-coastal-lidar-pds.s3.amazonaws.com/dem/USACE_CA_DEM_2010_9438/index.html), DAV 9438 | [InPort 66005](https://www.fisheries.noaa.gov/inport/item/66005) |
| `USACE_CA_DEM_2011_9432` | 2011 USACE NCMP Topobathy Lidar DEM: California | [index](https://noaa-nos-coastal-lidar-pds.s3.amazonaws.com/dem/USACE_CA_DEM_2011_9432/index.html), DAV 9432 | [InPort 65841](https://www.fisheries.noaa.gov/inport/item/65841) |
| `USACE_California_Topobathy_DEM_2014_5189` | 2014 USACE NCMP Topobathy Lidar DEM: California | [index](https://noaa-nos-coastal-lidar-pds.s3.amazonaws.com/dem/USACE_California_Topobathy_DEM_2014_5189/index.html), DAV 5189 | [InPort 49416](https://www.fisheries.noaa.gov/inport/item/49416) |
| `USACE_CA_Topobathy_DEM_2015_8482` | 2015 USACE NCMP Topobathy Lidar DEM: California | [index](https://noaa-nos-coastal-lidar-pds.s3.amazonaws.com/dem/USACE_CA_Topobathy_DEM_2015_8482/index.html), DAV 8482 | [InPort 51862](https://www.fisheries.noaa.gov/inport/item/51862) |
| `CA_Central_CoNED_DEM_2017_8657` | 1929–2017 USGS CoNED Topobathy DEM (Compiled 2017): Central Coast of California | [index](https://noaa-nos-coastal-lidar-pds.s3.amazonaws.com/dem/CA_Central_CoNED_DEM_2017_8657/index.html), DAV 8657 | [InPort 55319](https://www.fisheries.noaa.gov/inport/item/55319) |
| `CA_north_coned_DEM_2020_9181` | 1986–2019 USGS CoNED Topobathy DEM (Compiled 2020): Northern California | [index](https://noaa-nos-coastal-lidar-pds.s3.amazonaws.com/dem/CA_north_coned_DEM_2020_9181/index.html), DAV 9181 | [InPort 62987](https://www.fisheries.noaa.gov/inport/item/62987) |

## Review reasoning and limits

- Publisher: US government (USACE JALBTCX NCMP; USGS CoNED), distributed by
  NOAA OCM. The bucket is NOAA's official public distribution, listed in the
  AWS Registry of Open Data. Admitting a URL here only means "reviewed
  publisher location"; it grants no rights and promotes nothing.
- Each file still needs `add-survey` (native adapter inspection), operator
  metadata review and `promote-survey` (rights review for `usable`, or
  `--physical-only` for private processing). Pinned SHA-256 per file is still
  required for repeat use.
- NCMP tiles are 1 m bare-earth topobathy lidar grids (originally gridded by
  the producer, NAVD88 heights, often geographic NAD83 coordinates). They cover
  the shallow nearshore fringe, about 0 to 25 m depth in the Morro Bay sector.
- **CoNED is a compilation** (it merges lidar, multibeam and older soundings
  1929–2019; InPort 55319 and 62987 describe it as compiled). docs/seafloor.md
  treats compilations as context, not habitat depth, and the code now enforces
  that: the two CoNED folders are listed separately as
  `fetch.COMPILATION_PREFIXES`. Their files can be fetched, imported from a local
  source root and inspected with `add-survey` (the draft and adapter receipt are
  written), but `promote-survey` refuses them for both `usable` and
  `--physical-only`, the manifest validator refuses a CoNED row with either
  status, and `physical_source()` never selects one, so no public or private
  habitat run can use CoNED depth. To use the depth inside a CoNED footprint,
  qualify the contributing original survey (for example an NCMP tile) instead.
  The NCMP folders are originals and stay eligible. Folder admission holds only
  for canonical URL text: a URL such as `.../USACE_CA_DEM_2009_9488/../<other
  folder>/x.tif` (or a percent-encoded variant) refuses at fetch, import,
  promotion, manifest validation and selection, so no path can reach CoNED or
  an unreviewed folder through an NCMP prefix.
- Vertical datum: NAVD88 lidar heights are not MLLW. The pipeline performs no
  datum conversion, so the station-specific NAVD88–MLLW offset is not applied;
  it matters only near the 0 ft band edge. This is recorded, not hidden.
