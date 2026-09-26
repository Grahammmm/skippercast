import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import { hourScores, rankMornings, rateHour, rankTimelineDays } from "../dist/morning-outlook.js";
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
      ["gfs_global", "ecmwf_ifs025", "ncep_gfswave016", "ecmwf_wam025"].map(
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
test("rough combined seas retain a useful nonzero ranking without double-counting wind waves", () => {
  const c={wind:12,gust:16,sea:{height:6},chop:{height:5,period:8},
    swell:{from:300},secondary:{height:0,from:200}};
  const rough=hourScores(c,{wind:12,gust:16,sea:{height:6}},'reef');
  assert.ok(rough.conditions>2 && rough.conditions<5);
  const lessChop=hourScores({...c,chop:{height:0.5,period:8}},{wind:12,gust:16,sea:{height:6}},'reef');
  assert.ok(rough.conditions<lessChop.conditions);
  const extreme=hourScores({...c,wind:30,gust:38,sea:{height:12},chop:{height:11,period:5}},
    {wind:30,gust:38,sea:{height:12}},'reef');
  assert.equal(extreme.conditions,0);
});
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
test("missing detail and stale individual models show limited scores that cannot qualify", () => {
  for (const mutate of [
    (b) => (b.models.ecmwf_wam025.data[0].hourly.wave_height[6] = null),
    (b) => (b.alerts.coastal = null),
    (b) => (b.models.ncep_gfswave016.data[0].hourly.wind_wave_period[3] = null),
    (b) =>
      (b.models.ncep_gfswave016.data[0].hourly.secondary_swell_wave_direction[3] =
        null),
    (b) =>
      (b.models.gfs_global.meta.last_run_initialisation_time =
        now / 1000 - 40 * 3600),
    (b) => (b.alerts.coastal = [{ title: "Marine hazard" }]),
  ]) {
    const b = bundle();
    mutate(b);
    const row=rankMornings(b, 0, "lingcod", now)[0];
    assert.ok(Number.isFinite(row.conditions) && row.conditions<8);
    assert.equal(row.confidence,"Low");
  }
});
test("inconsistent gusts remain flagged and never produce a high-confidence score", () => {
  const b=bundle();
  b.models.gfs_global.data[0].hourly.wind_gusts_10m[4]=2;
  const row=rankMornings(b,0,"reef",now)[0];
  assert.ok(Number.isFinite(row.conditions) && row.conditions<=7.9);
  assert.equal(row.confidence,"Low");
  assert.ok(row.reasons.some(r=>r.includes("Inconsistent gust omitted")));
  assert.equal(b.models.gfs_global.data[0].hourly.wind_gusts_10m[4],2);
  b.models.ecmwf_ifs025.data[0].hourly.wind_gusts_10m[4]=3;
  const both=rankMornings(b,0,"reef",now)[0];
  assert.ok(both.conditions<=6.9);
  assert.ok(both.reasons.some(r=>r.includes("no gust assumed")));
});
test("partial last day is disclosed and cannot get an 8+ score", () => {
  const b=bundle(),hours=times.slice(0,-3);
  const rows=rankTimelineDays(b,0,"reef",hours,now);
  assert.equal(rows.at(-1).partial,true);
  assert.equal(rows.at(-1).sampleCount,4);
  assert.ok(rows.at(-1).conditions<=7.9);
  assert.equal(rows.at(-1).confidence,"Low");
});
test("seven-day strip retains numeric warnings and limited outlooks without a false 8+",()=>{
  const b=bundle();
  b.alerts.coastal=[{title:'Small Craft Advisory',starts:times[0]-3600,ends:times[6]+3600}];
  b.models.ecmwf_wam025.meta.data_end_time=times[20];
  const rows=rankTimelineDays(b,0,'reef',times,now);
  assert.equal(rows.length,7);
  assert.ok(rows.every(r=>Number.isFinite(r.conditions)));
  assert.ok(rows[0].conditions<=1.9 && rows[0].hazard);
  assert.ok(rows.slice(3).every(r=>r.limited && r.conditions<=6.9 && r.confidence==='Low'));
  assert.ok([rows[0],...rows.slice(3)].every(r=>r.conditions<8));
});
test("no usable wind or combined seas remains unrated",()=>{
  const b=bundle();
  for(const m of ['gfs_global','ecmwf_ifs025']) b.models[m].data[0].hourly.wind_speed_10m.fill(null);
  for(const m of ['ncep_gfswave016','ecmwf_wam025']) b.models[m].data[0].hourly.wave_height.fill(null);
  const row=rankTimelineDays(b,0,'reef',times,now)[0];
  assert.equal(row.conditions,null);
  assert.ok(row.reasons.some(r=>r.includes('No usable wind')));
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


test("a retained individual model cannot be made fresh by another successful refresh",()=>{
 const b=bundle();b.models.gfs_global.retrieved=now-4*3600000;
 const row=rateHour(b,0,'reef',times[0],now);
 assert.ok(row.conditions<=6.9);
 assert.equal(row.limited,true);
 assert.ok(row.reasons.some(r=>r.includes('NOAA GFS forecast unavailable')));
});
test("day narrative labels incomplete coverage as a limited estimate",async()=>{
 const {boatDayHTML,ratingLabel}=await import('../dist/forecast-summary.js');
 const b=bundle(),r=rankMornings(b,0,'reef',now)[0];
 let html=boatDayHTML(b,0,'reef',times[0],r,now);
 assert.match(html,/on the boat/);assert.match(html,/kt/);assert.match(html,/seconds apart/);
 assert.equal(ratingLabel(0),'Very rough');assert.equal(ratingLabel(null),'Data incomplete');
 b.models.ncep_gfswave016.data[0].hourly.wave_height.fill(null);
 const missing=rankMornings(b,0,'reef',now)[0];html=boatDayHTML(b,0,'reef',times[0],missing,now);
 assert.match(html,/Limited forecast screen/);assert.match(html,/limited comparison/);assert.ok(missing.conditions<=6.9);
 b.models.ecmwf_wam025.data[0].hourly.wave_height.fill(null);
 const none=rankMornings(b,0,'reef',now)[0];html=boatDayHTML(b,0,'reef',times[0],none,now);
 assert.equal(none.conditions,null);assert.match(html,/Data incomplete/);assert.doesNotMatch(html,/0.0\/10/);
});
