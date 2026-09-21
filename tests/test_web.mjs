import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import {
  valueAt,
  range,
  evidenceFlags,
  futureDates,
  compass,
  coverageNote,
  pacificEpoch,
} from "../dist/forecast.js";
import { targetGPX } from "../dist/gpx.js";

test("direct mobile downloads match every public target and its linked geometry", () => {
  const atlas = JSON.parse(
    readFileSync(new URL("../dist/data/atlas.json", import.meta.url)),
  );
  const directory = new URL("../dist/downloads/targets/", import.meta.url);
  assert.deepEqual(
    readdirSync(directory).sort(),
    atlas.targets.map((t) => `${t.id}.gpx`).sort(),
  );
  for (const target of atlas.targets) {
    assert.equal(
      readFileSync(new URL(`${target.id}.gpx`, directory), "utf8"),
      targetGPX(atlas, target.id),
      target.id,
    );
  }
});

test("missing, null, invalid units, duplicates, and malformed arrays are unavailable", () => {
  const f = {
    timezone: "America/Los_Angeles",
    hourly: { time: ["2026-09-21T08:00"], wind_speed_10m_gfs_global: [null] },
    hourly_units: { wind_speed_10m_gfs_global: "kn" },
  };
  const get = () =>
    valueAt(f, "gfs_global", "wind_speed_10m", "2026-09-21T08:00", "kn");
  assert.equal(get(), null);
  f.hourly.wind_speed_10m_gfs_global = [0];
  assert.equal(get(), 0);
  f.hourly_units.wind_speed_10m_gfs_global = "km/h";
  assert.equal(get(), null);
  f.hourly_units.wind_speed_10m_gfs_global = "kn";
  f.hourly.time.push("2026-09-21T08:00");
  assert.equal(get(), null);
  f.hourly.wind_speed_10m_gfs_global.push(2);
  assert.equal(get(), null);
  assert.equal(range([1, null, 2]), null);
  assert.equal(range([0, 0]), "0.0");
});
test("values do not extrapolate past the returned hours", () => {
  const f = {
    timezone: "America/Los_Angeles",
    hourly: { time: ["2026-09-21T08:00"], wave_height_ecmwf_wam025: [2] },
    hourly_units: { wave_height_ecmwf_wam025: "ft" },
  };
  assert.equal(
    valueAt(f, "ecmwf_wam025", "wave_height", "2026-09-22T08:00", "ft"),
    null,
  );
});
test("inconsistent gusts are visible and missing models do not silently pass", () => {
  const f = {
    timezone: "America/Los_Angeles",
    hourly: {
      time: ["2026-09-21T08:00"],
      wind_speed_10m_gfs_global: [8],
      wind_gusts_10m_gfs_global: [4],
    },
    hourly_units: {
      wind_speed_10m_gfs_global: "kn",
      wind_gusts_10m_gfs_global: "kn",
    },
  };
  const flags = evidenceFlags(f, null, "2026-09-21T08:00");
  assert.ok(flags.some((s) => s.includes("inconsistent")));
  assert.ok(flags.some((s) => s.includes("missing wind")));
  assert.ok(flags.some((s) => s.includes("combined seas unavailable")));
});
test("future calendar dates follow Pacific midnight and DST", () => {
  assert.equal(futureDates(new Date("2026-09-21T02:00:00Z"))[0], "2026-09-21");
  assert.deepEqual(futureDates(new Date("2026-11-01T08:30:00Z")).slice(0, 2), [
    "2026-11-02",
    "2026-11-03",
  ]);
  assert.equal(compass(null), "unavailable");
  assert.equal(compass(360), "N");
});
test("selected GPX keeps polygon holes as separate segments and rejects unknown IDs", () => {
  const a = JSON.parse(
    readFileSync(new URL("../dist/data/atlas.json", import.meta.url)),
  );
  const t = a.targets.find((t) => t.drift_id);
  const gpx = targetGPX(a, t.id);
  assert.ok(gpx.includes(`<name>${t.name}</name>`));
  assert.ok(gpx.includes("Not a navigation route."));
  assert.equal((gpx.match(/<wpt /g) || []).length, 1);
  assert.ok(!gpx.includes("<rte>"));
  assert.throws(() => targetGPX(a, "not-a-target"), /Unknown target/);
  const clone = structuredClone(a);
  clone.areas = clone.areas.filter((x) => t.area_ids.includes(x.id));
  clone.areas[0].geometry = {
    type: "Polygon",
    coordinates: [
      [
        [1, 2],
        [3, 4],
        [1, 2],
      ],
      [
        [1.1, 2.1],
        [1.2, 2.2],
        [1.1, 2.1],
      ],
    ],
  };
  clone.drifts = [];
  const output = targetGPX(clone, t.id);
  assert.equal((output.match(/<trkseg>/g) || []).length, 2);
});

test("timezone and latest-run coverage are checked independently of populated values", () => {
  const f = {
    timezone: "UTC",
    hourly: { time: ["2026-09-21T08:00"], wave_height_ecmwf_wam025: [2] },
    hourly_units: { wave_height_ecmwf_wam025: "ft" },
  };
  assert.equal(
    valueAt(f, "ecmwf_wam025", "wave_height", "2026-09-21T08:00", "ft"),
    null,
  );
  assert.equal(
    pacificEpoch("2026-09-21T08:00"),
    Date.parse("2026-09-21T15:00:00Z") / 1000,
  );
  assert.equal(
    pacificEpoch("2026-11-02T08:00"),
    Date.parse("2026-11-02T16:00:00Z") / 1000,
  );
  assert.match(
    coverageNote(
      { data_end_time: Date.parse("2026-09-21T14:00:00Z") / 1000 },
      "2026-09-21T08:00",
    ),
    /Beyond/,
  );
  assert.equal(
    coverageNote(
      { data_end_time: Date.parse("2026-09-21T16:00:00Z") / 1000 },
      "2026-09-21T08:00",
    ),
    null,
  );
});
