import test from "node:test";
import assert from "node:assert/strict";
import { existsSync, readFileSync, readdirSync } from "node:fs";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
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

// Prove the filter itself, not just that git deleted the old source files.
test("the static copy omits stale GPX but preserves neighboring downloads", async (t) => {
  const { copyStatic } = await import("../scripts/client-build.mjs");
  const root = await mkdtemp(join(tmpdir(), "sc-downloads-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const src = join(root, "src"), out = join(root, "out");
  await mkdir(join(src, "downloads", "targets"), { recursive: true });
  for (const name of ["complete.gpx", "targets/SC26-001.gpx", "LICENSE.txt", "spot-notes.html"]) {
    await writeFile(join(src, "downloads", name), name);
  }
  await copyStatic(src, out);
  const download = join(out, "downloads");
  assert.deepEqual(readdirSync(download, { recursive: true }).filter((name) => /\.gpx$/i.test(name)), []);
  for (const name of ["LICENSE.txt", "spot-notes.html"]) {
    assert.equal(readFileSync(join(download, name), "utf8"), name);
  }
});

// Neither the shipping tree nor an install/offline pack list may restore the files.
test("the client build and its precache and offline pack lists contain no GPX", () => {
  const source = new URL("../dist/downloads/", import.meta.url);
  assert.deepEqual(readdirSync(source, { recursive: true }).filter((name) => /\.gpx$/i.test(name)), []);
  const client = new URL("../dist/client/", import.meta.url);
  if (!existsSync(client)) return; // Some source-only CI steps run before pnpm build.
  assert.deepEqual(readdirSync(client, { recursive: true }).filter((name) => /\.gpx$/i.test(name)), []);
  const manifest = JSON.parse(readFileSync(new URL("precache.json", client)));
  for (const paths of [manifest.shells, manifest.assets, manifest.static, manifest.warm, manifest.v2.assets, manifest.v2.static]) {
    assert.ok(paths.every((path) => !/\.gpx(?:[?#]|$)/i.test(path)));
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
    hourly: { time: ["2026-09-21T08:00"], wave_height_ecmwf_wam: [2] },
    hourly_units: { wave_height_ecmwf_wam: "ft" },
  };
  assert.equal(
    valueAt(f, "ecmwf_wam", "wave_height", "2026-09-22T08:00", "ft"),
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
        [2, 4],
        [1, 2],
      ],
      [
        [1.1, 2.1],
        [1.2, 2.2],
        [1.1, 2.2],
        [1.1, 2.1],
      ],
    ],
  };
  clone.drifts = [];
  clone.targets.find(x=>x.id===t.id).drift_id=null;
  const output = targetGPX(clone, t.id);
  assert.equal((output.match(/<trkseg>/g) || []).length, 2);
});

test("timezone and latest-run coverage are checked independently of populated values", () => {
  const f = {
    timezone: "UTC",
    hourly: { time: ["2026-09-21T08:00"], wave_height_ecmwf_wam: [2] },
    hourly_units: { wave_height_ecmwf_wam: "ft" },
  };
  assert.equal(
    valueAt(f, "ecmwf_wam", "wave_height", "2026-09-21T08:00", "ft"),
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
