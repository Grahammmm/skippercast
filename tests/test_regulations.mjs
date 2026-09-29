import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { regulationState, regulationsHTML, validRegulations, officialURL, areaNoticesHTML, ruleSummary, ruleSummaryHTML, firstClause, depthLimit } from "../dist/regulations.js";
const now = Date.parse("2026-09-21T18:00:00Z");
const original = JSON.parse(readFileSync(new URL("../dist/data/regulations.json", import.meta.url), "utf8"));
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
    (d) => d.checks["rules-salmon"].url = "https://wildlife.ca.gov/another-document",
    (d) => d.checks["rules-salmon"].normalization = "old-parser",
    (d) => d.checks["rules-salmon"].data_retrieved_at = "2026-09-19T00:00:00Z",
  ]) {
    const d = data(); edit(d);
    assert.equal(regulationState(d, "salmon", now).status, "unknown");
    assert.equal(regulationState(d, "lingcod", now).status, "open");
  }
});

test("unreviewed legal content withholds open and ancillary access notices stay separate", () => {
  const d = data(); d.rules_review_status = 'content-needs-review';
  assert.equal(regulationState(d, 'lingcod', now).status, 'unknown');
  const southern = JSON.parse(readFileSync(new URL('../dist/regions/southern-california/regulations.json', import.meta.url), 'utf8'));
  southern.checks['rules-navy-sci'].status = 'unavailable';
  const html = areaNoticesHTML(southern, Date.parse(southern.reviewed_at));
  assert.match(html, /Area rules &amp; island access/);
  assert.match(html, /Current operational clearance has not been verified/);
  assert.match(html, /https:\/\/www.ecfr.gov\/current\/title-33/);
  assert.match(officialURL('https://fgc.ca.gov/Regulations/2026-New-and-Proposed'), /^https:\/\/fgc.ca.gov/);
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

test('latitude-limited seasons check the entire selected fishing geometry', () => {
  const d=data();
  d.species.salmon.windows[0].geography={kind:'latitude-band',south:35.0,north:35.4,source_id:'rules-salmon',note:'Open only between reviewed latitude lines.'};
  const location=(latitude,geometry=null)=>({coverage:'covered',regionId:'morro-bay',point:{latitude,longitude:-120.9,geometry},protection:{status:'clear'}});
  assert.equal(regulationState(d,'salmon',now).status,'unknown');
  assert.equal(regulationState(d,'salmon',now,null,'rod',null,location(35.2)).status,'open');
  const north=regulationState(d,'salmon',now,null,'rod',null,location(35.5));
  assert.equal(north.status,'closed');
  assert.match(north.reason,/outside the area opened/);
  const crossing={type:'Polygon',coordinates:[[[-121,35.35],[-120.8,35.35],[-120.8,35.45],[-121,35.45],[-121,35.35]]]};
  assert.equal(regulationState(d,'salmon',now,null,'rod',null,location(35.38,crossing)).status,'unknown');
  d.checks['rules-salmon'].status='changed';
  assert.equal(regulationState(d,'salmon',now,null,'rod',null,location(35.2)).status,'unknown');
  d.species.salmon.windows[0].geography.north=91;
  assert.equal(validRegulations(d),false);
});

test("summary row leads the card with status, bag, size, depth, verified date and one link", () => {
  const d = data();
  const html = regulationsHTML(d, "halibut", now);
  const row = html.indexOf('class="reg-summary-row"');
  assert.ok(row > 0 && row < html.indexOf("reg-notice"), "row comes before the existing detail");
  assert.match(html, /<dl class="reg-limits"><dt>Season<\/dt>/, "existing detail is still rendered");
  const s = ruleSummary(d, "halibut", regulationState(d, "halibut", now));
  assert.equal(s.label, "Open");
  assert.deepEqual(s.bag, ["5 per person daily"]);
  assert.deepEqual(s.size, ["22 in min total length"]);
  assert.equal(s.verified, "Sep 21");
  assert.match(s.link, /^https:\/\/wildlife\.ca\.gov\//);
  assert.equal((ruleSummaryHTML(s).match(/<a /g) || []).length, 1, "exactly one official link");
  const lingcod = ruleSummary(d, "lingcod", regulationState(d, "lingcod", now));
  assert.equal(lingcod.depth, "All depths");
  const reef = ruleSummary(d, "reef", regulationState(d, "reef", now));
  assert.deepEqual(reef.bag.map((b) => b.split(":")[0]), ["Lingcod", "Rockfish / rock cod"]);
  assert.equal(reef.linkLabel, "Official groundfish rules");
  assert.equal((regulationsHTML(d, "reef", now).match(/reg-summary-row/g) || []).length, 1, "member cards do not repeat the row");
});

test("summary row keeps the fail-closed status and never claims verification", () => {
  const d = data();
  d.checks[d.species.halibut.source_ids[0]].status = "changed";
  const state = regulationState(d, "halibut", now);
  const s = ruleSummary(d, "halibut", state);
  assert.equal(s.status, "unknown");
  assert.equal(s.label, "Check rules");
  assert.equal(s.verified, null);
  assert.equal(s.depth, null);
  assert.match(ruleSummaryHTML(s), /Needs recheck · last check Sep 21/);
  assert.doesNotMatch(ruleSummaryHTML(s), />Open</);
  const stale = data(now - 48 * 3600000);
  const staleSummary = ruleSummary(stale, "lingcod", regulationState(stale, "lingcod", now));
  assert.equal(staleSummary.label, "Check rules");
  assert.equal(staleSummary.verified, null);
  const missing = ruleSummary(null, "salmon", regulationState(null, "salmon", now));
  assert.equal(missing.label, "Check rules");
  assert.deepEqual(missing.bag, []);
  assert.equal(missing.link, "https://wildlife.ca.gov/Fishing/Ocean");
  assert.match(regulationsHTML(null, "salmon", now), /reg-summary-row[\s\S]*Check rules[\s\S]*Official CDFW rules/);
  const unreviewed = data(); unreviewed.rules_review_status = "content-needs-review";
  assert.equal(ruleSummary(unreviewed, "halibut", regulationState(unreviewed, "halibut", now)).verified, null);
});

test("summary text is cut from the reviewed wording, never rewritten, and depth comes from structured access", () => {
  assert.equal(firstClause("2 per person daily; 2 in possession."), "2 per person daily");
  assert.equal(firstClause("22 in minimum total length."), "22 in min total length");
  assert.match(firstClause("5 total kelp, barred sand and spotted sand bass combined, with no more than 4 barred sand bass."), /…$|exceptions below/);
  assert.match(firstClause("14 in minimum total length (or the regulation's defined 10 in alternate length)."), /^14 in min total length \(exceptions below\)$/);
  assert.equal(firstClause(""), null);
  const southern = JSON.parse(readFileSync(new URL("../dist/regions/southern-california/regulations.json", import.meta.url), "utf8"));
  assert.equal(depthLimit(southern.species.lingcod, "2026-08-01"), "Inside 50-fm line");
  assert.equal(depthLimit(southern.species.lingcod, "2026-11-01"), "Outside 50-fm line");
  assert.equal(depthLimit(southern.species.lingcod, "2026-05-01"), "All depths");
  assert.equal(depthLimit(southern.species.lingcod, "2026-02-01"), null, "no active window, no depth claim");
  assert.equal(depthLimit(southern.species.halibut, "2026-05-01"), null, "no depth wording, no depth claim");
});

test("summary escapes registry text", () => {
  const d = data(); d.species.halibut.bag = '<b onmouseover="x()">5</b> per person daily';
  assert.doesNotMatch(ruleSummaryHTML(ruleSummary(d, "halibut", regulationState(d, "halibut", now))), /<b /);
});
