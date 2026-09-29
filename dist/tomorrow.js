// "Tomorrow" answer: for the next three days, go / marginal / no-go per
// two-hour window for the saved boat, the one factor that limits the day in
// words, model agreement as confidence, and the latest comfortable time to be
// back at the dock. It reuses the hourly ratings in morning-outlook.js; this is
// a disclosed planning heuristic, not a routed trip or a safety clearance.
import { rateHour } from "./morning-outlook.js";
import { readConditions, angleBetween, POINTS } from "./marine-data.js";
import { futureDates, pacificEpoch } from "./forecast.js";
import { activeBoatFactors } from "./boat-handling.js";
import { esc, local } from "./marine-charts.js";

export const FIRST_HOUR = 5;   // first window starts 5 a.m. Pacific
export const WINDOWS = 7;      // 5–7 a.m. … 5–7 p.m.
export const GO = 7;           // conditions score at or above this is "go"
export const NO_GO = 4;        // below this is "no-go"
const HOUR = 3600;
const COMPASS = ["N","NNE","NE","ENE","E","ESE","SE","SSE","S","SSW","SW","WSW","W","WNW","NW","NNW"];
const compass = (deg) => Number.isFinite(deg) ? COMPASS[Math.round(((deg % 360) + 360) % 360 / 22.5) % 16] : "";
const round = (n) => Math.round(n);
const ft = (n) => (Math.round(n * 2) / 2).toString();

/** "7 a.m.", "12 p.m." for an epoch in the region's time zone. */
export function clock(t) {
  return local(t, { hour: "numeric" }).replace(" AM", " a.m.").replace(" PM", " p.m.");
}

export function verdictFor(rating) {
  if (!rating || !Number.isFinite(rating.conditions)) return "unknown";
  if (rating.hazard || rating.conditions < NO_GO) return "no-go";
  return rating.conditions >= GO ? "go" : "marginal";
}
const RANK = { go: 0, marginal: 1, unknown: 2, "no-go": 3 };
const worse = (a, b) => (RANK[a] >= RANK[b] ? a : b);

/**
 * The single largest penalty in the hour, in the same units morning-outlook.js
 * charges them, so the words match what moved the score. Returns null when
 * nothing crosses the boat's thresholds.
 */
export function limitingFactor(bundle, point, time, boat = activeBoatFactors(), rating = null) {
  if (rating?.hazard) {
    const kind = activeAlerts(bundle, point, time)[0];
    return { kind: "hazard", penalty: Infinity, text: kind || "Marine advisory or low visibility" };
  }
  const g = readConditions(bundle, point, time, "gfs"), e = readConditions(bundle, point, time, "ecmwf");
  const S = boat.sea, W = boat.wind;
  const winds = [g, e].filter((m) => Number.isFinite(m.wind));
  if (!winds.length || ![g.sea.height, e.sea.height].some(Number.isFinite)) return { kind: "missing", penalty: Infinity, text: "forecast incomplete" };
  const rough = winds.reduce((a, b) => (b.wind > a.wind ? b : a));
  const gusts = [g, e].filter((m) => Number.isFinite(m.gust) && Number.isFinite(m.wind) && m.gust >= m.wind).map((m) => m.gust);
  const gust = gusts.length ? Math.max(...gusts) : null;
  const seaModel = [g, e].filter((m) => Number.isFinite(m.sea.height)).reduce((a, b) => (b.sea.height > a.sea.height ? b : a));
  const sea = seaModel.sea;
  const out = [
    { kind: "wind", penalty: Math.max(0, rough.wind - 4 * W) * 0.32 / W, text: `${compass(rough.windFrom)} ${round(rough.wind)} kt`.trim() },
    { kind: "gust", penalty: gust === null ? 0 : Math.max(0, gust - 7 * W) * 0.1 / W, text: `gusts ${round(gust)} kt` },
    { kind: "seas", penalty: Math.max(0, sea.height - 1.5 * S) * 0.7 / S, text: `${ft(sea.height)} ft seas${Number.isFinite(sea.period) ? ` at ${round(sea.period)} s` : ""}` },
  ];
  const chop = g.chop;
  if (Number.isFinite(chop.height)) {
    const short = chop.height >= 0.5 * S && Number.isFinite(chop.period) && chop.period <= boat.chopPeriod ? 0.8 : 0;
    out.push({ kind: "chop", penalty: Math.max(0, chop.height - 0.4 * S) * 1.1 / S + short, text: `${ft(chop.height)} ft wind chop${Number.isFinite(chop.period) ? ` at ${round(chop.period)} s` : ""}` });
  }
  if (Number.isFinite(g.secondary.height) && g.secondary.height >= 1 * S && angleBetween(g.swell.from, g.secondary.from) >= 60)
    out.push({ kind: "crossing", penalty: 0.7, text: `crossing swells (${compass(g.swell.from)} and ${compass(g.secondary.from)})` });
  const top = out.reduce((a, b) => (b.penalty > a.penalty ? b : a));
  return top.penalty > 0 ? top : null;
}
function activeAlerts(bundle, point, time) {
  const all = bundle?.alerts?.[POINTS[point]?.offshore ? "offshore" : "coastal"] || [];
  return all.filter((a) => (!Number.isFinite(a.starts) || a.starts <= time) && (!Number.isFinite(a.ends) || a.ends >= time)).map((a) => a.title).filter(Boolean);
}

/** Whether GFS and ECMWF agree for one hour (same tolerances as marine-data comfort flags). */
function agreement(bundle, point, time) {
  const g = readConditions(bundle, point, time, "gfs"), e = readConditions(bundle, point, time, "ecmwf");
  if (![g.wind, e.wind, g.sea.height, e.sea.height].every(Number.isFinite)) return null;
  return Math.abs(g.wind - e.wind) <= 4 && Math.abs(g.sea.height - e.sea.height) <= 1;
}
export function confidenceFrom(flags) {
  const known = flags.filter((f) => f !== null);
  if (!known.length || known.length < flags.length / 2) return { level: "Low", text: "one model only" };
  const share = known.filter(Boolean).length / known.length;
  if (share >= 0.9) return { level: "High", text: "GFS and ECMWF agree" };
  if (share >= 0.6) return { level: "Moderate", text: "models mostly agree" };
  return { level: "Low", text: "GFS and ECMWF disagree" };
}

/** Evaluate one local date. `rate` is injectable for tests. */
export function planDay(bundle, point, species, date, now = Date.now(), boat = activeBoatFactors(), rate = rateHour) {
  const start = pacificEpoch(`${date}T${String(FIRST_HOUR).padStart(2, "0")}:00`);
  const hours = Array.from({ length: WINDOWS * 2 }, (_, i) => start + i * HOUR);
  const rated = hours.map((t) => ({ t, rating: rate(bundle, point, species, t, now) }));
  for (const h of rated) h.verdict = verdictFor(h.rating);
  const windows = Array.from({ length: WINDOWS }, (_, w) => {
    const pair = rated.slice(w * 2, w * 2 + 2);
    const verdict = pair.map((h) => h.verdict).reduce(worse);
    const scores = pair.map((h) => h.rating?.conditions).filter(Number.isFinite);
    return { start: pair[0].t, end: pair[0].t + 2 * HOUR, verdict, conditions: scores.length === pair.length ? Math.min(...scores) : null };
  });
  // Latest comfortable back-at-dock: the end of the first unbroken run of "go" hours.
  const first = rated.findIndex((h) => h.verdict === "go");
  let backBy = null, departFrom = null;
  if (first >= 0) {
    let last = first;
    while (last + 1 < rated.length && rated[last + 1].verdict === "go") last++;
    departFrom = rated[first].t;
    backBy = rated[last].t + HOUR;
  }
  // The limiting factor, in words: the first window of the day's worst verdict
  // (so a marginal morning that turns no-go names what makes it no-go).
  const worst = windows.map((w) => w.verdict).reduce(worse);
  let limit = null;
  const firstShort = worst === "go" ? -1 : windows.findIndex((w) => w.verdict === worst);
  if (firstShort >= 0) {
    const win = windows[firstShort];
    const hour = rated.slice(firstShort * 2, firstShort * 2 + 2).reduce((a, b) => (RANK[b.verdict] > RANK[a.verdict] ? b : a));
    const factor = limitingFactor(bundle, point, hour.t, boat, hour.rating);
    const recovers = windows.slice(firstShort).findIndex((w) => w.verdict === "go");
    const when = firstShort === 0
      ? recovers > 0 ? ` until ${clock(windows[firstShort + recovers].start)}` : " all day"
      : ` after ${clock(win.start)}`;
    limit = factor ? { kind: factor.kind, text: factor.text + when } : { kind: "score", text: `rougher overall${when}` };
  }
  const conf = confidenceFrom(hours.map((t) => agreement(bundle, point, t)));
  const overall = windows.every((w) => w.verdict === "unknown") ? "unknown" : windows.some((w) => w.verdict === "go") ? "go" : windows.some((w) => w.verdict === "marginal") ? "marginal" : worst;
  return { date, windows, verdict: overall, worst, limit, confidence: conf.level, agreement: conf.text, departFrom, backBy,
    reasons: [...new Set(rated.flatMap((h) => h.rating?.reasons || []))] };
}

/** The next three local dates, starting tomorrow. */
export function planTomorrow(bundle, point, species, now = Date.now(), boat = activeBoatFactors(), rate = rateHour) {
  return futureDates(new Date(now)).slice(0, 3).map((date) => planDay(bundle, point, species, date, now, boat, rate));
}

const LABEL = { go: "Go", marginal: "Marginal", "no-go": "No-go", unknown: "No data" };
export function headline(day) {
  if (day.verdict === "unknown") return "No usable forecast";
  if (day.verdict === "go") return day.backBy ? `Go · back by ${clock(day.backBy)}` : "Go";
  return LABEL[day.verdict];
}

export function tomorrowHTML(days, { boatName = "", pointName = "" } = {}) {
  if (!days?.length) return "";
  const rows = days.map((d) => {
    const t = pacificEpoch(`${d.date}T12:00`);
    const pills = d.windows.map((w) => `<li class="tw-${w.verdict}" title="${esc(clock(w.start))}–${esc(clock(w.end))}: ${LABEL[w.verdict]}"><span>${esc(clock(w.start).replace(/ (a|p)\.m\./, "$1"))}</span><b>${LABEL[w.verdict]}</b></li>`).join("");
    const limit = d.limit ? `Limit: ${esc(d.limit.text)}` : "Nothing above your boat’s thresholds";
    return `<article class="tomorrow-day tw-${d.verdict}" data-date="${esc(d.date)}"><header><strong>${esc(local(t, { weekday: "short", month: "numeric", day: "numeric" }))}</strong><span class="tomorrow-verdict">${esc(headline(d))}</span></header><ol class="tomorrow-windows" aria-label="Two-hour windows">${pills}</ol><p class="tomorrow-limit">${limit}</p><p class="tomorrow-confidence">Confidence ${esc(d.confidence)} · ${esc(d.agreement)}</p></article>`;
  }).join("");
  const reasons = [...new Set(days.flatMap((d) => d.reasons))];
  return `<section class="tomorrow" aria-labelledby="tomorrow-heading"><h3 id="tomorrow-heading">Tomorrow${pointName ? ` · ${esc(pointName)}` : ""}</h3><p class="tomorrow-boat">${boatName ? `For ${esc(boatName)}` : "For the reference 23 ft boat · set your boat for your own limits"}</p>${rows}<details class="tomorrow-why"><summary>Why?</summary><p class="small">Each two-hour window from 5 a.m. to 7 p.m. takes the rougher hour. Go means a conditions score of ${GO}/10 or more for your boat, marginal ${NO_GO}–${GO - 0.1}, no-go below ${NO_GO} or any marine advisory. The limit names the largest single penalty (wind, gusts, seas, chop or crossing swell) in the first window of the day’s worst rating. Back-by is the end of the first unbroken run of go hours. Confidence is how often NOAA GFS and ECMWF agree within 4 kt of wind and 1 ft of seas. This is a planning heuristic: it is not a routed trip, a harbor-bar clearance or a safety certification, and bite potential is not scored.</p>${reasons.length ? `<ul class="small">${reasons.slice(0, 6).map((r) => `<li>${esc(r)}</li>`).join("")}</ul>` : ""}</details></section>`;
}

// The latest plan the app computed, for the first-run answer (first-run.js).
let latest = null;
export function publishTomorrow(days, pointName = '') {
  latest = { days, pointName };
  globalThis.document?.dispatchEvent(new CustomEvent('skippercast:tomorrow', { detail: latest }));
  return latest;
}
export function latestTomorrow() { return latest; }
