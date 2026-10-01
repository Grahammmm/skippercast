// Synthetic UI data only: never a forecast, observation or production feed.
// Match requested coordinates/fields so browser tests do not call model services.
export function forecastFixture(url: URL, now = Date.now()) {
  const start = Math.floor(now / 86_400_000) * 86400;
  const time = Array.from({length: 9 * 24}, (_, i) => start + i * 3600);
  if (url.pathname.endsWith('/meta.json')) return {
    last_run_initialisation_time: start, last_run_availability_time: start,
    last_run_modification_time: start, data_end_time: time.at(-1),
    temporal_resolution_seconds: 3600, update_interval_seconds: 21600,
  };
  const values: Record<string, [number, string]> = {
    wind_speed_10m: [6, 'kn'], wind_gusts_10m: [9, 'kn'], wind_direction_10m: [300, '°'],
    visibility: [20000, 'm'], precipitation: [0, 'mm'], temperature_2m: [62, '°F'],
    cloud_cover: [20, '%'], weather_code: [0, 'wmo code'],
  };
  for (const [name, height, period] of [['wave', 2.5, 12], ['wind_wave', .5, 4], ['swell_wave', 2, 12], ['secondary_swell_wave', .5, 16]] as const) {
    values[`${name}_height`] = [height, 'ft'];
    values[`${name}_period`] = [period, 's'];
    values[`${name}_direction`] = [290, '°'];
  }
  const fields = (url.searchParams.get('hourly') || '').split(',').filter(Boolean);
  const lats = (url.searchParams.get('latitude') || '').split(',').map(Number);
  const lons = (url.searchParams.get('longitude') || '').split(',').map(Number);
  const rows = lats.map((latitude, i) => ({
    latitude, longitude: lons[i], utc_offset_seconds: 0, timezone: 'UTC',
    hourly_units: {time: 'unixtime', ...Object.fromEntries(fields.map(f => [f, values[f]?.[1] || 'unknown']))},
    hourly: {time, ...Object.fromEntries(fields.map(f => [f, time.map(() => values[f]?.[0] ?? null)]))},
  }));
  return rows.length === 1 ? rows[0] : rows;
}
