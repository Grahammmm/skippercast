# Current weather and ocean observations

SkipperCast separates measurements from forecasts. **Live** shows the latest
available NOAA observations with their station, observation time and age. Waves,
Wind and the seven-day timeline show model forecasts. Neither is an entrance
clearance or a prediction of catch success.

## Sources and refresh

- **Diablo Canyon buoy 46215:** significant wave height, dominant period and
  direction, water temperature, and separately timed swell / wind-wave components.
  [NOAA station](https://www.ndbc.noaa.gov/station_page.php?station=46215).
- **Cape San Martin buoy 46028:** an offshore wind and sea reference about 55 nm
  WNW of Morro Bay. It is not a sheltered-bay measurement.
  [NOAA station](https://www.ndbc.noaa.gov/station_page.php?station=46028).
- **San Luis Obispo airport KSBP:** weather, air temperature, wind and visibility.
  This land station cannot measure wind or fog at the bar or fishing grounds.
  [NWS observation API](https://api.weather.gov/stations/KSBP/observations/latest).
- **Port San Luis 9412110:** measured water level, feet above MLLW; a nearby tide
  reference, not Morro Bay current or slack predictions.
  [NOAA station](https://tidesandcurrents.noaa.gov/stationhome.html?id=9412110).
- **NWS PZZ645 / PZZ670:** active coastal and offshore advisories are checked
  independently of the forecast refresh.

The browser checks observations and advisories every five minutes while visible,
and on return to a stale tab. Forecast models refresh every 30 minutes. Manual
Refresh requests both. Missing, failed and over-two-hour-old measurements are
clearly marked; neither a fetch time nor a retained reading becomes an observation
time. The browser never derives zero wind or calm seas from missing values.

NDBC text files do not allow cross-origin browser reads. A small GitHub Actions
job collects their public data at minutes 7 and 37 of each hour and publishes
`https://raw.githubusercontent.com/Grahammmm/skippercast/conditions/latest.json`.
It also runs on changes to its collector and supports manual dispatch. Source
errors are published before the job reports a failure. This is a near-real-time
feed, not streaming sensor data: NOAA publication and GitHub scheduling can delay
updates. The original sample times and failed refresh state remain visible.
Regions refresh independently: a region whose collector raises is recorded as
`status: failed` (with `error_class`) in `regions/index.json` and keeps its last
published files, while the other regions publish; the cycle fails only when the
default region or more than half of the regions fail.
The job operates without this Mac or a browser open.

The same job collects NOAA GFS and ECMWF IFS winds plus NOAA GFS Wave 0.16°
and ECMWF WAM seas for every published regional forecast point. The finer NOAA
wave grid replaced its 0.25° product after several coastal cells returned zero
height and zero period. Its coverage audit
checks each point's next seven local 7 a.m.–1 p.m. windows hour by hour. The
published regional intelligence includes rated-hour and independent-model
counts; `intelligence-health.json` reports point-days with full wind-and-sea
coverage and two-model coverage. A point-day missing any usable wind or
combined-sea hour degrades the scheduled run instead of silently displaying a
calm or complete rating. A comparison gap remains visible as limited coverage.
Forecast grids can represent the same coarse water cell for nearby points, so
complete data coverage does not imply reef-scale weather accuracy.

The conditions branch is independent of the daily fishing-evidence data branch;
the two jobs do not write the same files or branch. Each cycle replaces the
branch with one parentless commit, so it carries only the current snapshot. No API keys or private
observations are used. [Job status](https://github.com/Grahammmm/skippercast/actions/workflows/live-conditions.yml).

## Recorded buoy history (FE-42)

`python -m skippercast.pipeline.ndbc_history` builds the History view's
`HistoryBundle` (`packages/coast/src/history-types.ts`) for 46215 and 46028 and
[`buoy-history.yml`](../.github/workflows/buoy-history.yml) publishes it to the
`data` branch as `regions/morro-bay/history.json` (served at
`/feeds/data/regions/morro-bay/history.json`). It is descriptive recorded
history, not a climatology, forecast or catch probability.

- **Full pass** (monthly, and the one-off backfill by manual dispatch): reads each
  station's archive index and every annual standard-met file it lists (46215
  from 2004, 46028 from 1983; 65 files, about 12 MB compressed). Each file is
  kept under `var/ndbc-history/ndbc/stdmet/<station>/<year>/<sha256>.bin` with a
  checkpoint recording its URL, fetch time, size and SHA-256; a later pass reuses
  any file whose bytes still match and downloads nothing for it. `--revalidate`
  refetches them when NOAA may have revised an archive. The workflow carries the
  checkpoints between runs in the Actions cache; if the cache is evicted the next
  full pass simply downloads the files again.
- **Recent pass** (weekly): fetches only the two 45-day realtime files and keeps
  the published monthly bands, archive index and annual receipts unchanged.
  Until the first full backfill has published `history.json`, the recent pass
  skips with a notice and publishes nothing, so run the full pass first.
- **Aggregation:** UTC-hour means of valid samples only, with raw and per-metric
  counts. Monthly p10 / median / p90 (linear interpolation), min, max and mean
  pool those hours across years, each hour weighted equally, with the count,
  calendar hours expected, coverage fraction and the years that contributed.
  The 7-, 14- and 45-day views read the 45 days of hourly means. Missing hours
  and sentinel values are counted, never filled or interpolated; conflicting
  duplicate rows mask the value.
- **Failures:** a station whose index or annual files fail keeps its published
  baseline; a failed realtime file keeps the last series, marked stale after
  three hours. If every request fails nothing is published.
