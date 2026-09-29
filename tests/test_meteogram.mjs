import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  scoreLevel, niceCeil, segments, linePath, areaPath, barsPath, ticksPath, runs,
  provisionalStart, dayStarts, layout, indexAt, agreementLevel, summaryText, hasData,
  meteogramSVG, PROVISIONAL_HOUR,
} from "../dist/meteogram-core.js";
import { buildSeries } from "../dist/meteogram-series.js";

const HOUR = 3600;
const x = (i) => i * 10, y = (v) => 100 - v * 10;

function series(n = 169, start = Date.parse("2026-09-28T07:00:00Z") / 1000) {
  const s = { times: [], wind: [], gust: [], sea: [], period: [], tide: [], score: [], hazard: [], agreement: [], provisional: [] };
  for (let i = 0; i < n; i++) {
    s.times.push(start + i * HOUR);
    s.wind.push(6 + 6 * Math.sin(i / 7));
    s.gust.push(10 + 6 * Math.sin(i / 7));
    s.sea.push(3 + Math.cos(i / 11));
    s.period.push(11);
    s.tide.push(2.5 + 2.5 * Math.sin(i / 2));
    s.score.push(5 + 4 * Math.sin(i / 13));
    s.hazard.push(false);
    s.agreement.push(i % 30 < 3 ? "differ" : "agree");
    s.provisional.push(i >= PROVISIONAL_HOUR);
  }
  return s;
}

test("score colour mapping follows the go / caution / rough / unknown bands", () => {
  assert.equal(scoreLevel(9), "go");
  assert.equal(scoreLevel(7), "go");
  assert.equal(scoreLevel(6.9), "caution");
  assert.equal(scoreLevel(4), "caution");
  assert.equal(scoreLevel(3.9), "rough");
  assert.equal(scoreLevel(0), "rough");
  assert.equal(scoreLevel(9, true), "rough", "a hazard is never shown as go");
  for (const missing of [null, undefined, NaN, "7"]) assert.equal(scoreLevel(missing), "unknown");
});

test("scales round up to readable maxima and never collapse to zero", () => {
  assert.equal(niceCeil(12.3, 5, 15), 15);
  assert.equal(niceCeil(22, 5, 15), 25);
  assert.equal(niceCeil(null, 2, 4), 4);
  assert.equal(niceCeil(0, 2), 2);
  const L = layout(390, 169);
  assert.equal(L.x(0), L.left + L.step / 2);
  assert.ok(Math.abs(L.x(168) + L.step / 2 - (390 - L.right)) < 1e-9, "last hour ends at the right edge");
  assert.equal(indexAt(L.x(37), 390), 37);
  assert.equal(indexAt(-50, 390), 0);
  assert.equal(indexAt(9999, 390), 168);
});

test("missing values are gaps, never zeros", () => {
  const values = [1, 2, null, NaN, 3, undefined, 4, 5];
  assert.deepEqual(segments(values), [[0, 1], [4, 4], [6, 7]]);
  const line = linePath(values, x, y);
  assert.equal((line.match(/M/g) || []).length, 3, "the pen lifts at every gap");
  assert.doesNotMatch(line, /,100(?!\.)/, "no point is drawn at value 0");
  assert.match(line, /^M0,90L10,80M38.5,70H41.5M60,60L70,50$/);
  const area = areaPath([null, 1, 2, null], x, y, 100);
  assert.equal(area, "M10,100L10,90L20,80L20,100Z");
  assert.equal(barsPath([null, 0, 2], x, y, 100, 4), "M18,100V80h4V100Z", "null and 0 kt draw no bar");
  assert.equal(ticksPath([null, 3], x, y, 4), "M8,70h4");
  assert.equal(linePath([null, null], x, y), "");
});

test("an all-missing series is reported as unavailable, not drawn", () => {
  const s = series(10);
  for (const k of ["wind", "gust", "sea", "period", "tide", "score"]) s[k] = s[k].map(() => null);
  assert.equal(hasData(s), false);
  assert.match(summaryText(s), /Wind unavailable\. Seas unavailable\. Tide unavailable\. No hourly score available\./);
  assert.match(summaryText(s), /10 of 10 hours have no wind or seas data/);
});

test("the provisional boundary is the first flagged hour and is hatched from there", () => {
  const s = series();
  assert.equal(provisionalStart(s), 72);
  assert.equal(provisionalStart({ provisional: [false, false] }), null);
  const svg = meteogramSVG(s, { width: 390, id: "t" });
  const L = layout(390, 169);
  const px = Math.round((L.left + 72 * L.step) * 10) / 10;
  assert.match(svg, new RegExp(`<rect class="mg-provisional" x="${px}"[^>]*fill="url\\(#t-hatch\\)"`));
  assert.match(summaryText(s), /provisional outlook/);
});

test("score band runs and model agreement", () => {
  assert.deepEqual(runs(["go", "go", "unknown", "go"]), [
    { level: "go", start: 0, end: 1 }, { level: "unknown", start: 2, end: 2 }, { level: "go", start: 3, end: 3 }]);
  assert.equal(agreementLevel({ wind: 10, sea: 3 }, { wind: 13, sea: 3.5 }), "agree");
  assert.equal(agreementLevel({ wind: 10, sea: 3 }, { wind: 15, sea: 3 }), "differ");
  assert.equal(agreementLevel({ wind: 10, sea: 3 }, { wind: 10, sea: 4.5 }), "differ");
  assert.equal(agreementLevel({ wind: 10, sea: 3 }, { wind: null, sea: 3 }), "unknown");
  const s = series(24);
  s.score[5] = null;
  const svg = meteogramSVG(s, { width: 390 });
  assert.match(svg, /class="mg-score mg-unknown"/);
  assert.match(svg, /class="mg-differ"/);
});

test("day separators follow the region's local calendar days", () => {
  const start = Date.parse("2026-09-28T05:00:00Z") / 1000; // 10 p.m. PDT
  const days = dayStarts(Array.from({ length: 30 }, (_, i) => start + i * HOUR), "America/Los_Angeles");
  assert.deepEqual(days.map((d) => d.index), [0, 2, 26]);
  assert.match(days[1].label, /Mon 28|28 Mon/);
});

test("svg has an accessible summary, now marker, cursor with a 44 px target", () => {
  const s = series();
  const now = s.times[0] + 1800;
  const svg = meteogramSVG(s, { width: 390, now, selected: 10 });
  assert.match(svg, /^<svg[^>]*role="img"[^>]*aria-label="Hourly forecast from [^"]+Wind [^"]+Seas [^"]+Tide [^"]+"/);
  assert.match(svg, /class="mg-now"/);
  assert.match(svg, /<rect class="mg-hit" x="-22" y="0" width="44"/);
  const L = layout(390, 169);
  assert.match(svg, new RegExp(`class="mg-cursor" transform="translate\\(${Math.round(L.x(10) * 10) / 10},0\\)"`));
  assert.doesNotMatch(svg, /NaN|undefined|Infinity/);
});

test("builds the SVG for 169 samples in under 16 ms", () => {
  const s = series();
  for (let i = 0; i < 5; i++) meteogramSVG(s, { width: 390 }); // warm up the JIT and Intl caches
  const samples = [];
  for (let i = 0; i < 25; i++) {
    const t0 = performance.now();
    meteogramSVG(s, { width: 390, now: s.times[0], selected: i });
    samples.push(performance.now() - t0);
  }
  samples.sort((a, b) => a - b);
  const median = samples[Math.floor(samples.length / 2)];
  console.log(`meteogramSVG 169 samples: median ${median.toFixed(2)} ms, max ${samples.at(-1).toFixed(2)} ms`);
  assert.ok(median < 16, `median ${median} ms`);
});

// A minimal marine bundle in the shape loadMarine() returns.
function bundle(now, hours) {
  const values = {
    wind_speed_10m: [8, "kn"], wind_gusts_10m: [12, "kn"], wind_direction_10m: [315, "°"],
    visibility: [20000, "m"], weather_code: [1, "wmo code"], precipitation: [0, "mm"], temperature_2m: [60, "°F"],
    wave_height: [3, "ft"], wave_period: [11, "s"], wave_direction: [300, "°"],
    wind_wave_height: [0.5, "ft"], wind_wave_period: [4, "s"], wind_wave_direction: [315, "°"],
    swell_wave_height: [2.8, "ft"], swell_wave_period: [11, "s"], swell_wave_direction: [300, "°"],
    secondary_swell_wave_height: [0.2, "ft"], secondary_swell_wave_period: [15, "s"], secondary_swell_wave_direction: [200, "°"],
  };
  const d = { utc_offset_seconds: 0, hourly: { time: hours }, hourly_units: { time: "unixtime" } };
  for (const [k, [v, u]] of Object.entries(values)) { d.hourly[k] = hours.map(() => v); d.hourly_units[k] = u; }
  const tides = hours.flatMap((t) => [0, 1800].map((o) => ({ time: t + o, height: 2 + Math.sin((t + o) / 20000) })));
  return {
    retrieved: now, alerts: { coastal: [], offshore: [] }, tides,
    models: Object.fromEntries(["gfs_global", "ecmwf_ifs025", "ncep_gfswave016", "ecmwf_wam"].map((id) => [id, {
      data: [structuredClone(d)], meta: { last_run_initialisation_time: now / 1000 - 3600, data_end_time: hours.at(-1) },
    }])),
  };
}

test("buildSeries reads the loaded bundle and keeps missing hours null", () => {
  const now = Date.parse("2026-09-28T15:00:00Z");
  const start = Math.floor(now / 1000 / HOUR) * HOUR;
  const hours = Array.from({ length: 169 }, (_, i) => start + i * HOUR);
  const b = bundle(now, hours);
  b.models.gfs_global.data[0].hourly.wind_speed_10m[5] = null;
  b.models.ncep_gfswave016.data[0].hourly.wave_height[6] = null;
  b.models.gfs_global.data[0].hourly.wind_gusts_10m[7] = 4; // gust below sustained wind
  b.models.ecmwf_ifs025.data[0].hourly.wind_speed_10m[8] = 20;
  b.tides = b.tides.filter((p) => p.time < start + 100 * HOUR);
  const s = buildSeries(b, 0, "lingcod", "gfs", start, now);
  assert.equal(s.times.length, 169);
  assert.equal(s.wind[0], 8);
  assert.equal(s.sea[0], 3);
  assert.equal(s.period[0], 11);
  assert.ok(Number.isFinite(s.tide[0]));
  assert.equal(s.wind[5], null);
  assert.equal(s.sea[6], null);
  assert.equal(s.gust[7], null, "inconsistent gust is omitted, not drawn");
  assert.equal(s.agreement[8], "differ");
  assert.equal(s.agreement[5], "unknown");
  assert.equal(s.tide[120], null, "no tide past the predictions");
  assert.ok(s.score[0] >= 7);
  assert.equal(s.provisional[71], false);
  assert.equal(s.provisional[72], true);
  const stale = buildSeries(b, 0, "lingcod", "gfs", start, now + 4 * 3600000);
  assert.ok(stale.score.every((v) => v === null), "stale forecasts have no score");
});

test("mount is a separate module and keeps region-dependent imports lazy", () => {
  const ui = readFileSync(new URL("../dist/meteogram-ui.js", import.meta.url), "utf8");
  const statics = [...ui.matchAll(/^import\s[^;]*?from\s*["']\.\/([^"']+)["']/gm)].map((m) => m[1]);
  assert.deepEqual(statics, ["meteogram.js"], "marine-data.js must not load before boot.js sets the region");
  assert.match(ui, /import\("\.\/meteogram-series\.js"\)/);
  assert.match(ui, /getElementById\("detail-hour"\)/);
  const html = readFileSync(new URL("../dist/index.html", import.meta.url), "utf8");
  assert.match(html, /<link rel="stylesheet" href="meteogram\.css" \/>/);
  assert.match(html, /<details id="meteogram-card" class="meteogram-card" open>/);
  assert.match(html, /<script type="module" src="meteogram-ui\.js"><\/script>/);
});
