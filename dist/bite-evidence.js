import { esc } from "./marine-charts.js?v=5.4";
import { distanceNm } from "./marine-data.js?v=5.4";

export const FEED_URL =
  "https://raw.githubusercontent.com/Grahammmm/skippercast/data/latest.json";
const HOUR = 3600000;
const names = {
  lingcod: "Lingcod",
  rockfish: "Rockfish",
  halibut: "California halibut",
  salmon: "Salmon",
  albacore: "Albacore",
  bluefin: "Bluefin",
  dungeness: "Dungeness crab",
};
const dateFormat = new Intl.DateTimeFormat("en-CA", {
  timeZone: "America/Los_Angeles",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
});
const when = (s) =>
  s && Number.isFinite(Date.parse(s))
    ? new Date(s).toLocaleString("en-US", {
        timeZone: "America/Los_Angeles",
        month: "short",
        day: "numeric",
        hour: "numeric",
        minute: "2-digit",
      }) + " PT"
    : "Time unavailable";
const day = (s) =>
  /^\d{4}-\d{2}-\d{2}$/.test(s || "")
    ? new Date(s + "T12:00:00Z").toLocaleDateString("en-US", {
        timeZone: "UTC",
        month: "short",
        day: "numeric",
      })
    : "Unknown date";
const safeURL = (s) => {
  try {
    const u = new URL(s);
    return u.protocol === "https:" ? u.href : "#";
  } catch {
    return "#";
  }
};
const age = (s, now) =>
  Number.isFinite(Date.parse(s)) ? (now - Date.parse(s)) / HOUR : Infinity;

export function validFeed(data) {
  return (
    data?.schema_version === 1 &&
    Number.isFinite(Date.parse(data.generated_at)) &&
    data.sources &&
    !Array.isArray(data.sources) &&
    Array.isArray(data.reports) &&
    data.health &&
    data.catch_probability === null &&
    data.bite_score === null
  );
}

let feedPromise = null,
  feedRequestedAt = 0;
export function loadDailyEvidence(force = false) {
  if (feedPromise && !force && Date.now() - feedRequestedAt < HOUR)
    return feedPromise;
  feedRequestedAt = Date.now();
  feedPromise = (async () => {
    for (const url of [FEED_URL, "data/daily-evidence.json"]) {
      try {
        const r = await fetch(url, {
          signal: AbortSignal.timeout(15000),
          cache: "no-cache",
        });
        if (!r.ok) throw new Error("Feed request failed");
        const data = await r.json();
        if (!validFeed(data)) throw new Error("Feed schema changed");
        return { data, fallback: url !== FEED_URL };
      } catch {
        /* The bundled fallback keeps its own timestamps. */
      }
    }
    throw new Error("Daily fishing evidence unavailable");
  })();
  return feedPromise;
}

export function reportEvidence(
  data,
  species,
  now = Date.now(),
  groundId = null,
) {
  const today = dateFormat.format(new Date(now));
  const first = new Date(Date.parse(today + "T12:00:00Z") - 7 * 24 * HOUR)
    .toISOString()
    .slice(0, 10);
  const fresh =
    validFeed(data) &&
    age(data.generated_at, now) >= -1 &&
    age(data.generated_at, now) <= 36;
  const reports = (data?.reports || []).filter(
    (r) =>
      r.date >= first &&
      r.date < today &&
      (!groundId || r.ground_id === groundId) &&
      r.catches?.some((c) => c.species === species && c.count > 0),
  );
  const boats = new Set(reports.map((r) => r.boat)).size;
  const days = new Set(reports.map((r) => r.date)).size;
  const pages = Array.from({ length: 7 }, (_, i) =>
    new Date(Date.parse(today + "T12:00:00Z") - (i + 1) * 24 * HOUR)
      .toISOString()
      .slice(0, 10),
  );
  const coverage = pages.filter((d) => {
    const s = data?.sources?.["catches-" + d];
    return (
      s?.status === "ok" &&
      age(s.data_retrieved_at, now) <= 36 &&
      age(s.data_retrieved_at, now) >= -1
    );
  }).length;
  let confidence = "Insufficient";
  if (reports.length) confidence = "Low";
  if (fresh && coverage === 7 && reports.length >= 5 && boats >= 2 && days >= 3)
    confidence = "Moderate";
  const reason = !fresh
    ? "The daily feed is stale or unavailable; retained reports are historical context."
    : coverage < 7
      ? `${coverage}/7 recent report pages verified; gaps limit confidence.`
      : !reports.length
        ? "No recent reports of this species in the collected sample. This does not establish absence."
        : confidence === "Moderate"
          ? "Repeated reports from several boats support recent activity. Exact catches at your spot remain unverified."
          : "Recent reports exist, but there are too few boats or dates for stronger confidence.";
  return {
    confidence,
    fresh,
    reports,
    boats,
    days,
    coverage,
    start: first,
    end: pages[0],
    reason,
    named: reports.filter((r) => r.ground_id).length,
    catch_probability: null,
    bite_score: null,
  };
}

export function nearestGrid(source, point, kind, now = Date.now()) {
  const data = source?.data;
  if (!data?.samples?.length) return null;
  // Find the nearest actual grid cell BEFORE checking for missing values. Never
  // jump across a cloud/reception gap to imply coverage at the selected point.
  const sample = data.samples.reduce(
    (best, s) =>
      !best || distanceNm(s, point) < distanceNm(best, point) ? s : best,
    null,
  );
  const distance = distanceNm(sample, point);
  const limit = kind === "currents" ? 4 : 3;
  const keys =
    kind === "sst"
      ? ["analysed_sst"]
      : kind === "chlorophyll"
        ? ["chlorophyll"]
        : ["water_u", "water_v"];
  const usable =
    distance <= limit && keys.every((k) => Number.isFinite(sample[k]));
  const sampleAge = age(sample.time, now);
  const fresh =
    source.status === "ok" &&
    sampleAge >= -1 &&
    sampleAge <= source.max_age_hours;
  return { sample, distance, usable, fresh };
}

function gridHTML(source, point, kind) {
  const result = nearestGrid(source, point, kind);
  const titles = {
    sst: "Surface temperature",
    chlorophyll: "Chlorophyll",
    currents: "Surface current",
  };
  const s = result?.sample;
  let value = "Unavailable";
  if (result?.usable) {
    if (kind === "sst")
      value = `${((s.analysed_sst * 9) / 5 + 32).toFixed(1)}°F`;
    if (kind === "chlorophyll") value = `${s.chlorophyll.toFixed(2)} mg/m³`;
    if (kind === "currents")
      value = `${(Math.hypot(s.water_u, s.water_v) * 1.943844).toFixed(2)} kt toward ${Math.round(((Math.atan2(s.water_u, s.water_v) * 180) / Math.PI + 360) % 360)}°`;
  }
  const state = result?.usable
    ? result.fresh
      ? "Dated context"
      : "Stale context"
    : "No usable local sample";
  return `<div class="evidence-signal"><span>${titles[kind]}</span><strong>${value}</strong><small>${state}${s ? ` · ${when(s.time)}` : ""}</small>${result?.usable ? `<small>Grid ${result.distance.toFixed(1)} nm from selection${kind === "sst" && Number.isFinite(s.analysis_error) ? ` · analysis error SD ${(s.analysis_error * 1.8).toFixed(1)}°F` : ""}</small>` : ""}</div>`;
}

const interpretations = {
  lingcod:
    "For lingcod, rocky habitat and controlled bottom contact remain the practical starting points. Surface temperature and radar current do not measure conditions at a 200-foot reef.",
  rockfish:
    "Recent rockfish totals combine several species. Match the habitat and sounder marks, identify your catch, and check species-specific limits. Larger reported catches do not rank individual reefs.",
  halibut:
    "For halibut, soft-bottom habitat and local bait matter. These reports do not measure bait, water clarity, bottom temperature, or a reliable optimum drift speed.",
  salmon:
    "For salmon, use legal-season reports and forage observations. A catch landed at Morro Bay does not locate a school; surface conditions do not establish the fishing depth.",
  albacore:
    "For albacore, temperature boundaries, ocean color and currents help compare water masses. Chlorophyll indicates surface phytoplankton, not a measured bait school or guaranteed feeding activity.",
  bluefin:
    "For bluefin, prioritize recent fish and forage observations. Ocean color and temperature are context; no single warm-water threshold or regional report locates a school.",
  dungeness:
    "For Dungeness, these sportfishing reports provide little effort coverage. Habitat, legal season and gear rules matter; no catch-probability inference is made from missing crab reports.",
};

function buoyHTML(data) {
  return ["buoy-46215", "buoy-46028"]
    .map((id) => {
      const source = data?.sources?.[id];
      const row = source?.data?.observations?.find(
        (r) => Number.isFinite(r.WVHT) && Number.isFinite(r.DPD),
      );
      const label =
        id === "buoy-46215"
          ? "Diablo Canyon · 46215"
          : "Cape San Martin · 46028";
      if (!row) return `<p>${label}: wave observation unavailable.</p>`;
      const fresh =
        source.status === "ok" &&
        age(row.time, Date.now()) >= -1 &&
        age(row.time, Date.now()) <= 6;
      return `<p><strong>${label}: ${(row.WVHT * 3.28084).toFixed(1)} ft at ${row.DPD.toFixed(0)} s</strong>${Number.isFinite(row.MWD) ? ` · mean direction from ${row.MWD}° true` : ""}<br><small>${fresh ? "Dated observation" : "Stale observation"} · ${when(row.time)}. Dominant wave period; this is regional buoy water, not the selected reef. <a href="${esc(safeURL(source.url))}" target="_blank" rel="noopener">Source ↗</a></small></p>`;
    })
    .join("");
}

export function evidenceHTML(
  data,
  species,
  point,
  { open = false, fallback = false } = {},
) {
  const e = reportEvidence(data, species);
  const reports = e.reports.slice(0, 5);
  const allSources = Object.values(data?.sources || {});
  const mainSources = allSources.filter((s) => s.kind !== "charter-reports");
  const issues = allSources.filter((s) => s.status !== "ok").length;
  return `<details class="bite-card" ${open ? "open" : ""}><summary><span><small>RECENT FISHING EVIDENCE</small><strong>${esc(names[species] || species)} · ${e.reports.length ? e.reports.length + (e.reports.length === 1 ? " reported trip" : " reported trips") : "Reports limited"}</strong></span><b class="evidence-confidence ${e.confidence.toLowerCase()}">${e.confidence}</b></summary><div class="bite-body"><p>${esc(e.reason)}</p><p class="small">${day(e.start)}–${day(e.end)} · ${e.boats} boat${e.boats === 1 ? "" : "s"} · ${e.days} reporting date${e.days === 1 ? "" : "s"} · Morro Bay / Avila landings. Confidence describes the <strong>evidence for recent activity</strong>, not your chance of a bite or a seven-day prediction.</p>${
    reports.length
      ? `<div class="evidence-reports">${reports
          .map(
            (r) =>
              `<a href="${esc(safeURL(r.source_url))}" target="_blank" rel="noopener"><span>${day(r.date)} · ${esc(r.boat)}</span><strong>${r.catches
                .filter((c) => c.species === species && c.count > 0)
                .map(
                  (c) =>
                    `${c.count} ${esc(c.label)}${c.disposition === "released" ? " released" : " reported"}`,
                )
                .join(
                  " · ",
                )}</strong><small>${r.ground ? "Reported ground: " + esc(r.ground) : esc(r.port) + " landing · fishing location unreported"}${r.anglers === null ? "" : " · " + r.anglers + " anglers"} ↗</small></a>`,
          )
          .join("")}</div>`
      : ""
  }<p>${esc(interpretations[species] || "")}</p><h3>Ocean context · ${esc(point.name || point.label || "Selected location")}</h3><div class="evidence-signals">${["sst", "chlorophyll", "currents"].map((k) => gridHTML(data?.sources?.[k], point, k)).join("")}</div><p class="small">Latest available dated samples. MUR is an interpolated surface analysis; chlorophyll can have cloud gaps. HF radar represents roughly the upper 2.4 m, not bottom current or a seven-day drift forecast. The hourly weather and tide views refresh separately.</p><details class="evidence-method"><summary>Observed seas · daily buoy sample</summary>${buoyHTML(data)}<p class="small">Collected once daily. Recheck live buoy observations before departure; a calm observation does not verify a future forecast.</p></details><details class="evidence-method"><summary>Why there is no bite-probability score yet</summary><p>We need successful <em>and zero-catch</em> trips with species targeted, time fishing, anglers, gear, depth and location, plus bait and sonar observations. Charter totals lack that denominator and can reflect limits or selective reporting. A model must then be tested on future trips and different locations before publishing a calibrated probability.</p><p>Moderate evidence requires a fresh daily feed, all seven recent report pages checked, and at least five positive trips from two boats across three dates. Smaller samples are Low; no reports are Insufficient. This transparent rule is not a statistical confidence interval. No High category or numeric bite score is currently earned.</p><a href="https://github.com/Grahammmm/skippercast/blob/main/docs/bite-evidence.md" target="_blank" rel="noopener">Research, product comparison & data method ↗</a></details><details class="evidence-health"><summary>Daily data · ${e.fresh && !fallback ? "updated" : fallback ? "saved snapshot" : "stale"}${issues ? " · " + issues + (issues === 1 ? " source issue" : " source issues") : ""}</summary><p class="small">Collected ${when(data?.generated_at)}. ${fallback ? "Live feed could not load; this saved edition keeps its original dates. " : ""}Cloud refresh scheduled daily at 4:17 a.m. Pacific; delays and failures stay visible. The job does not depend on this Mac.</p><ul>${mainSources.map((s) => `<li><a href="${esc(safeURL(s.url))}" target="_blank" rel="noopener">${esc(s.name)}</a> · <strong>${esc(s.status)}</strong><small>${s.data?.sample_at ? "Source time " + when(s.data.sample_at) + ". " : ""}Checked ${when(s.checked_at)}.${s.changed_since_previous ? " Page changed; rules need review." : ""}${s.issue ? " " + esc(s.issue) : ""}</small></li>`).join("")}</ul><p class="small">A regulation-page check detects access and changes, not permission to fish. Harbor information is not live entrance clearance. NOAA, NASA JPL/GSFC, IOOS/HFRNet and Open-Meteo retain their data credits; landing facts link to SoCalFishReports.</p><a href="https://github.com/Grahammmm/skippercast/actions/workflows/daily-data.yml" target="_blank" rel="noopener">Daily job status ↗</a></details></div></details>`;
}

export function initBiteEvidence(host) {
  let data = null,
    fallback = false,
    species = "lingcod",
    point = { name: "Estero Bay", latitude: 35.36, longitude: -120.94 };
  let key = "";
  function render(force = false) {
    const next = `${species}:${point.latitude}:${point.longitude}:${Math.floor(Date.now() / HOUR)}`;
    if (!force && next === key) return;
    key = next;
    const open = host.querySelector(".bite-card")?.open;
    host.innerHTML = data
      ? evidenceHTML(data, species, point, { open, fallback })
      : '<p class="small">Daily fishing evidence is loading…</p>';
  }
  async function load(force = false) {
    try {
      const result = await loadDailyEvidence(force);
      data = result.data;
      fallback = result.fallback;
      render(true);
      return;
    } catch {
      /* Both public feed and dated fallback failed. */
    }
    host.innerHTML =
      '<div class="bite-card"><p>Daily fishing evidence is unavailable. No bite score is assumed. <button id="retry-bite-evidence">Retry</button></p></div>';
    host.querySelector("button").addEventListener("click", () => load(true));
  }
  render(true);
  load();
  setInterval(() => {
    if (document.visibilityState === "visible") load();
  }, HOUR);
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") load();
  });
  return {
    select(id, location) {
      species = id;
      point = location;
      render();
    },
    refresh: () => load(true),
  };
}
