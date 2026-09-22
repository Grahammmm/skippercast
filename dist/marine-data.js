import { getRegion, localContext } from "./region.js?v=8.10";
// UTC, unit-checked hourly samples. No gap filling, zero substitution, or extrapolation.
import { fetchJSON, WIND_MODELS, WAVE_MODELS } from "./forecast.js?v=8.10";

export const HOUR = 3600;
export const POINTS = getRegion().forecast_points;
export const POINT_SIGNATURE=JSON.stringify(POINTS.map(p=>[p.id,p.latitude,p.longitude]));
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
  const combined=component('wave');
  if(combined.period!==null && combined.period<=0){combined.height=null;combined.period=null;combined.from=null;}
  return {
    wind: at(windId, "wind_speed_10m", "kn"),
    gust: at(windId, "wind_gusts_10m", "kn"),
    windFrom: at(windId, "wind_direction_10m", "°"),
    visibility: at(windId, "visibility", "m"),
    rain: at(windId, "precipitation", "mm"),
    air: at(windId, "temperature_2m", "°F"),
    weatherCode: at(windId, "weather_code", "wmo code"),
    sea: combined,
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
export function tideURL(now = Date.now(), interval = "6", station = getRegion().stations.tide) {
  const date = (n) =>
    new Date(n).toISOString().slice(0, 10).replaceAll("-", "");
  return (
    "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter?" +
    new URLSearchParams({
      product: "predictions",
      application: "SkipperCast",
      station,
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
export async function loadMarine(previous = null) {
  // Cache complete/partial responses only in this tab. No private location or account data.
  const models = {};
  let shared=null;
  try {
    const response=await fetch(`/api/forecast?region=${encodeURIComponent(getRegion().id)}`,{signal:AbortSignal.timeout(5000)});
    if(response.ok){const candidate=await response.json();if(candidate.region_id===getRegion().id&&JSON.stringify(candidate.requested_points)===POINT_SIGNATURE&&Number.isFinite(candidate.retrieved)&&Date.now()-candidate.retrieved<3*3600000)shared=candidate;}
  }catch{ /* Direct providers remain a fallback when the shared feed is unavailable. */ }
  await Promise.allSettled(
    MODELS.map(async (m) => {
      const cached=shared?.models?.[m.id];
      if(cached&&!cached.error&&cached.meta&&cached.data?.length===POINTS.length){models[m.id]={...cached,retrieved:cached.retrieved||shared.retrieved};return;}
      const [forecast, metadata] = await Promise.all([
        attempt(modelURL(m)),
        attempt(m.meta),
      ]);
      // Retry transient failures once; never retry or fabricate a missing forecast hour.
      if(forecast.error) Object.assign(forecast,await attempt(modelURL(m)));
      if(metadata.error) Object.assign(metadata,await attempt(m.meta));
      const prior=previous?.pointSignature===POINT_SIGNATURE?previous.models?.[m.id]:null;
      const priorAt=prior?.retrieved||previous?.retrieved;
      if((!forecast.value || !metadata.value) && prior?.data?.length===POINTS.length && Date.now()-priorAt<3*3600000){
        models[m.id]={...prior,retrieved:priorAt,refreshError:forecast.error||metadata.error};return;
      }
      const data = forecast.value;
      models[m.id] = {
        data: Array.isArray(data) ? data : data ? [data] : [],
        meta: metadata.value,
        retrieved: Date.now(),
        error: forecast.value?undefined:forecast.error,
        metaError: metadata.value?undefined:metadata.error,
      };
    }),
  );
  const contexts = {}, requests = new Map();
  const once=url=>{if(!requests.has(url))requests.set(url,attempt(url));return requests.get(url);};
  const bindings=getRegion().contexts ? Object.entries(getRegion().contexts) : [['default',localContext()]];
  await Promise.all(bindings.map(async([id,ctx])=>{
    const [tides,extremes,alerts,outerAlerts,water]=await Promise.all([
      once(tideURL(Date.now(),'6',ctx.stations.tide)),once(tideURL(Date.now(),'hilo',ctx.stations.tide)),
      once(`https://api.weather.gov/alerts/active?zone=${ctx.marine_zones.coastal}`),
      once(`https://api.weather.gov/alerts/active?zone=${ctx.marine_zones.offshore}`),
      once(`https://api.tidesandcurrents.noaa.gov/api/prod/datagetter?product=water_level&application=SkipperCast&station=${ctx.stations.tide}&date=latest&datum=MLLW&time_zone=gmt&units=english&format=json`),
    ]);
    const parse=r=>r.value?.type==='FeatureCollection' && Array.isArray(r.value.features) ? r.value.features.map(f=>({title:f.properties.headline||f.properties.event,starts:Date.parse(f.properties.onset||f.properties.effective)/1000,ends:Date.parse(f.properties.ends||f.properties.expires)/1000,url:f.id})) : null;
    contexts[id]={tides:tidePoints(tides.value),extremes:tidePoints(extremes.value),tideError:tides.error,alerts:{coastal:parse(alerts),offshore:parse(outerAlerts)},alertError:alerts.error||outerAlerts.error,water:water.value?.data?.[0],waterError:water.error,stations:ctx.stations};
  }));
  const primary=contexts[localContext(getRegion().default_forecast_point).id] || Object.values(contexts)[0];
  return {models,...primary,contexts,pointSignature:POINT_SIGNATURE,retrieved:Date.now(),sharedForecastAt:shared?.retrieved||null};
}
