import test from "node:test";
import assert from "node:assert/strict";
import { airportReading, buoyReading, freshness, loadObservations, observationsHTML, observedDock, parseLiveAlerts } from "../dist/live-conditions.js";

const now = Date.parse("2026-09-21T19:00:00Z");
function feed() {
  return { schema_version: 1, generated_at: "2026-09-21T18:45:00Z", sources: { diablo: {
    status: "ok", data: { units: { WVHT: "m", DPD: "sec", MWD: "degT", WSPD: "m/s", GST: "m/s", WDIR: "degT" },
      observations: [
        { time: "2026-09-21T18:50:00Z", WVHT: null, DPD: null, WSPD: 3, GST: null, WDIR: 20 },
        { time: "2026-09-21T18:26:00Z", WVHT: 1, DPD: 17, MWD: 215, WSPD: null, GST: null },
      ] } } } };
}

test("buoy wind and waves keep their own sample times; missing gusts stay missing", () => {
  const r = buoyReading(feed(), "diablo", now);
  assert.ok(Math.abs(r.height - 3.28084) < 0.0001);
  assert.equal(r.period, 17);
  assert.equal(r.from, 215);
  assert.equal(r.gust, null);
  assert.equal(r.waveTime, Date.parse("2026-09-21T18:26:00Z"));
  assert.equal(r.windTime, Date.parse("2026-09-21T18:50:00Z"));
  assert.match(observedDock({ buoys: feed() }, false, now), /Diablo Canyon buoy/);
});

test("old, failed, delayed and future readings never appear as fresh observations", () => {
  assert.equal(freshness(now - 121 * 60000, now).fresh, false);
  assert.equal(freshness(now + 6 * 60000, now).fresh, false);
  assert.equal(freshness(now, now, false).fresh, false);
  assert.equal(freshness(NaN, now).label, "Unavailable");
  for (const alter of [d => { d.sources.diablo.status = "retained"; }, d => { d.generated_at = "2026-09-21T16:00:00Z"; }]) {
    const d = feed(); alter(d);
    assert.equal(observedDock({ buoys: d }, false, now), null);
    assert.equal(buoyReading(d, "diablo", now).height, 3.28084);
  }
});

test("unexpected units and missing source responses are not calm measurements", () => {
  const d = feed(); d.sources.diablo.data.units.WVHT = "ft";
  assert.equal(buoyReading(d, "diablo", now).height, null);
  assert.equal(buoyReading(null, "diablo", now).height, null);
  assert.equal(parseLiveAlerts({}), null);
  assert.equal(parseLiveAlerts({ type: "FeatureCollection", features: [null] }), null);
  assert.deepEqual(parseLiveAlerts({ type: "FeatureCollection", features: [] }), []);
});

test("airport observations convert validated units and reject invalid quality", () => {
  const p = { timestamp: "2026-09-21T18:50:00+00:00",
    temperature: { value: 19, unitCode: "wmoUnit:degC", qualityControl: "V" },
    windSpeed: { value: 5.544, unitCode: "wmoUnit:km_h-1", qualityControl: "V" },
    windGust: { value: null, unitCode: "wmoUnit:km_h-1" },
    windDirection: { value: 270, unitCode: "wmoUnit:degree_(angle)" } };
  const r = airportReading({ properties: p }, now);
  assert.equal(r.air, 66.2); assert.equal(Math.round(r.wind), 3);
  assert.equal(r.gust, null); assert.equal(r.visibility, null); assert.equal(r.from, 270);
  p.temperature.qualityControl = "X";
  assert.equal(airportReading({ properties: p }, now).air, null);
});

test("partial provider outages preserve other observations and cannot clear alerts", async () => {
  const r = await loadObservations(async url => {
    if (url.includes("raw.githubusercontent")) return feed();
    throw new Error("test source outage");
  }, now);
  assert.equal(r.buoys.schema_version, 1);
  assert.equal(r.airport, undefined);
  assert.equal(r.alerts.coastal, null);
  const html = observationsHTML({ ...r, retrieved: now }, false, now);
  assert.match(html, /could not be confirmed/);
  assert.match(html, /gust not reported/);
  assert.doesNotMatch(html, /No active issued marine alerts/);
  assert.match(html, /KSBP airport is on land/);
});
