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
The job operates without this Mac or a browser open.

The conditions branch is independent of the daily fishing-evidence data branch;
the two jobs do not write the same files or branch. No API keys or private
observations are used. [Job status](https://github.com/Grahammmm/skippercast/actions/workflows/live-conditions.yml).
