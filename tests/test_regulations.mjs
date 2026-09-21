import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { regulationState, regulationsHTML, validRegulations, officialURL } from "../dist/regulations.js";
const now = Date.parse("2026-09-21T18:00:00Z");
const original = JSON.parse(readFileSync(new URL("../dist/data/regulations.json", import.meta.url), "utf8"));
function data(at = now) {
  const d = structuredClone(original);
  for (const [id, source] of Object.entries(d.sources)) {
    source.approved_content_sha256 = "a".repeat(64);
    d.checks[id] = { status: "unchanged", source_status: "ok", content_sha256: "a".repeat(64), data_retrieved_at: new Date(at).toISOString() };
  }
  return d;
}
test("all seven species have local limits and correct initial season states", () => {
  const d = data();
  assert.ok(validRegulations(d));
  for (const id of Object.keys(d.species)) {
    const state = regulationState(d, id, now);
    assert.equal(state.status, id === "dungeness" ? "closed" : "open");
    assert.match(regulationsHTML(d, id, now), /Daily \/ possession limit/);
  }
  assert.match(d.species.halibut.bag, /^5 /);
  assert.match(d.species.albacore.bag, /^25 /);
  assert.match(d.species.rockfish.details.join(" "), /1 copper, 2 canary/);
});
test("seasons roll at Pacific midnight; crab does not auto-authorize traps", () => {
  for (const [date, species, expected] of [
    ["2026-10-01T06:59:00Z", "salmon", "open"],
    ["2026-10-01T07:00:00Z", "salmon", "closed"],
    ["2026-11-07T08:00:00Z", "dungeness", "scheduled"],
    ["2027-01-01T08:00:00Z", "lingcod", "unknown"],
  ]) {
    const at = Date.parse(date);
    assert.equal(regulationState(data(at), species, at).status, expected);
  }
});
test("stale, changed, missing, retained, unreviewed and mismatched evidence withhold open", () => {
  for (const edit of [
    (d) => d.checks["rules-salmon"].status = "changed",
    (d) => delete d.checks["rules-salmon"],
    (d) => d.checks["rules-salmon"].source_status = "retained",
    (d) => d.sources["rules-salmon"].approved_content_sha256 = null,
    (d) => d.checks["rules-salmon"].content_sha256 = "b".repeat(64),
    (d) => d.checks["rules-salmon"].data_retrieved_at = "2026-09-19T00:00:00Z",
  ]) {
    const d = data(); edit(d);
    assert.equal(regulationState(d, "salmon", now).status, "unknown");
    assert.equal(regulationState(d, "lingcod", now).status, "open");
  }
});
test("unavailable or malformed registry still gives official links", () => {
  assert.equal(regulationState(null, "salmon", now).status, "unknown");
  assert.match(regulationsHTML(null, "salmon", now), /https:\/\/wildlife.ca.gov\/Fishing\/Ocean/);
  const d = data(); delete d.species.bluefin;
  assert.ok(!validRegulations(d));
});
test("data is escaped and links stay on official sources", () => {
  const d = data(); d.species.lingcod.name = '<img src=x onerror="bad()">';
  const html = regulationsHTML(d, "lingcod", now);
  assert.ok(!html.includes('<img'));
  assert.match(html, /&lt;img/);
  assert.equal(officialURL("javascript:alert(1)"), "https://wildlife.ca.gov/Fishing/Ocean");
  assert.equal(officialURL("https://wildlife.ca.gov.attacker.example/"), "https://wildlife.ca.gov/Fishing/Ocean");
});

test("combined reef selector keeps both legal limits and does not mask an unverified species", () => {
  const d = data();
  assert.equal(regulationState(d, "reef", now).status, "open");
  const html = regulationsHTML(d, "reef", now);
  assert.match(html, /2 per person daily/);
  assert.match(html, /10 total rockfish, cabezon and greenlings/);
  assert.match(html, /22 in minimum/);
  assert.match(html, /Keep the limits separate/);
  d.checks["rules-groundfish"].status = "changed";
  assert.equal(regulationState(d, "reef", now).status, "unknown");
  assert.equal(regulationState(null, "reef", now).status, "unknown");
});
