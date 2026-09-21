import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import { hourScores, rankMornings } from "../dist/morning-outlook.js";
import { futureDates, pacificEpoch } from "../dist/forecast.js";
const now = Date.parse("2026-09-21T08:00:00-07:00");
const times = futureDates(new Date(now)).flatMap((d) =>
  Array.from({ length: 7 }, (_, i) =>
    pacificEpoch(`${d}T${String(i + 7).padStart(2, "0")}:00`),
  ),
);
function bundle() {
  const values = {
    wind_speed_10m: [5, "kn"],
    wind_gusts_10m: [8, "kn"],
    wind_direction_10m: [315, "°"],
    visibility: [20000, "m"],
    weather_code: [1, "wmo code"],
    wave_height: [2, "ft"],
    wave_period: [12, "s"],
    wave_direction: [300, "°"],
    wind_wave_height: [0.3, "ft"],
    wind_wave_period: [4, "s"],
    wind_wave_direction: [315, "°"],
    swell_wave_height: [1.8, "ft"],
    swell_wave_period: [12, "s"],
    swell_wave_direction: [300, "°"],
    secondary_swell_wave_height: [0.2, "ft"],
    secondary_swell_wave_period: [15, "s"],
    secondary_swell_wave_direction: [200, "°"],
  };
  const d = {
    utc_offset_seconds: 0,
    hourly: { time: times },
    hourly_units: { time: "unixtime" },
  };
  for (const [k, [v, u]] of Object.entries(values)) {
    d.hourly[k] = times.map(() => v);
    d.hourly_units[k] = u;
  }
  return {
    retrieved: now,
    alerts: { coastal: [], offshore: [] },
    models: Object.fromEntries(
      ["gfs_global", "ecmwf_ifs025", "ncep_gfswave025", "ecmwf_wam025"].map(
        (id) => [
          id,
          {
            data: [structuredClone(d)],
            meta: {
              last_run_initialisation_time: now / 1000 - 3600,
              data_end_time: times.at(-1),
            },
          },
        ],
      ),
    ),
  };
}
test("full morning rating preserves unknown bite and uses the worst return hour", () => {
  const b = bundle();
  let row = rankMornings(b, 0, "lingcod", now)[0];
  assert.ok(row.conditions >= 8);
  assert.equal(row.bite, null);
  assert.equal(row.overall, null);
  for (const id of ["gfs_global", "ecmwf_ifs025"]) {
    b.models[id].data[0].hourly.wind_speed_10m[6] = 16;
    b.models[id].data[0].hourly.wind_gusts_10m[6] = 20;
  }
  row = rankMornings(b, 0, "lingcod", now)[0];
  assert.ok(row.conditions < 8);
  assert.ok(row.control <= row.comfort);
});
test("missing hours, inconsistent gusts, alert uncertainty and stale runs cannot qualify", () => {
  for (const mutate of [
    (b) => (b.models.ecmwf_wam025.data[0].hourly.wave_height[6] = null),
    (b) => (b.models.gfs_global.data[0].hourly.wind_gusts_10m[4] = 2),
    (b) => (b.alerts.coastal = null),
    (b) => (b.models.ncep_gfswave025.data[0].hourly.wind_wave_period[3] = null),
    (b) =>
      (b.models.ncep_gfswave025.data[0].hourly.secondary_swell_wave_direction[3] =
        null),
    (b) =>
      (b.models.gfs_global.meta.last_run_initialisation_time =
        now / 1000 - 40 * 3600),
    (b) => (b.alerts.coastal = [{ title: "Marine hazard" }]),
  ]) {
    const b = bundle();
    mutate(b);
    assert.equal(rankMornings(b, 0, "lingcod", now)[0].conditions, null);
  }
});
test("model disagreement can show a tentative best but never an 8+ highlight", () => {
  const b = bundle();
  b.models.ecmwf_ifs025.data[0].hourly.wind_speed_10m[0] = 9.1;
  b.models.ecmwf_ifs025.data[0].hourly.wind_gusts_10m[0] = 10;
  const r = rankMornings(b, 0, "lingcod", now)[0];
  assert.equal(r.confidence, "Low");
  assert.ok(r.conditions <= 7.9);
  assert.ok(r.conditions !== null);
});
test("rating dates follow Pacific calendar and incomplete final morning remains unrated", () => {
  const r = rankMornings(bundle(), 0, "halibut", now);
  assert.equal(r.length, 7);
  assert.equal(r[0].date, "2026-09-22");
  assert.equal(r.at(-1).conditions, null);
  assert.equal(r[3].provisional, true);
});
test("connected habitat regions retain holes and species depth ceilings", () => {
  const regions = JSON.parse(
    fs.readFileSync(
      new URL("../dist/data/habitat-regions.json", import.meta.url),
    ),
  ).areas;
  assert.equal(regions.filter((a) => a.species.includes("halibut")).length, 5);
  assert.equal(
    regions.filter((a) => a.species.includes("dungeness")).length,
    7,
  );
  assert.ok(regions.some((a) => a.geometry.coordinates.length > 1));
  for (const a of regions) {
    assert.equal(a.geometry.type, "Polygon");
    assert.ok(a.area_km2 >= 0.2);
    assert.ok(a.depth_ft[0] >= 25);
    assert.ok(a.depth_ft[1] < 200);
    if (a.species.includes("halibut")) assert.ok(a.depth_ft[1] <= 100);
    for (const ring of a.geometry.coordinates) {
      assert.deepEqual(ring[0], ring.at(-1));
      assert.ok(ring.length >= 4);
    }
  }
});
