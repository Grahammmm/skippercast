import { futureDates, pacificEpoch } from "./forecast.js?v=5.4";
import {
  readConditions,
  comfort,
  angleBetween,
  HOUR,
  POINTS,
} from "./marine-data.js?v=5.4";
import { esc, local, num } from "./marine-charts.js?v=5.4";
const MODELS = [
  "gfs_global",
  "ecmwf_ifs025",
  "ncep_gfswave025",
  "ecmwf_wam025",
];
const clamp = (n) => Math.round(Math.max(0, Math.min(10, n)) * 10) / 10;
export function hourScores(c, other, species) {
  const wind = Math.max(c.wind, other.wind),
    gust = Math.max(c.gust, other.gust),
    sea = Math.max(c.sea.height, other.sea.height);
  const crossing =
    c.secondary.height >= 1 &&
    angleBetween(c.swell.from, c.secondary.from) >= 60
      ? 0.7
      : 0;
  const short = c.chop.height >= 0.5 && c.chop.period <= 6 ? 0.8 : 0;
  const comfortScore = clamp(
    10 -
      Math.max(0, wind - 4) * 0.22 -
      Math.max(0, gust - 7) * 0.1 -
      Math.max(0, sea - 1.5) * 0.7 -
      Math.max(0, c.chop.height - 0.4) * 0.9 -
      crossing -
      short,
  );
  const bottom = ["lingcod", "rockfish", "halibut", "dungeness"].includes(
    species,
  );
  const controlScore = clamp(
    10 -
      Math.max(0, wind - 4) * (bottom ? 0.32 : 0.22) -
      Math.max(0, gust - 8) * 0.08 -
      Math.max(0, c.chop.height - 0.4) * (bottom ? 1.1 : 0.8) -
      Math.max(0, sea - 2) * 0.45 -
      crossing -
      short,
  );
  return {
    comfort: comfortScore,
    control: controlScore,
    conditions: Math.min(comfortScore, controlScore),
    bite: null,
    overall: null,
  };
}
export function rankMornings(
  bundle,
  point,
  species,
  now = Date.now(),
  horizon = now / 1000 + 168 * HOUR,
) {
  return futureDates(new Date(now)).map((date, i) => {
    const times = Array.from({ length: 7 }, (_, h) =>
      pacificEpoch(`${date}T${String(h + 7).padStart(2, "0")}:00`),
    );
    const row = {
      date,
      time: times[1],
      point,
      provisional: i >= 3,
      confidence: "Low",
      conditions: null,
      comfort: null,
      control: null,
      bite: null,
      overall: null,
      reasons: [],
    };
    if (!bundle || now - bundle.retrieved > 3 * 3600000) {
      row.reasons.push("Fresh forecasts unavailable");
      return row;
    }
    if (times.at(-1) > horizon) {
      row.reasons.push("Full morning extends beyond the slider window");
      return row;
    }
    if (
      MODELS.some(
        (id) =>
          !Number.isFinite(
            bundle.models[id]?.meta?.last_run_initialisation_time,
          ) ||
          now / 1000 - bundle.models[id].meta.last_run_initialisation_time >
            36 * HOUR,
      )
    ) {
      row.reasons.push("Model-run freshness cannot be verified");
      return row;
    }
    const hours = [];
    let critical = false,
      disagreement = false;
    for (const t of times) {
      const c = readConditions(bundle, point, t, "gfs"),
        other = readConditions(bundle, point, t, "ecmwf");
      const alerts =
        bundle.alerts?.[POINTS[point].offshore ? "offshore" : "coastal"];
      const active = Array.isArray(alerts)
        ? alerts
            .filter(
              (a) =>
                (!Number.isFinite(a.starts) || a.starts <= t) &&
                (!Number.isFinite(a.ends) || a.ends >= t),
            )
            .map((a) => a.title)
        : null;
      const state = comfort(c, other, active);
      if (
        !Number.isFinite(c.secondary.height) ||
        [c.chop, c.secondary].some(
          (part) =>
            part.height > 0 && ![part.period, part.from].every(Number.isFinite),
        )
      ) {
        row.reasons.push("Swell or chop components incomplete");
        critical = true;
        continue;
      }
      if (state.level === "unknown" || state.level === "hazard") {
        row.reasons.push(...state.flags);
        const onlyDisagreement =
          state.level === "unknown" &&
          state.flags.every(
            (f) =>
              f === "Wind models differ by >4 kt" ||
              f === "Wave models differ by >1 ft",
          );
        if (onlyDisagreement) {
          disagreement = true;
          hours.push(hourScores(c, other, species));
        } else critical = true;
      } else hours.push(hourScores(c, other, species));
    }
    row.reasons = [...new Set(row.reasons)];
    if (critical || hours.length !== 7) return row;
    for (const key of ["comfort", "control", "conditions"])
      row[key] = Math.min(...hours.map((h) => h[key]));
    row.confidence = disagreement ? "Low" : "Moderate";
    if (disagreement) row.conditions = Math.min(row.conditions, 7.9);
    else
      row.reasons = [
        "Lowest hourly comfort / fishing-control score, 7 a.m.–1 p.m.",
      ];
    return row;
  });
}
export function renderOutlook(rows, point) {
  const valid = rows
    .filter((r) => Number.isFinite(r.conditions))
    .sort((a, b) => b.conditions - a.conditions);
  const best = valid[0],
    qualifying = valid.filter((r) => r.conditions >= 8);
  const banner = document.getElementById("best-day-banner");
  banner.classList.toggle("qualifying", !!qualifying.length);
  banner.innerHTML = best
    ? `<span>${best.confidence === "Low" ? "Tentative best" : "Best conditions"} · ${local(best.time, { weekday: "short" })}${best.confidence === "Low" ? " · low confidence" : best.provisional ? " · provisional" : ""}</span><strong>${num(best.conditions)}/10 <small>· bite unscored</small></strong>`
    : "<span>7-day morning outlook</span><strong>Not enough data</strong>";
  banner.dataset.hour = best?.time || "";
  const host = document.getElementById("morning-outlook");
  host.innerHTML = `<details class="morning-summary"><summary>${best ? `${best.confidence === "Low" ? "Tentative best" : "Best"}: ${local(best.time, { weekday: "long" })} · ${num(best.conditions)}/10 conditions` : "Seven-day outlook · ratings unavailable"}<span>${qualifying.length ? `${qualifying.length} morning${qualifying.length === 1 ? "" : "s"} at 8+` : "No verified 8+ conditions yet"}</span></summary><p class="small">${esc(POINTS[point].name)} · 7 a.m.–1 p.m. Pacific. This ranks modeled comfort and gear control across the entire window. Bite potential and an overall bite-plus-comfort rating are unavailable. It is not a routed trip or entrance clearance.</p><div class="morning-days">${rows.map((r) => `<button class="morning-day ${r.conditions >= 8 ? "good" : ""}" data-morning="${r.time}"><strong>${local(r.time, { weekday: "short", month: "numeric", day: "numeric" })}</strong><b>${r.conditions === null ? "Unrated" : num(r.conditions) + "/10"}</b><span>${r.confidence}${r.provisional ? " · provisional" : ""} · ${r.conditions === null ? esc(r.reasons[0]) : "comfort " + num(r.comfort) + " / control " + num(r.control)}</span></button>`).join("")}</div><details><summary>How the rating works</summary><p class="small">A disclosed planning heuristic: take the lower of comfort and gear-control scores, then the lowest hourly result from 7 a.m. through 1 p.m. Use the rougher model’s wind, gusts and combined seas, plus GFS chop and crossing swells. Missing inputs, stale runs, fog, storms or active marine alerts prevent a rating. With material model disagreement only, use the rougher forecast, label Low confidence and cap the conditions rating at 7.9. Surface current does not estimate bottom drift. Recent charter reports and ocean observations appear in the fishing-evidence panel. Exact fish presence, forage and pressure remain unknown; the evidence is not converted into a bite-probability score.</p><a href="species-research.html#morning-ratings">Full score formula ↗</a></details></details>`;
  return best;
}
