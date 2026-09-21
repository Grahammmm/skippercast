// UTC, unit-checked hourly samples. No gap filling, zero substitution, or extrapolation.
import { fetchJSON, WIND_MODELS, WAVE_MODELS } from "./forecast.js?v=4.1";

export const HOUR = 3600;
export const POINTS = [
  { id: "north", name: "Point Estero", latitude: 35.45, longitude: -121.02 },
  { id: "central", name: "Estero Bay", latitude: 35.36, longitude: -120.94 },
  { id: "south", name: "Point Buchon", latitude: 35.24, longitude: -120.94 },
  { id: "avila", name: "Off Avila", latitude: 35.1, longitude: -120.82 },
  ...[35.05, 35.3, 35.55].flatMap((latitude, row) =>
    [-121.25, -121.5, -121.75].map((longitude, col) => ({
      id: `offshore-${row}-${col}`,
      name: `Offshore ${["south", "central", "north"][row]} · ${["inner", "middle", "outer"][col]}`,
      latitude,
      longitude,
      offshore: true,
    })),
  ),
];
export const MODELS = [
  ...WIND_MODELS.map((m) => ({
    ...m,
    kind: "wind",
    resolution: m.id === "gfs_global" ? "~13 km" : "~25 km",
  })),
  ...WAVE_MODELS.map((m) => ({ ...m, kind: "wave", resolution: "~25 km" })),
  {
    id: "meteofrance_currents",
    name: "Météo-France / Copernicus ocean",
    kind: "ocean",
    resolution: "~8 km",
    meta: "https://marine-api.open-meteo.com/data/meteofrance_currents/static/meta.json",
  },
];
const windVars = [
  "wind_speed_10m",
  "wind_gusts_10m",
  "wind_direction_10m",
  "visibility",
  "precipitation",
  "temperature_2m",
  "cloud_cover",
  "weather_code",
];
const waveVars = [
  "wave",
  "wind_wave",
  "swell_wave",
  "secondary_swell_wave",
].flatMap((k) => ["height", "period", "direction"].map((v) => `${k}_${v}`));
export function modelURL(model, points = POINTS) {
  const q = new URLSearchParams({
    latitude: points.map((p) => p.latitude).join(","),
    longitude: points.map((p) => p.longitude).join(","),
    forecast_days: 8,
    timezone: "UTC",
    timeformat: "unixtime",
    cell_selection: "sea",
    models: model.id,
  });
  const marine = model.kind !== "wind";
  q.set(
    "hourly",
    (model.kind === "wind"
      ? windVars
      : model.kind === "wave"
        ? waveVars
        : [
            "sea_surface_temperature",
            "ocean_current_velocity",
            "ocean_current_direction",
          ]
    ).join(","),
  );
  if (marine) q.set("length_unit", "imperial");
  else q.set("wind_speed_unit", "kn");
  q.set("temperature_unit", "fahrenheit");
  return `https://${marine ? "marine-api" : "api"}.open-meteo.com/v1/${marine ? "marine" : "forecast"}?${q}`;
}
export function sample(data, variable, epoch, unit, meta) {
  const h = data?.hourly,
    times = h?.time,
    values = h?.[variable];
  if (
    data?.hourly_units?.time !== "unixtime" ||
    data?.utc_offset_seconds !== 0 ||
    data?.hourly_units?.[variable] !== unit ||
    !Array.isArray(times) ||
    !Array.isArray(values) ||
    values.length !== times.length
  )
    return null;
  if (meta?.data_end_time && epoch > meta.data_end_time) return null;
  const i = times.indexOf(epoch);
  if (i < 0 || times.indexOf(epoch, i + 1) !== -1) return null;
  const n = values[i];
  if (typeof n !== "number" || !Number.isFinite(n)) return null;
  if (
    !["temperature_2m", "sea_surface_temperature"].includes(variable) &&
    n < 0
  )
    return null;
  if (variable.endsWith("direction") && n > 360) return null;
  return n;
}
export function timeline(now = Date.now()) {
  const start = Math.floor(now / 1000 / HOUR) * HOUR;
  return Array.from({ length: 169 }, (_, i) => start + i * HOUR);
}
export function directionTo(from) {
  return Number.isFinite(from) ? (from + 180) % 360 : null;
}
export function angleBetween(a, b) {
  return Number.isFinite(a) && Number.isFinite(b)
    ? Math.abs(((a - b + 540) % 360) - 180)
    : null;
}
export function distanceNm(a, b) {
  const r = Math.PI / 180,
    dlat = (b.latitude - a.latitude) * r,
    dlon = (b.longitude - a.longitude) * r;
  const q =
    Math.sin(dlat / 2) ** 2 +
    Math.cos(a.latitude * r) *
      Math.cos(b.latitude * r) *
      Math.sin(dlon / 2) ** 2;
  return 3440.065 * 2 * Math.atan2(Math.sqrt(q), Math.sqrt(1 - q));
}
export function readConditions(bundle, point, epoch, family = "gfs") {
  const windId = family === "gfs" ? "gfs_global" : "ecmwf_ifs025",
    waveId = family === "gfs" ? "ncep_gfswave025" : "ecmwf_wam025";
  const at = (id, key, unit) =>
    sample(
      bundle.models[id]?.data?.[point],
      key,
      epoch,
      unit,
      bundle.models[id]?.meta,
    );
  const component = (k) => ({
    height: at(waveId, `${k}_height`, "ft"),
    period: at(waveId, `${k}_period`, "s"),
    from: at(waveId, `${k}_direction`, "°"),
  });
  return {
    wind: at(windId, "wind_speed_10m", "kn"),
    gust: at(windId, "wind_gusts_10m", "kn"),
    windFrom: at(windId, "wind_direction_10m", "°"),
    visibility: at(windId, "visibility", "m"),
    rain: at(windId, "precipitation", "mm"),
    air: at(windId, "temperature_2m", "°F"),
    weatherCode: at(windId, "weather_code", "wmo code"),
    sea: component("wave"),
    chop: component("wind_wave"),
    swell: component("swell_wave"),
    secondary: component("secondary_swell_wave"),
    sst: at("meteofrance_currents", "sea_surface_temperature", "°F"),
    current: ((n) => (n === null ? null : n / 1.852))(
      at("meteofrance_currents", "ocean_current_velocity", "km/h"),
    ),
    currentTo: at("meteofrance_currents", "ocean_current_direction", "°"),
  };
}
export function comfort(c, other, advisories = null) {
  const flags = [];
  if (
    ![
      c.wind,
      c.gust,
      c.windFrom,
      c.sea.height,
      c.sea.period,
      c.sea.from,
      c.chop.height,
      c.swell.height,
      c.swell.period,
      c.swell.from,
      c.visibility,
      c.weatherCode,
    ].every(Number.isFinite)
  )
    flags.push("Critical wind, wave, or visibility data missing");
  if (c.gust !== null && c.wind !== null && c.gust < c.wind)
    flags.push("Gust below sustained wind: inconsistent source");
  for (const part of [c.chop, c.swell, c.secondary])
    if (
      part.height !== null &&
      c.sea.height !== null &&
      part.height > c.sea.height + 0.3
    )
      flags.push("Wave component exceeds combined seas");
  if (
    other &&
    c.wind !== null &&
    other.wind !== null &&
    Math.abs(c.wind - other.wind) > 4
  )
    flags.push("Wind models differ by >4 kt");
  if (
    other &&
    c.sea.height !== null &&
    other.sea.height !== null &&
    Math.abs(c.sea.height - other.sea.height) > 1
  )
    flags.push("Wave models differ by >1 ft");
  if (
    !other ||
    ![other.wind, other.gust, other.sea.height].every(Number.isFinite)
  )
    flags.push("Independent model comparison incomplete");
  if (
    other &&
    other.gust !== null &&
    other.wind !== null &&
    other.gust < other.wind
  )
    flags.push("Comparison model gust is below sustained wind");
  if (advisories === null) flags.push("Marine alert check unavailable");
  if (advisories?.length)
    return {
      level: "hazard",
      label: "Marine alert",
      flags: [...advisories, ...flags],
    };
  if (
    [c, other].some(
      (model) =>
        model &&
        ((Number.isFinite(model.visibility) && model.visibility < 1609) ||
          model.weatherCode >= 95),
    )
  )
    return {
      level: "hazard",
      label: "Visibility / weather hazard",
      flags: ["Fog or thunderstorm signal", ...flags],
    };
  if (flags.length)
    return { level: "unknown", label: "Uncertain", flags: [...new Set(flags)] };
  // Switching the displayed family must not hide the rougher forecast.
  const wind = Math.max(c.wind, other.wind),
    gust = Math.max(c.gust, other.gust),
    sea = Math.max(c.sea.height, other.sea.height),
    chop = Math.max(c.chop.height, other.chop.height ?? 0);
  const crossed =
    c.secondary.height >= 1 &&
    angleBetween(c.swell.from, c.secondary.from) >= 60;
  const short =
    c.chop.height >= 1 && c.chop.period !== null && c.chop.period <= 6;
  if (wind > 12 || gust > 18 || sea > 5 || chop > 2)
    return {
      level: "rough",
      label: "More motion",
      flags: ["Above the relaxed small-boat comfort screen"],
    };
  if (wind > 8 || gust > 12 || sea > 3 || chop > 1 || crossed || short)
    return {
      level: "mixed",
      label: "Mixed comfort",
      flags: [
        crossed
          ? "Crossing swells can increase roll"
          : short
            ? "Short-period chop can feel sharp"
            : "Above one or more preferred comfort targets",
      ],
    };
  return {
    level: "calmer",
    label: "Calmer signal",
    flags: [
      "Hourly model screen only; entrance, route, currents, and actual boat motion still matter",
    ],
  };
}
export function tideURL(now = Date.now(), interval = "6") {
  const date = (n) =>
    new Date(n).toISOString().slice(0, 10).replaceAll("-", "");
  return (
    "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter?" +
    new URLSearchParams({
      product: "predictions",
      application: "SkipperCast",
      station: "9412110",
      begin_date: date(now - 86400000),
      end_date: date(now + 8 * 86400000),
      datum: "MLLW",
      time_zone: "gmt",
      interval,
      units: "english",
      format: "json",
    })
  );
}
export function tidePoints(response) {
  return (response?.predictions || [])
    .filter(
      (p) =>
        typeof p.t === "string" && typeof p.v === "string" && p.v.trim() !== "",
    )
    .map((p) => ({
      time: Date.parse(p.t.replace(" ", "T") + "Z") / 1000,
      height: Number(p.v),
      type: p.type,
    }))
    .filter((p) => Number.isFinite(p.time) && Number.isFinite(p.height));
}
export function tideAt(points, time) {
  const b = points.findIndex((p) => p.time >= time);
  if (b < 0) return null;
  if (points[b].time === time) return points[b].height;
  if (b === 0 || points[b].time - points[b - 1].time > 360) return null;
  const a = points[b - 1],
    z = points[b];
  return (
    a.height + ((z.height - a.height) * (time - a.time)) / (z.time - a.time)
  );
}
async function attempt(url) {
  try {
    return { value: await fetchJSON(url) };
  } catch (e) {
    return { error: e.name === "AbortError" ? "Request timed out" : e.message };
  }
}
export async function loadMarine() {
  // Cache complete/partial responses only in this tab. No private location or account data.
  const models = {};
  await Promise.allSettled(
    MODELS.map(async (m) => {
      const [forecast, metadata] = await Promise.all([
        attempt(modelURL(m)),
        attempt(m.meta),
      ]);
      const data = forecast.value;
      models[m.id] = {
        data: Array.isArray(data) ? data : data ? [data] : [],
        meta: metadata.value,
        error: forecast.error,
        metaError: metadata.error,
      };
    }),
  );
  const [tides, extremes, alerts, outerAlerts, water] = await Promise.all([
    attempt(tideURL()),
    attempt(tideURL(Date.now(), "hilo")),
    attempt("https://api.weather.gov/alerts/active?zone=PZZ645"),
    attempt("https://api.weather.gov/alerts/active?zone=PZZ670"),
    attempt(
      "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter?product=water_level&application=SkipperCast&station=9412110&date=latest&datum=MLLW&time_zone=gmt&units=english&format=json",
    ),
  ]);
  const parseAlerts = (r) =>
    r.value?.features?.map((f) => ({
      title: f.properties.headline || f.properties.event,
      starts: Date.parse(f.properties.onset || f.properties.effective) / 1000,
      ends: Date.parse(f.properties.ends || f.properties.expires) / 1000,
      url: f.id,
    }));
  return {
    models,
    tides: tidePoints(tides.value),
    extremes: tidePoints(extremes.value),
    tideError: tides.error,
    alerts: {
      coastal: parseAlerts(alerts),
      offshore: parseAlerts(outerAlerts),
    },
    alertError: alerts.error || outerAlerts.error,
    water: water.value?.data?.[0],
    waterError: water.error,
    retrieved: Date.now(),
  };
}
