import test from "node:test";
import assert from "node:assert/strict";
import {
  reportEvidence,
  nearestGrid,
  validFeed,
  evidenceHTML,
} from "../dist/bite-evidence.js";
const now = Date.parse("2026-09-21T16:00:00Z");
function feed() {
  const data = {
    schema_version: 1,
    generated_at: new Date(now).toISOString(),
    sources: {},
    reports: [],
    health: {},
    catch_probability: null,
    bite_score: null,
  };
  for (let i = 1; i <= 7; i++) {
    const date = `2026-09-${21 - i}`;
    data.sources["catches-" + date] = {
      status: "ok",
      data_retrieved_at: data.generated_at,
    };
    data.reports.push({
      id: String(i),
      date,
      boat: "Boat " + (i % 2),
      catches: [{ species: "lingcod", count: 2 }],
      ground_id: null,
    });
  }
  return data;
}
test("evidence confidence needs fresh coverage and is not catch probability", () => {
  const data = feed();
  assert.ok(validFeed(data));
  assert.equal(reportEvidence(data, "lingcod", now).confidence, "Moderate");
  assert.equal(reportEvidence(data, "lingcod", now).catch_probability, null);
  data.sources["catches-2026-09-20"].status = "retained";
  assert.equal(reportEvidence(data, "lingcod", now).confidence, "Low");
  assert.equal(
    reportEvidence(data, "lingcod", now + 40 * 3600000).confidence,
    "Low",
  );
  assert.equal(reportEvidence(data, "halibut", now).confidence, "Insufficient");
});
test("port reports and zero counts do not establish a named ground or presence", () => {
  const data = feed();
  assert.equal(
    reportEvidence(data, "lingcod", now, "CHARTER-PECHO").reports.length,
    0,
  );
  for (const r of data.reports) r.catches[0].count = 0;
  assert.equal(reportEvidence(data, "lingcod", now).confidence, "Insufficient");
});
test("ocean samples preserve cloud gaps and source time rather than nearest available water", () => {
  const source = {
    status: "ok",
    max_age_hours: 96,
    data: {
      samples: [
        {
          latitude: 35.3,
          longitude: -121.5,
          time: "2026-09-20T12:00:00Z",
          chlorophyll: null,
        },
        {
          latitude: 35.34,
          longitude: -121.5,
          time: "2026-09-20T12:00:00Z",
          chlorophyll: 2,
        },
      ],
    },
  };
  assert.equal(
    nearestGrid(
      source,
      { latitude: 35.3, longitude: -121.5 },
      "chlorophyll",
      now,
    ).usable,
    false,
  );
  source.data.samples[0].chlorophyll = 1;
  source.status = "retained";
  assert.equal(
    nearestGrid(
      source,
      { latitude: 35.3, longitude: -121.5 },
      "chlorophyll",
      now,
    ).fresh,
    false,
  );
});
test("untrusted report text cannot add executable markup", () => {
  const data = feed();
  data.generated_at = new Date().toISOString();
  const date = new Date(Date.now() - 86400000).toISOString().slice(0, 10);
  data.reports = [
    {
      date,
      boat: "<img src=x onerror=alert(1)>",
      catches: [{ species: "lingcod", count: 1, label: "Lingcod" }],
      source_url: "javascript:alert(1)",
      port: "Morro Bay",
      anglers: null,
    },
  ];
  const rendered = evidenceHTML(data, "lingcod", {
    name: "Estero Bay",
    latitude: 35.36,
    longitude: -120.94,
  });
  assert.ok(!rendered.includes("<img"));
  assert.ok(!rendered.includes('href="javascript:'));
});
