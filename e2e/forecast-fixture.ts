import {FT_PER_M, KMH_PER_MS, KN_PER_MS, MPH_PER_MS} from '../server/units.js';

// Synthetic UI data only: never a forecast, observation or production feed.
export class ForecastFixtureQueryError extends Error {}

const SPEED = {kn: [KN_PER_MS, 'kn'], kmh: [KMH_PER_MS, 'km/h'], ms: [1, 'm/s'], mph: [MPH_PER_MS, 'mp/h']} as const;
const DECIMAL = /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?$/i;
const round = (value: number, scale: number) => Math.round(value * scale) / scale;

// Match requested coordinates/fields so browser tests do not call model services.
export function forecastFixture(url: URL, now = Date.now()) {
  const start = Math.floor(now / 86_400_000) * 86400;
  const time = Array.from({length: 9 * 24}, (_, i) => start + i * 3600);
  if (url.pathname.endsWith('/meta.json')) return {
    last_run_initialisation_time: start, last_run_availability_time: start,
    last_run_modification_time: start, data_end_time: time.at(-1),
    temporal_resolution_seconds: 3600, update_interval_seconds: 21600,
  };
  const params = url.searchParams;
  const coordinates = (key: string) => (params.get(key) ?? '').split(',').map(value => {
    const token = value.trim();
    return DECIMAL.test(token) ? Number(token) : NaN;
  });
  const lats = coordinates('latitude'), lons = coordinates('longitude');
  if (lats.length !== lons.length || lats.length > 50
    || lats.some(v => !Number.isFinite(v) || Math.abs(v) > 90)
    || lons.some(v => !Number.isFinite(v) || Math.abs(v) > 180)) {
    throw new ForecastFixtureQueryError('latitude and longitude must be matching lists of up to 50 in-range numbers');
  }
  const option = <T extends string>(key: string, allowed: readonly [T, ...T[]]): T => {
    const requested = params.get(key) || allowed[0];
    const value = allowed.find(unit => unit === requested);
    if (value === undefined) throw new ForecastFixtureQueryError(`Invalid ${key}`);
    return value;
  };
  const [speedFactor, speedUnit] = SPEED[option('wind_speed_unit', ['kmh', 'ms', 'mph', 'kn'])];
  const imperial = option('length_unit', ['metric', 'imperial']) === 'imperial';
  const fahrenheit = option('temperature_unit', ['celsius', 'fahrenheit']) === 'fahrenheit';
  const precipitationUnit = option('precipitation_unit', ['mm', 'inch']);
  const timeUnit = option('timeformat', ['iso8601', 'unixtime']);
  // The fixture uses UTC. Match the provider's time representation without simulating its local clock.
  const hourlyTime = timeUnit === 'unixtime' ? time : time.map(t => new Date(t * 1000).toISOString().slice(0, 16));
  const speed = (knots: number): [number, string] => [round(knots * speedFactor / KN_PER_MS, 10), speedUnit];
  const values: Record<string, [number, string]> = {
    wind_speed_10m: speed(6), wind_gusts_10m: speed(9), wind_direction_10m: [300, '°'],
    visibility: imperial ? [Math.round(20000 * FT_PER_M), 'ft'] : [20000, 'm'],
    precipitation: [0, precipitationUnit], temperature_2m: fahrenheit ? [62, '°F'] : [16.7, '°C'],
    cloud_cover: [20, '%'], weather_code: [0, 'wmo code'],
  };
  for (const [name, height, period] of [['wave', 2.5, 12], ['wind_wave', .5, 4], ['swell_wave', 2, 12], ['secondary_swell_wave', .5, 16]] as const) {
    values[`${name}_height`] = imperial ? [height, 'ft'] : [round(height / FT_PER_M, 100), 'm'];
    values[`${name}_period`] = [period, 's'];
    values[`${name}_direction`] = [290, '°'];
  }
  const fields = (params.get('hourly') || '').split(',').filter(Boolean);
  const rows = lats.map((latitude, i) => {
    const hourly_units: Record<string, string> = {time: timeUnit, ...Object.fromEntries(fields.map(f => [f, values[f]?.[1] || 'unknown']))};
    const hourly: Record<string, (string | number | null)[]> = {
      time: hourlyTime, ...Object.fromEntries(fields.map(f => [f, time.map(() => values[f]?.[0] ?? null)])),
    };
    return {latitude, longitude: lons[i]!, utc_offset_seconds: 0, timezone: 'UTC', hourly_units, hourly};
  });
  return rows.length === 1 ? rows[0]! : rows;
}

/** The synthetic shared feed has the unit-checked shape of /api/forecast. */
export function sharedForecastPoint(point: {latitude: number; longitude: number; hourly: Record<string, unknown>}) {
  const hourly = Object.keys(point.hourly).filter(key => key !== 'time');
  const url = new URL('https://fixture.invalid/forecast');
  url.search = new URLSearchParams({latitude: String(point.latitude), longitude: String(point.longitude),
    hourly: hourly.join(','), timeformat: 'unixtime', wind_speed_unit: 'kn', temperature_unit: 'fahrenheit',
    length_unit: hourly.includes('wave_height') ? 'imperial' : 'metric'}).toString();
  const row = forecastFixture(url);
  if (!('hourly' in row)) throw new Error('Expected one shared forecast point');
  return row;
}
