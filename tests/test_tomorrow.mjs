import test from "node:test";
import assert from "node:assert/strict";
import { planTomorrow, planDay, verdictFor, confidenceFrom, limitingFactor, tomorrowHTML, headline, clock } from "../dist/tomorrow.js";
import { futureDates, pacificEpoch } from "../dist/forecast.js";

const now = Date.parse("2026-09-21T20:00:00-07:00");
const dates = futureDates(new Date(now)).slice(0, 4);
const times = dates.flatMap((d) => Array.from({ length: 24 }, (_, h) => pacificEpoch(`${d}T${String(h).padStart(2, "0")}:00`)));
const REF = { sea: 1, wind: 1, chopPeriod: 6 };

function bundle(overrides = {}) {
  const values = {
    wind_speed_10m: [5, "kn"], wind_gusts_10m: [8, "kn"], wind_direction_10m: [315, "°"],
    visibility: [20000, "m"], weather_code: [1, "wmo code"],
    wave_height: [2, "ft"], wave_period: [12, "s"], wave_direction: [300, "°"],
    wind_wave_height: [0.3, "ft"], wind_wave_period: [4, "s"], wind_wave_direction: [315, "°"],
    swell_wave_height: [1.8, "ft"], swell_wave_period: [12, "s"], swell_wave_direction: [300, "°"],
    secondary_swell_wave_height: [0.2, "ft"], secondary_swell_wave_period: [15, "s"], secondary_swell_wave_direction: [200, "°"],
  };
  const d = { utc_offset_seconds: 0, hourly: { time: times }, hourly_units: { time: "unixtime" } };
  for (const [k, [v, u]] of Object.entries(values)) { d.hourly[k] = times.map(() => v); d.hourly_units[k] = u; }
  const b = {
    retrieved: now, alerts: { coastal: [], offshore: [] },
    models: Object.fromEntries(["gfs_global", "ecmwf_ifs025", "ncep_gfswave016", "ecmwf_wam"].map((id) => [id, {
      data: [structuredClone(d)], meta: { last_run_initialisation_time: now / 1000 - 3600, data_end_time: times.at(-1) },
    }])),
  };
  return b;
}
// Set a variable on the given models from a local date and hour onward.
function setFrom(b, ids, key, value, date, hour, until = 24) {
  for (const id of ids) b.models[id].data[0].hourly[key] = b.models[id].data[0].hourly[key].map((v, i) => {
    const t = times[i], d0 = pacificEpoch(`${date}T${String(hour).padStart(2, "0")}:00`), d1 = pacificEpoch(`${date}T00:00`) + until * 3600;
    return t >= d0 && t < d1 ? value : v;
  });
}
const WIND = ["gfs_global", "ecmwf_ifs025"], WAVE = ["ncep_gfswave016", "ecmwf_wam"];

test("verdict thresholds: go at 7+, marginal 4–6.9, no-go under 4 or any hazard", () => {
  assert.equal(verdictFor({ conditions: 7 }), "go");
  assert.equal(verdictFor({ conditions: 6.9 }), "marginal");
  assert.equal(verdictFor({ conditions: 3.9 }), "no-go");
  assert.equal(verdictFor({ conditions: 8, hazard: true }), "no-go");
  assert.equal(verdictFor({ conditions: null }), "unknown");
  assert.equal(verdictFor(null), "unknown");
});

test("a calm day is go all day with a back-by at 7 p.m. and high agreement", () => {
  const days = planTomorrow(bundle(), 0, "lingcod", now, REF);
  assert.equal(days.length, 3);
  assert.deepEqual(days.map((d) => d.date), dates.slice(0, 3));
  const d = days[0];
  assert.equal(d.windows.length, 7);
  assert.ok(d.windows.every((w) => w.verdict === "go"));
  assert.equal(d.limit, null);
  assert.equal(d.confidence, "High");
  assert.equal(clock(d.departFrom), "5 a.m.");
  assert.equal(clock(d.backBy), "7 p.m.");
  assert.match(headline(d), /^Go · back by 7 p\.m\.$/);
});

test("afternoon northwesterly is named with its time and ends the comfortable run", () => {
  const b = bundle();
  setFrom(b, WIND, "wind_speed_10m", 18, dates[0], 11);
  setFrom(b, WIND, "wind_gusts_10m", 22, dates[0], 11);
  const d = planDay(b, 0, "lingcod", dates[0], now, REF);
  assert.deepEqual(d.windows.map((w) => w.verdict).slice(0, 3), ["go", "go", "go"]);
  assert.notEqual(d.windows[3].verdict, "go");
  assert.equal(d.limit.kind, "wind");
  assert.equal(d.limit.text, "NW 18 kt after 11 a.m.");
  assert.equal(clock(d.backBy), "11 a.m.");
  assert.equal(d.verdict, "go");
});

test("a rough morning that eases says 'until' and starts the run later", () => {
  const b = bundle();
  setFrom(b, WAVE, "wave_height", 12, dates[1], 0, 9);
  setFrom(b, WAVE, "wave_period", 9, dates[1], 0, 9);
  setFrom(b, WAVE, "swell_wave_height", 11.5, dates[1], 0, 9);
  const d = planDay(b, 0, "lingcod", dates[1], now, REF);
  assert.equal(d.windows[0].verdict, "no-go");
  assert.equal(d.limit.kind, "seas");
  assert.equal(d.limit.text, "12 ft seas at 9 s until 9 a.m.");
  assert.equal(clock(d.departFrom), "9 a.m.");
});

test("a saved small boat lowers its limits compared with the reference boat", () => {
  const b = bundle();
  setFrom(b, WAVE, "wave_height", 3.2, dates[0], 0);
  const small = { sea: 0.6, wind: 0.8, chopPeriod: 5 };
  const ref = limitingFactor(b, 0, pacificEpoch(`${dates[0]}T09:00`), REF);
  const tiny = limitingFactor(b, 0, pacificEpoch(`${dates[0]}T09:00`), small);
  assert.ok(!ref || tiny.penalty > ref.penalty);
  assert.equal(tiny.kind, "seas");
});

test("model disagreement lowers confidence; a missing model is one-model only", () => {
  const b = bundle();
  setFrom(b, ["ecmwf_ifs025"], "wind_speed_10m", 14, dates[0], 0);
  setFrom(b, ["ecmwf_ifs025"], "wind_gusts_10m", 18, dates[0], 0);
  assert.equal(planDay(b, 0, "lingcod", dates[0], now, REF).confidence, "Low");
  assert.deepEqual(confidenceFrom([true, true, true, false, true, true, true, true, true, true]), { level: "High", text: "GFS and ECMWF agree" });
  assert.equal(confidenceFrom([true, false, true, true, false, true]).level, "Moderate");
  assert.deepEqual(confidenceFrom([null, null, true]), { level: "Low", text: "one model only" });
});

test("an active marine advisory is no-go and names the advisory", () => {
  const b = bundle();
  b.alerts.coastal = [{ title: "Small Craft Advisory", starts: pacificEpoch(`${dates[0]}T13:00`), ends: pacificEpoch(`${dates[0]}T23:00`) }];
  b.alerts.offshore = b.alerts.coastal;
  const d = planDay(b, 0, "lingcod", dates[0], now, REF);
  assert.equal(d.windows[4].verdict, "no-go");
  assert.equal(d.limit.text, "Small Craft Advisory after 1 p.m.");
});

test("no fresh forecast gives no-data windows, never a go", () => {
  const stale = { ...bundle(), retrieved: now - 5 * 3600000 };
  const d = planDay(stale, 0, "lingcod", dates[0], now, REF);
  assert.equal(d.verdict, "unknown");
  assert.ok(d.windows.every((w) => w.verdict === "unknown"));
  assert.equal(d.backBy, null);
  assert.equal(headline(d), "No usable forecast");
});

test("the card escapes text and keeps caveats behind Why?", () => {
  const b = bundle();
  setFrom(b, WIND, "wind_speed_10m", 18, dates[0], 11);
  const html = tomorrowHTML(planTomorrow(b, 0, "lingcod", now, REF), { boatName: "<Sea Ray>", pointName: "Morro" });
  assert.match(html, /&lt;Sea Ray&gt;/);
  assert.match(html, /Limit: NW 18 kt after 11 a\.m\./);
  assert.match(html, /<details class="tomorrow-why"><summary>Why\?<\/summary>/);
  const beforeWhy = html.split('<details class="tomorrow-why">')[0];
  assert.doesNotMatch(beforeWhy, /not a routed trip/);
  assert.equal((html.match(/<article class="tomorrow-day/g) || []).length, 3);
});

test("a marginal morning that turns no-go names what makes it no-go", () => {
  const b = bundle();
  setFrom(b, WAVE, "wave_height", 7, dates[0], 0);
  setFrom(b, WIND, "wind_speed_10m", 25, dates[0], 13);
  setFrom(b, WIND, "wind_gusts_10m", 30, dates[0], 13);
  const d = planDay(b, 0, "lingcod", dates[0], now, REF);
  assert.equal(d.windows[0].verdict, "marginal");
  assert.equal(d.worst, "no-go");
  assert.equal(d.verdict, "marginal");
  assert.equal(d.limit.text, "NW 25 kt after 1 p.m.");
  assert.equal(d.backBy, null);
});
