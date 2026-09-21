import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { matchingGrounds, reportSummary } from "../dist/charter-grounds.js";

const evidence = JSON.parse(
  readFileSync(new URL("../dist/data/charter-grounds.json", import.meta.url)),
);
const atlas = JSON.parse(
  readFileSync(new URL("../dist/data/atlas.json", import.meta.url)),
);

test("combined reef view includes either species without counting a trip twice", () => {
  const combined = matchingGrounds(evidence.grounds, { species: "reef" });
  const union = new Set(["lingcod", "rockfish"].flatMap((species) => matchingGrounds(evidence.grounds, { species }).map((g) => g.id)));
  assert.deepEqual(new Set(combined.map((g) => g.id)), union);
  for (const ground of combined) {
    assert.equal(reportSummary(ground, "reef").trips, ground.reports.filter((r) => r.species.includes("lingcod") || r.species.includes("rockfish")).length);
  }
});

test("reported grounds preserve provenance, counts and uncertainty without changing terrain", () => {
  const coverage = evidence.coverage;
  assert.equal(
    coverage.local_trips,
    Object.values(coverage.ground_counts).reduce((a, b) => a + b, 0),
  );
  assert.equal(
    coverage.dates_available,
    coverage.pages.filter((p) => p.status === "ok").length,
  );
  assert.equal(
    new Set(coverage.pages.map((p) => p.date)).size,
    coverage.dates_checked,
  );
  assert.equal(
    coverage.mapped_single_ground_trips,
    evidence.grounds.reduce((s, g) => s + g.reports.length, 0),
  );
  const dates = new Set(
    coverage.pages.filter((p) => p.status === "ok").map((p) => p.date),
  );
  for (const ground of evidence.grounds) {
    assert.equal(ground.report_count, ground.reports.length);
    assert.equal(
      new Set(ground.reports.map((r) => `${r.date}:${r.boat}`)).size,
      ground.report_count,
    );
    assert.equal(ground.ais_verified, false);
    assert.equal(ground.exact_position_published, false);
    assert.equal(ground.depth_of_reported_trips, null);
    assert.equal(ground.catch_probability, null);
    assert.ok(ground.depth_ft[0] >= 25 && ground.depth_ft[1] <= 195);
    assert.equal(ground.latest_report, [...ground.report_dates].sort().at(-1));
    assert.ok(["Polygon", "MultiPolygon"].includes(ground.geometry.type));
    assert.ok(
      !["Out Front", "Point Sal", "Purisima Point", "Shell Beach"].includes(
        ground.reported_ground,
      ),
    );
    for (const r of ground.reports) {
      assert.ok(dates.has(r.date));
      const url = new URL(r.source_url);
      assert.equal(url.hostname, "www.socalfishreports.com");
      assert.equal(url.searchParams.get("date"), r.date);
    }
    for (const id of ground.nearby_target_ids)
      assert.ok(atlas.targets.some((t) => t.id === id));
  }
});

test("incidental catches do not turn broad bottom-fishing reports into species hotspots", () => {
  for (const species of [
    "halibut",
    "salmon",
    "bluefin",
    "albacore",
    "dungeness",
  ])
    assert.deepEqual(matchingGrounds(evidence.grounds, { species }), []);
  assert.equal(
    matchingGrounds(evidence.grounds, { species: "rockfish" }).length,
    3,
  );
  assert.equal(
    matchingGrounds(evidence.grounds, { species: "lingcod" }).length,
    3,
  );
  const diablo = evidence.grounds.find((g) => g.id === "CHARTER-DIABLO");
  assert.ok(diablo.reports.some((r) => r.species.includes("halibut")));
  assert.ok(reportSummary(diablo, "lingcod").trips < diablo.report_count);
  assert.deepEqual(reportSummary(diablo, "albacore"), {
    trips: 0,
    dates: 0,
    boats: [],
    latest: null,
  });
});

test("search includes boats, area and whole-outline depth filters exclude unsupported water", () => {
  assert.deepEqual(
    matchingGrounds(evidence.grounds, {
      species: "rockfish",
      search: "  flying FISH ",
    }).map((g) => g.id),
    ["CHARTER-PECHO"],
  );
  assert.deepEqual(
    matchingGrounds(evidence.grounds, {
      species: "rockfish",
      area: "PointEstero",
    }),
    [],
  );
  assert.deepEqual(
    matchingGrounds(evidence.grounds, { species: "rockfish", depth: 100 }),
    [],
  );
  assert.deepEqual(
    matchingGrounds(evidence.grounds, { species: "rockfish", depth: 150 }).map(
      (g) => g.id,
    ),
    ["CHARTER-PECHO"],
  );
});

test("a same-day report from another boat counts as a trip, not another date", () => {
  const morro = evidence.grounds.find((g) => g.id === "CHARTER-MORRO");
  assert.equal(morro.report_count, 14);
  assert.equal(morro.report_dates.length, 10);
  assert.equal(reportSummary(morro, "rockfish").trips, 14);
  assert.equal(reportSummary(morro, "rockfish").dates, 10);
});
