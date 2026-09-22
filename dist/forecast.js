import { getRegion } from "./region.js?v=8.1";
// Pure data handling shared by the browser and offline checks. Missing is never calm.
export const STATIONS = [
  {
    id: "north",
    name: "Point Estero offshore",
    latitude: 35.45,
    longitude: -121.02,
  },
  {
    id: "central",
    name: "Estero Bay offshore",
    latitude: 35.36,
    longitude: -120.94,
  },
  {
    id: "south",
    name: "Point Buchon offshore",
    latitude: 35.24,
    longitude: -120.94,
  },
];
export const WIND_MODELS = [
  {
    id: "ecmwf_ifs025",
    name: "ECMWF IFS",
    meta: "https://api.open-meteo.com/data/ecmwf_ifs025/static/meta.json",
  },
  {
    id: "gfs_global",
    name: "NOAA GFS",
    meta: "https://api.open-meteo.com/data/ncep_gfs013/static/meta.json",
  },
];
export const WAVE_MODELS = [
  {
    id: "ecmwf_wam025",
    name: "ECMWF WAM",
    meta: "https://marine-api.open-meteo.com/data/ecmwf_wam025/static/meta.json",
  },
  {
    id: "ncep_gfswave025",
    name: "NOAA GFS Wave",
    meta: "https://marine-api.open-meteo.com/data/ncep_gfswave025/static/meta.json",
  },
];
export const TIMEZONE = getRegion().timezone;
export function localDate(date = new Date()) {
  const parts = Object.fromEntries(
    new Intl.DateTimeFormat("en-US", {
      timeZone: TIMEZONE,
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    })
      .formatToParts(date)
      .map((p) => [p.type, p.value]),
  );
  return `${parts.year}-${parts.month}-${parts.day}`;
}
export function futureDates(now = new Date()) {
  const start = new Date(`${localDate(now)}T12:00:00Z`);
  return Array.from({ length: 7 }, (_, i) =>
    new Date(start.getTime() + (i + 1) * 86400000).toISOString().slice(0, 10),
  );
}
export function forecastURLs() {
  const base = {
    latitude: STATIONS.map((s) => s.latitude).join(","),
    longitude: STATIONS.map((s) => s.longitude).join(","),
    forecast_days: 8,
    timezone: TIMEZONE,
    cell_selection: "sea",
  };
  const wind = new URLSearchParams({
    ...base,
    models: WIND_MODELS.map((m) => m.id).join(","),
    wind_speed_unit: "kn",
    hourly:
      "wind_speed_10m,wind_gusts_10m,wind_direction_10m,visibility,precipitation",
  });
  const wave = new URLSearchParams({
    ...base,
    models: WAVE_MODELS.map((m) => m.id).join(","),
    length_unit: "imperial",
    hourly: ["wave", "wind_wave", "swell_wave", "secondary_swell_wave"]
      .flatMap((k) => ["height", "period", "direction"].map((v) => `${k}_${v}`))
      .join(","),
  });
  return {
    wind: `https://api.open-meteo.com/v1/forecast?${wind}`,
    wave: `https://marine-api.open-meteo.com/v1/marine?${wave}`,
  };
}
export function valueAt(forecast, model, variable, time, unit) {
  if (forecast?.timezone !== TIMEZONE) return null;
  const times = forecast?.hourly?.time,
    key = `${variable}_${model}`,
    values = forecast?.hourly?.[key];
  if (
    !Array.isArray(times) ||
    !Array.isArray(values) ||
    values.length !== times.length ||
    forecast?.hourly_units?.[key] !== unit
  )
    return null;
  const index = times.indexOf(time);
  if (index < 0 || times.indexOf(time, index + 1) !== -1) return null;
  const value = values[index];
  return typeof value === "number" && Number.isFinite(value) && value >= 0
    ? value
    : null;
}
export function pacificEpoch(time) {
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(time)) return null;
  const desired = Date.parse(`${time}:00Z`);
  if (!Number.isFinite(desired)) return null;
  let guess = desired;
  const formatter = new Intl.DateTimeFormat("en-US", {
    timeZone: TIMEZONE,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  });
  for (let i = 0; i < 3; i++) {
    const p = Object.fromEntries(
      formatter.formatToParts(new Date(guess)).map((p) => [p.type, p.value]),
    );
    const actual = Date.parse(
      `${p.year}-${p.month}-${p.day}T${p.hour}:${p.minute}:00Z`,
    );
    guess += desired - actual;
  }
  return guess / 1000;
}
export function coverageNote(meta, time) {
  if (!Number.isFinite(meta?.data_end_time))
    return "Latest model coverage unavailable.";
  const epoch = pacificEpoch(time);
  return epoch !== null && epoch > meta.data_end_time
    ? "Beyond latest published model coverage; rolling values need separate run attribution."
    : null;
}
export function compass(degrees) {
  if (!Number.isFinite(degrees) || degrees < 0 || degrees > 360)
    return "unavailable";
  return [
    "N",
    "NNE",
    "NE",
    "ENE",
    "E",
    "ESE",
    "SE",
    "SSE",
    "S",
    "SSW",
    "SW",
    "WSW",
    "W",
    "WNW",
    "NW",
    "NNW",
  ][Math.round(degrees / 22.5) % 16];
}
export function range(values, digits = 1) {
  if (!values.length || values.some((v) => !Number.isFinite(v))) return null;
  const lo = Math.min(...values).toFixed(digits),
    hi = Math.max(...values).toFixed(digits);
  return lo === hi ? lo : `${lo}–${hi}`;
}
export function evidenceFlags(wind, wave, time) {
  const flags = [];
  if (wind && wind.timezone !== TIMEZONE)
    flags.push(
      "Wind response timezone is missing or not Pacific; values withheld.",
    );
  if (wave && wave.timezone !== TIMEZONE)
    flags.push(
      "Wave response timezone is missing or not Pacific; values withheld.",
    );
  for (const m of WIND_MODELS) {
    const speed = valueAt(wind, m.id, "wind_speed_10m", time, "kn"),
      gust = valueAt(wind, m.id, "wind_gusts_10m", time, "kn");
    if (speed === null || gust === null)
      flags.push(`${m.name}: missing wind or gust values.`);
    else if (gust < speed)
      flags.push(
        `${m.name}: gust is below sustained wind; these values are inconsistent.`,
      );
  }
  for (const m of WAVE_MODELS) {
    const combined = valueAt(wave, m.id, "wave_height", time, "ft");
    if (combined === null)
      flags.push(`${m.name}: combined seas unavailable for this hour.`);
    for (const component of [
      "wind_wave",
      "swell_wave",
      "secondary_swell_wave",
    ]) {
      const height = valueAt(wave, m.id, `${component}_height`, time, "ft");
      if (height !== null && combined !== null && height > combined + 0.3)
        flags.push(
          `${m.name}: a component exceeds combined seas; check the source.`,
        );
    }
  }
  const winds = WIND_MODELS.map((m) =>
    valueAt(wind, m.id, "wind_speed_10m", time, "kn"),
  );
  const waves = WAVE_MODELS.map((m) =>
    valueAt(wave, m.id, "wave_height", time, "ft"),
  );
  if (winds.every(Number.isFinite) && Math.abs(winds[0] - winds[1]) > 4)
    flags.push("Wind models differ by more than 4 kt.");
  if (waves.every(Number.isFinite) && Math.abs(waves[0] - waves[1]) > 1)
    flags.push("Wave models differ by more than 1 ft.");
  return [...new Set(flags)];
}
export async function fetchJSON(url) {
  const controller = new AbortController(),
    timer = setTimeout(() => controller.abort(), 20000);
  try {
    const r = await fetch(url, { signal: controller.signal });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const body = await r.json();
    if (body?.error) throw new Error(String(body.reason || "Provider error"));
    return body;
  } finally {
    clearTimeout(timer);
  }
}
