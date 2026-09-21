import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import {
  sample,
  timeline,
  directionTo,
  angleBetween,
  comfort,
  tidePoints,
  tideAt,
  readConditions,
  POINTS,
  MODELS,
  modelURL,
} from "../dist/marine-data.js";
import { matchesSpecies, PROFILES } from "../dist/species.js";
import { lineChart, waveSketch } from "../dist/marine-charts.js";

const forecast = (values = [0, 2], times = [100, 3700]) => ({
  utc_offset_seconds: 0,
  hourly_units: { time: "unixtime", wave_height: "ft" },
  hourly: { time: times, wave_height: values },
});
test("forecast samples preserve zero, reject missing/invalid values, and respect published coverage", () => {
  assert.equal(sample(forecast(), "wave_height", 100, "ft"), 0);
  for (const n of [null, undefined, "0", NaN, -1])
    assert.equal(sample(forecast([n, 2]), "wave_height", 100, "ft"), null);
  assert.equal(sample(forecast(), "wave_height", 100, "m"), null);
  assert.equal(
    sample(forecast(), "wave_height", 3700, "ft", { data_end_time: 3699 }),
    null,
  );
  assert.equal(sample(forecast(), "wave_height", 4000, "ft"), null);
  assert.equal(
    sample(forecast([1], [100, 3700]), "wave_height", 100, "ft"),
    null,
  );
  assert.equal(
    sample(forecast([1, 2], [100, 100]), "wave_height", 100, "ft"),
    null,
  );
  const wrong = forecast();
  wrong.utc_offset_seconds = -25200;
  assert.equal(sample(wrong, "wave_height", 100, "ft"), null);
});
test("timeline is exactly 168 elapsed hours, even across a Pacific DST change", () => {
  const h = timeline(Date.parse("2026-10-31T22:37:00-07:00"));
  assert.equal(h.length, 169);
  assert.equal(h.at(-1) - h[0], 7 * 86400);
  assert.equal(new Set(h).size, 169);
  assert.equal(h[0] % 3600, 0);
});
test("from/to directions are explicit and headings wrap through north", () => {
  assert.equal(directionTo(0), 180);
  assert.equal(directionTo(270), 90);
  assert.equal(directionTo(null), null);
  assert.equal(angleBetween(350, 10), 20);
  assert.equal(angleBetween(90, 270), 180);
});
function calm() {
  return {
    wind: 5,
    gust: 8,
    windFrom: 315,
    sea: { height: 2, period: 12, from: 300 },
    chop: { height: 0.3, period: 4, from: 315 },
    swell: { height: 1.8, period: 12, from: 300 },
    secondary: { height: 0.2, period: 15, from: 200 },
    visibility: 20000,
    weatherCode: 1,
  };
}
test("comfort does not reward missing data, inconsistent gusts, or contradictory models", () => {
  const c = calm();
  assert.equal(comfort(c, calm(), []).level, "calmer");
  assert.equal(comfort({ ...c, wind: null }, calm(), []).level, "unknown");
  assert.equal(comfort({ ...c, gust: 4 }, calm(), []).level, "unknown");
  assert.equal(comfort(c, { ...calm(), gust: 4 }, []).level, "unknown");
  assert.equal(comfort(c, { ...calm(), wind: 12 }, []).level, "unknown");
  assert.equal(comfort(c, null, []).level, "unknown");
  assert.equal(comfort(c, calm(), null).level, "unknown");
});
test("hazards and cross swell override otherwise low wave numbers", () => {
  const c = calm();
  assert.equal(comfort(c, calm(), ["Small Craft Advisory"]).level, "hazard");
  assert.equal(comfort({ ...c, visibility: 500 }, calm(), []).level, "hazard");
  assert.equal(comfort({ ...c, weatherCode: 95 }, calm(), []).level, "hazard");
  assert.equal(
    comfort(
      { ...c, secondary: { height: 1.2, period: 14, from: 160 } },
      calm(),
      [],
    ).level,
    "mixed",
  );
  assert.equal(
    comfort({ ...c, chop: { height: 1.2, period: 4, from: 315 } }, calm(), [])
      .level,
    "mixed",
  );
});
test("comfort includes the rougher comparison even below disagreement cutoffs", () => {
  const c = { ...calm(), wind: 8, gust: 12, sea: { ...calm().sea, height: 3 } };
  const other = {
    ...calm(),
    wind: 12,
    gust: 18,
    sea: { ...calm().sea, height: 4 },
  };
  assert.equal(comfort(c, other, []).level, "mixed");
  assert.equal(comfort(other, c, []).level, "mixed");
  assert.equal(
    comfort(calm(), { ...calm(), visibility: 500 }, []).level,
    "hazard",
  );
});
test("tides accept negative levels, reject blank values, and do not bridge missing intervals", () => {
  const p = tidePoints({
    predictions: [
      { t: "2026-09-21 12:00", v: "-0.5" },
      { t: "2026-09-21 12:06", v: "0.5" },
      { t: "2026-09-21 12:12", v: "" },
      { t: "2026-09-21 12:18", v: null },
    ],
  });
  assert.equal(p.length, 2);
  assert.equal(tideAt(p, p[0].time + 180), 0);
  assert.equal(tideAt(p, p[0].time - 1), null);
  assert.equal(tideAt(p, p.at(-1).time + 1), null);
  assert.equal(
    tideAt(
      [
        { time: 0, height: 0 },
        { time: 720, height: 1 },
      ],
      360,
    ),
    null,
  );
});
test("current speed is converted from the actual returned unit, including zero", () => {
  const d = {
    utc_offset_seconds: 0,
    hourly_units: { time: "unixtime", ocean_current_velocity: "km/h" },
    hourly: { time: [100], ocean_current_velocity: [1.852] },
  };
  const bundle = { models: { meteofrance_currents: { data: [d] } } };
  assert.equal(readConditions(bundle, 0, 100).current, 1);
  d.hourly_units.ocean_current_velocity = "kn";
  assert.equal(readConditions(bundle, 0, 100).current, null);
});
test("every model request has its own grid, UTC epochs, explicit units and eight days", () => {
  for (const m of MODELS) {
    const url = new URL(modelURL(m));
    assert.equal(url.searchParams.get("models"), m.id);
    assert.equal(url.searchParams.get("forecast_days"), "8");
    assert.equal(url.searchParams.get("timeformat"), "unixtime");
    assert.equal(url.searchParams.get("timezone"), "UTC");
    assert.equal(
      url.searchParams.get("latitude").split(",").length,
      POINTS.length,
    );
  }
});
test("species filters separate reef candidates, sediment windows, and pelagic search sectors", () => {
  const atlas = JSON.parse(
    fs.readFileSync(new URL("../dist/data/atlas.json", import.meta.url)),
  );
  const soft = JSON.parse(
    fs.readFileSync(
      new URL("../dist/data/species-habitat.json", import.meta.url),
    ),
  );
  assert.equal(Object.keys(PROFILES).length, 7);
  assert.equal(
    atlas.targets.filter((t) => matchesSpecies(t, "rockfish")).length,
    132,
  );
  const ling = atlas.targets.filter((t) => matchesSpecies(t, "lingcod"));
  assert.ok(ling.length > 0 && ling.length < 132);
  for (const id of ["halibut", "dungeness", "salmon", "bluefin", "albacore"])
    assert.equal(atlas.targets.filter((t) => matchesSpecies(t, id)).length, 0);
  assert.equal(soft.areas.length, 18);
  assert.equal(
    soft.areas.filter((a) => a.species.includes("halibut")).length,
    9,
  );
  for (const a of soft.areas) {
    assert.ok(a.depth_ft[1] <= 195);
    assert.ok(a.depth_ft[0] >= 25);
    assert.ok(a.soft_bottom_percent >= 95);
    assert.ok(!a.source_url.includes("Cambria"));
    assert.equal(a.geometry.type, "Polygon");
    if (a.species.includes("halibut")) assert.ok(a.depth_ft[1] <= 100);
  }
});
test("graphs break at missing values and wave drawings do not claim exact wave arrivals", () => {
  const svg = lineChart(
    [
      { time: 0, value: 1 },
      { time: 3600, value: null },
      { time: 7200, value: 2 },
    ],
    { label: "test", unit: "ft" },
  );
  assert.match(svg, /Gaps are unavailable/);
  assert.match(svg, /M42\.0,[\d.]+ M602\.0/);
  assert.match(
    waveSketch({ height: 2, period: 12, from: 270 }, "Swell", "#000"),
    /5\.0 wave cycles/,
  );
  assert.match(
    waveSketch({ height: null, period: 12, from: 270 }, "Swell", "#000"),
    /unavailable/,
  );
});
