// SCA-543 / F13-05: one synthetic rules check, rendered by the three real cards.
// Required suite: node --test tests/test_f13_05_audit.mjs
// Read-only contract replay: node tests/test_f13_05_audit.mjs --audit
// The replay must fail on an affected baseline and pass once SCA-200 fixes it.
// A known restriction is a separate historical note on the two cards that
// already explain the rule; it is not a confirmed status or a current limit.
import assert from 'node:assert/strict';
import {mkdtemp, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {fileURLToPath, pathToFileURL} from 'node:url';
import {after, before, test} from 'node:test';
import {build} from 'esbuild';
import {rendererPlugins} from './helpers/esbuild-url.mjs';

const NOW = Date.parse('2026-10-12T18:00:00Z'), DAY = '2026-10-12', HOUR = 3_600_000;
const AUTHORITY = 'https://authority.example.test/audit-rules';
const SPECIES = 'lingcod', REGION = {id: 'morro-bay', timezone: 'America/Los_Angeles', species: [SPECIES],
  regulatory_authority_hosts: [new URL(AUTHORITY).hostname]};
const BAG = 'Synthetic bag clause', SIZE = 'Synthetic size clause', DEPTH = 'Inside 50-fm line';
const RESTRICTION = 'Synthetic gear restriction';
const HASH = 'a'.repeat(64);
const SOURCE = {url: AUTHORITY, normalization: 'synthetic', approved_content_sha256: HASH};
const iso = hours => new Date(NOW - hours * HOUR).toISOString();
const registry = (hours, restricted) => ({
  schema_version: 1, rules_review_status: 'reviewed', reviewed_at: iso(31),
  valid_from: '2026-10-01', valid_through: '2026-10-31', common_notes: [],
  check_interval_hours: 24, max_age_hours: 36,
  sources: {audit: SOURCE},
  checks: {audit: {url: AUTHORITY, normalization: SOURCE.normalization, status: 'unchanged', source_status: 'ok',
    content_sha256: HASH, data_retrieved_at: iso(hours)}},
  species: {[SPECIES]: {name: 'Synthetic lingcod', season: 'Synthetic open season', bag: BAG, size: SIZE,
    details: [], source_ids: ['audit'], windows: [{start: '2026-10-01', end: '2026-10-31', access: 'shoreward-50fm',
      ...(restricted ? {restriction: RESTRICTION} : {})}]}},
});

let ui, dir;
before(async () => {
  dir = await mkdtemp(join(tmpdir(), 'f13-05-'));
  const out = join(dir, 'ui.mjs');
  await build({stdin: {resolveDir: fileURLToPath(new URL('..', import.meta.url)), loader: 'ts', contents: `
    export {PlanRules} from './web/app/PlanRules.tsx';
    export {TargetRules} from './web/app/PlanView.tsx';
    export {RulesLine} from './web/app/RulesCard.tsx';
    export {regionInfo} from './web/app/region-info.ts';
    export {markData} from './web/map/marks.ts';
    export {regsData, regulationState} from './web/regs.ts';
    export {configureStore, syncFromURL} from './web/state.ts';
    export {render} from 'preact-render-to-string'; export {h} from 'preact';`},
  bundle: true, platform: 'node', format: 'esm', outfile: out, jsx: 'automatic', jsxImportSource: 'preact', plugins: rendererPlugins});
  ui = await import(pathToFileURL(out).href);
  ui.configureStore({v2: true, storage: null});
  ui.syncFromURL(`https://skippercast.test/map?region=${REGION.id}&profile=boat&target=${SPECIES}`);
  ui.regionInfo.value = {...REGION, rules: REGION};
  ui.markData.value = {region: REGION};
});
after(async () => { if (dir) await rm(dir, {recursive: true, force: true}); });

const plain = html => html.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim();
function observe(html) {
  const text = plain(html);
  return {
    badge: html.match(/<span\b[^>]*\bapp-mark-regs-badge\b[^>]*>([^<]*)<\/span>/)?.[1],
    authority: [...html.matchAll(/<a\b[^>]*\bhref="([^"]*)"/g)].some(([, href]) => href === AUTHORITY),
    bag: text.includes(BAG), size: text.includes(SIZE), depth: text.includes(DEPTH),
  };
}

function control(label, hours, overdue, expected, restricted = false) {
  test(label, async t => {
    t.mock.timers.enable({apis: ['Date'], now: NOW});
    const fetch = t.mock.method(globalThis, 'fetch', () => { throw Error('offline fixture: unexpected fetch'); });
    const data = registry(hours, restricted);
    const {status, issues, overdue: scheduledRecheck} = ui.regulationState(data, SPECIES, REGION, NOW, DAY, NOW);
    assert.deepEqual({status, issues, scheduledRecheck}, {status: restricted ? 'restricted' : 'open', issues: [], scheduledRecheck: overdue},
      'the synthetic source is reviewed, unchanged and inside the hard ceiling');
    ui.regsData.value = {region: REGION.id, data};
    const {h, render, PlanRules, TargetRules, RulesLine} = ui;
    const cards = [
      ['trip planner', h(PlanRules, {date: DAY, species: SPECIES, region: REGION, now: NOW})],
      ['plan view', h(TargetRules, {now: new Date(NOW)})],
      ['selected mark', h(RulesLine, {mark: {id: 'spot:synthetic'}})],
    ];
    for (const [name, card] of cards) {
      await t.test(name, () => {
        const html = render(card);
        const observed = observe(html), want = {...expected};
        if (restricted && name !== 'selected mark') {
          // Require a label next to the actual saved rule, not merely a generic freshness caveat elsewhere.
          observed.lastKnown = new RegExp(`\\b(?:last[- ]known|last[- ]reviewed|saved)\\s+restriction\\s*[:.–-]?\\s*${RESTRICTION}`, 'i').test(plain(html));
          want.lastKnown = true;
        }
        assert.deepEqual(observed, want);
      });
    }
    assert.equal(fetch.mock.callCount(), 0, 'render needs no transport');
  });
}

control('fresh check: Open with authority link and current limits', 1, false,
  {badge: 'Open', authority: true, bag: true, size: true, depth: true});
if (process.argv.includes('--audit')) {
  const unconfirmed = {badge: 'Check rules', authority: true, bag: false, size: false, depth: false};
  control('overdue open check: Check rules with authority link and no current limits', 30, true, unconfirmed);
  control('overdue restricted check: keep the restriction as a separately labeled note', 30, true, unconfirmed, true);
}
