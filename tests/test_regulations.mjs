// The reviewed rules registry read through web/regs.ts (FE-61 moved these from
// v1's dist/regulations.js, deleted with the v1 shell; its HTML card, gear
// methods and fishing-location check went with it).
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { regulationState, validRegulations, officialURL, ruleProfile, ruleSummary, firstClause, depthLimit } from "../web/regs.ts";
const now = Date.parse("2026-09-21T18:00:00Z");
const read = path => JSON.parse(readFileSync(new URL(`../dist/${path}`, import.meta.url), "utf8"));
const original = read("data/regulations.json");
const region = read("regions/morro-bay/region.json");
const state = (d, id, at = now) => regulationState(d, id, region, at);
const summary = (d, id, at = now) => ruleSummary(d, id, state(d, id, at), region);
function data(at = now) {
  const d = structuredClone(original);
  d.reviewed_at = new Date(at - 3600000).toISOString();
  d.rules_review_status = "reviewed";
  for (const [id, source] of Object.entries(d.sources)) {
    source.approved_content_sha256 = "a".repeat(64);
    d.checks[id] = { url: source.url, normalization: source.normalization, status: "unchanged", source_status: "ok", content_sha256: "a".repeat(64), data_retrieved_at: new Date(at).toISOString() };
  }
  return d;
}
test("all seven species have local limits and correct initial season states", () => {
  const d = data();
  assert.ok(validRegulations(d, region));
  for (const id of Object.keys(d.species)) assert.equal(state(d, id).status, id === "dungeness" ? "closed" : "open");
  assert.match(d.species.halibut.bag, /^5 /);
  assert.match(d.species.albacore.bag, /^25 /);
  assert.match(d.species.rockfish.details.join(" "), /1 copper, 2 canary/);
});
test("seasons roll at Pacific midnight; crab is only scheduled", () => {
  for (const [date, species, expected] of [
    ["2026-10-01T06:59:00Z", "salmon", "open"],
    ["2026-10-01T07:00:00Z", "salmon", "closed"],
    ["2026-11-07T08:00:00Z", "dungeness", "scheduled"],
    ["2027-01-01T08:00:00Z", "lingcod", "unknown"],
  ]) {
    const at = Date.parse(date);
    assert.equal(state(data(at), species, at).status, expected);
  }
});
test("stale, changed, missing, retained, unreviewed and mismatched evidence withhold open", () => {
  for (const edit of [
    (d) => d.checks["rules-salmon"].status = "changed",
    (d) => delete d.checks["rules-salmon"],
    (d) => d.checks["rules-salmon"].source_status = "retained",
    (d) => d.sources["rules-salmon"].approved_content_sha256 = null,
    (d) => d.checks["rules-salmon"].content_sha256 = "b".repeat(64),
    (d) => d.checks["rules-salmon"].url = "https://wildlife.ca.gov/another-document",
    (d) => d.checks["rules-salmon"].normalization = "old-parser",
    (d) => d.checks["rules-salmon"].data_retrieved_at = "2026-09-19T00:00:00Z",
  ]) {
    const d = data(); edit(d);
    assert.equal(state(d, "salmon").status, "unknown");
    assert.equal(state(d, "lingcod").status, "open");
  }
});
test("unreviewed legal content withholds open; links stay on official sources", () => {
  const d = data(); d.rules_review_status = 'content-needs-review';
  assert.equal(state(d, 'lingcod').status, 'unknown');
  assert.equal(officialURL("javascript:alert(1)", region), "https://wildlife.ca.gov/Fishing/Ocean");
  assert.equal(officialURL("https://wildlife.ca.gov.attacker.example/", region), "https://wildlife.ca.gov/Fishing/Ocean");
});
test("an unavailable or incomplete registry is unknown", () => {
  assert.equal(state(null, "salmon").status, "unknown");
  const d = data(); delete d.species.bluefin;
  assert.ok(!validRegulations(d, region));
});
test("combined reef selector keeps both legal limits and does not mask an unverified species", () => {
  const d = data();
  assert.equal(state(d, "reef").status, "open");
  assert.deepEqual(summary(d, "reef").bag.map((b) => b.split(":")[0]), ["Lingcod", "Rockfish / rock cod"]);
  d.checks["rules-groundfish"].status = "changed";
  assert.equal(state(d, "reef").status, "unknown");
  assert.equal(state(null, "reef").status, "unknown");
});
test('a latitude-limited season asks for a fishing location and its band is validated', () => {
  const d = data();
  d.species.salmon.windows[0].geography = {kind: 'latitude-band', south: 35.0, north: 35.4, source_id: 'rules-salmon', note: 'Open only between reviewed latitude lines.'};
  assert.equal(state(d, 'salmon').status, 'unknown');
  assert.equal(state(d, 'salmon').label, 'Choose fishing location');
  d.species.salmon.windows[0].geography.north = 91;
  assert.equal(validRegulations(d, region), false);
});
test("summary leads with status, bag, size, depth, verified date and one link", () => {
  const d = data();
  const s = summary(d, "halibut");
  assert.equal(s.label, "Open");
  assert.deepEqual(s.bag, ["5 per person daily"]);
  assert.deepEqual(s.size, ["22 in min total length"]);
  assert.equal(s.verified, "Sep 21");
  assert.match(s.link, /^https:\/\/wildlife\.ca\.gov\//);
  assert.equal(summary(d, "lingcod").depth, "All depths");
  assert.equal(summary(d, "reef").linkLabel, "Official groundfish rules");
});
test("summary keeps the fail-closed status and never claims verification", () => {
  const d = data();
  d.checks[d.species.halibut.source_ids[0]].status = "changed";
  const s = summary(d, "halibut");
  assert.equal(s.status, "unknown");
  assert.equal(s.label, "Check rules");
  assert.equal(s.verified, null);
  assert.equal(s.checked, "Sep 21");
  assert.equal(s.depth, null);
  const stale = data(now - 48 * 3600000);
  assert.equal(summary(stale, "lingcod").label, "Check rules");
  assert.equal(summary(stale, "lingcod").verified, null);
  const missing = summary(null, "salmon");
  assert.equal(missing.label, "Check rules");
  assert.deepEqual(missing.bag, []);
  assert.equal(missing.link, "https://wildlife.ca.gov/Fishing/Ocean");
  const unreviewed = data(); unreviewed.rules_review_status = "content-needs-review";
  assert.equal(summary(unreviewed, "halibut").verified, null);
});
test("summary text is cut from the reviewed wording, never rewritten, and depth comes from structured access", () => {
  assert.equal(firstClause("2 per person daily; 2 in possession."), "2 per person daily");
  assert.equal(firstClause("22 in minimum total length."), "22 in min total length");
  assert.match(firstClause("5 total kelp, barred sand and spotted sand bass combined, with no more than 4 barred sand bass."), /…$|exceptions below/);
  assert.match(firstClause("14 in minimum total length (or the regulation's defined 10 in alternate length)."), /^14 in min total length \(exceptions below\)$/);
  assert.equal(firstClause(""), null);
  const southern = read("regions/southern-california/regulations.json");
  assert.equal(depthLimit(southern.species.lingcod, "2026-08-01"), "Inside 50-fm line");
  assert.equal(depthLimit(southern.species.lingcod, "2026-11-01"), "Outside 50-fm line");
  assert.equal(depthLimit(southern.species.lingcod, "2026-05-01"), "All depths");
  assert.equal(depthLimit(southern.species.lingcod, "2026-02-01"), null, "no active window, no depth claim");
  assert.equal(depthLimit(southern.species.halibut, "2026-05-01"), null, "no depth wording, no depth claim");
});
test('unsupported and inherited target identities remain unknown in state and summary', () => {
  const d = data();
  for (const id of ['constructor', 'toString', '__proto__', '', 'unsupported-target']) {
    assert.equal(ruleProfile(d, id, region), null, id);
    const s = state(d, id);
    assert.equal(s.status, 'unknown'); assert.equal(s.profile, undefined);
    const row = ruleSummary(d, id, s, region);
    assert.deepEqual(row.bag, []); assert.deepEqual(row.size, []); assert.equal(row.depth, null); assert.equal(row.verified, null);
  }
  const inherited = Object.create({borrowed: d.species.lingcod}); Object.assign(inherited, d.species);
  assert.equal(state({...d, species: inherited}, 'borrowed').status, 'unknown');
  const malformed = {...d, species: {...d.species, broken: {name: 'Broken'}}};
  assert.equal(state(malformed, 'broken').status, 'unknown');
});
