// SC2037-11: the planner states each target species' rules on the plan's date (web/app/PlanRules.tsx), from the frozen FE-61
// registry (tests/fixtures/regulations/fe61-v1.json) with synthetic source checks and a frozen clock. Offline.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {mkdtemp, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import test, {after} from 'node:test';
import {build} from 'esbuild';
import {rendererPlugin, preparedCatalogue} from './helpers/esbuild-url.mjs';

const realFetch = globalThis.fetch;
globalThis.fetch = async () => { throw new Error('no network in this test'); };
const hookStub = {name: 'hook-stub', setup: b => {
  b.onResolve({filter: /^preact\/hooks$/}, a => a.importer.endsWith('web/app/PlanRules.tsx') ? {path: 'hooks', namespace: 'hook-stub'} : null);
  b.onLoad({filter: /.*/, namespace: 'hook-stub'}, () => ({contents: 'export const useEffect = () => {};', loader: 'js'}));
}};
const dir = await mkdtemp(join(tmpdir(), 'planner-rules-')), out = join(dir, 'ui.mjs');
await build({stdin: {resolveDir: new URL('..', import.meta.url).pathname, loader: 'ts', contents: `
    export {PlanRules, planRuleLine, ruleSpecies, CHECK_RULES, NOT_LEGAL_ADVICE} from './web/app/PlanRules.tsx';
    export {regsData} from './web/regs.ts';
    export {language, t} from './web/i18n.ts';
    export {render} from 'preact-render-to-string'; export {h} from 'preact';`},
  bundle: true, format: 'esm', platform: 'node', outfile: out, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact', plugins: [rendererPlugin, preparedCatalogue, hookStub]});
const m = await import(pathToFileURL(out).href);
after(async () => { globalThis.fetch = realFetch; m.regsData.value = null; m.language.value = 'en'; await rm(dir, {recursive: true, force: true}); });

const fixture = JSON.parse(readFileSync(new URL('./fixtures/regulations/fe61-v1.json', import.meta.url)));
const MORRO = fixture.region, HOUR = 3600000;
const NOW = Date.parse('2026-10-12T18:00:00Z');
function data(at = NOW) {
  const d = structuredClone(fixture.regulations);
  d.reviewed_at = new Date(at - HOUR).toISOString();
  d.rules_review_status = 'reviewed';
  for (const [id, source] of Object.entries(d.sources)) {
    source.approved_content_sha256 = 'a'.repeat(64);
    d.checks[id] = {url: source.url, normalization: source.normalization, status: 'unchanged', source_status: 'ok', content_sha256: 'a'.repeat(64), data_retrieved_at: new Date(at).toISOString()};
  }
  return d;
}
const html = (d, species, date = '2026-10-14', loaded = d) => {
  m.regsData.value = loaded ? {region: 'morro-bay', data: loaded} : null;
  return m.render(m.h(m.PlanRules, {date, species, region: {id: 'morro-bay', timezone: 'America/Los_Angeles'}, now: NOW}));
};
const text = s => s.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ');

test('an open species reads open with its limits, verified date, freshness and the one official link', () => {
  const t = text(html(data(), 'lingcod')), line = m.planRuleLine(data(), 'lingcod', '2026-10-14', MORRO, NOW);
  assert.equal(line.kind, 'open');
  assert.match(t, /Open/); assert.match(t, /2 per person daily/); assert.match(t, /Verified Oct 12/); assert.match(t, /Checked today/);
  assert.doesNotMatch(t, new RegExp(m.CHECK_RULES));
  assert.equal((html(data(), 'lingcod').match(/<a /g) ?? []).length, 1);
  assert.match(html(data(), 'lingcod'), /href="https:\/\/[^"]+"/);
  assert.match(t, new RegExp(m.NOT_LEGAL_ADVICE));
});

test('a closed date says closed plainly, never open', () => {
  const d = data(); d.species.lingcod.windows = [{start: '2026-04-01', end: '2026-10-31'}];
  const out = html(d, 'lingcod', '2026-11-10'), t = text(out), line = m.planRuleLine(d, 'lingcod', '2026-11-10', MORRO, NOW);
  assert.equal(line.kind, 'closed');
  assert.match(t, /Closed on 2026-11-10/);
  assert.doesNotMatch(t, /\bOpen\b/);
  assert.doesNotMatch(out, /Check the official rules/);
});

test('a depth or area limit reads as that, not open', () => {
  const d = data();
  d.species.lingcod.windows = d.species.lingcod.windows.map(w => ({...w, geography: {kind: 'latitude-band', south: 34.5, north: 36, source_id: d.species.lingcod.source_ids[0], note: 'Synthetic band.'}}));
  const out = html(d, 'lingcod'), t = text(out), line = m.planRuleLine(d, 'lingcod', '2026-10-14', MORRO, NOW);
  assert.equal(line.kind, 'check');
  assert.match(t, /applies only within a geographic area/); assert.match(t, /Check the official rules before this trip/);
  assert.doesNotMatch(t, /Verified/); assert.doesNotMatch(out, /data-status="open"/);
});

test('stale, overdue and not-reviewed rules read check the official rules, never open', () => {
  const stale = data(NOW - 50 * HOUR), overdue = data(NOW - 30 * HOUR), unreviewed = data(); unreviewed.rules_review_status = 'draft';
  const outside = data();
  for (const [d, date, label] of [[stale, '2026-10-14', 'stale'], [overdue, '2026-10-14', 'overdue'], [unreviewed, '2026-10-14', 'not reviewed'], [outside, '2027-03-01', 'outside the reviewed period']]) {
    const out = html(d, 'lingcod', date), t = text(out);
    assert.equal(m.planRuleLine(d, 'lingcod', date, MORRO, NOW).kind, 'check', label);
    assert.match(t, /Check the official rules before this trip/, label);
    assert.doesNotMatch(out, /data-status="open"/, label);
    assert.doesNotMatch(t, /Verified/, label);
    assert.match(out, /href="https:\/\//, label);
  }
});

test('no rules loaded reads check the official rules with the official link and no open badge', () => {
  const out = html(null, 'lingcod', '2026-10-14', null), t = text(out);
  assert.match(t, /Check the official rules before this trip/); assert.doesNotMatch(out, />Open</);
  assert.doesNotMatch(out, /data-status="open"/); assert.match(out, /href="https:\/\//);
  m.regsData.value = {region: 'other-region', data: data()};
  assert.match(text(m.render(m.h(m.PlanRules, {date: '2026-10-14', species: 'lingcod', region: {id: 'morro-bay'}, now: NOW}))), /Check the official rules/);
});

test('reef gives a line each for lingcod and rockfish; no date gives nothing', () => {
  assert.deepEqual(m.ruleSpecies('reef'), ['lingcod', 'rockfish']);
  assert.deepEqual(m.ruleSpecies('lingcod'), ['lingcod']);
  const out = html(data(), 'reef');
  assert.equal((out.match(/class="plan-rule"/g) ?? []).length, 2);
  assert.match(text(out), /Lingcod/); assert.match(text(out), /Rockfish/);
  assert.equal(html(data(), 'reef', ''), '');
});

test('the rules block is not part of the plan, the GPX or the saved trip', () => {
  for (const f of ['../web/planner.ts', '../dist/trip-export.js', '../web/trip.ts']) {
    const src = readFileSync(new URL(f, import.meta.url), 'utf8');
    assert.doesNotMatch(src, /PlanRules|planRuleLine|regulationState/, f);
  }
});

// SC1407-13: the card in Spanish. The decisions are the same as English; only the card's own words change, and the registry's
// reason and bag and size clauses stay English, marked lang="en".
const inSpanish = fn => { m.language.value = 'es'; try { return fn(); } finally { m.language.value = 'en'; } };
const esHtml = (...args) => inSpanish(() => html(...args));
const hrefs = s => [...s.matchAll(/<a [^>]*>/g)].map(a => a[0].match(/href="([^"]+)"/)[1]);

test('plan_rules_es_confirmed_states: open, restricted, scheduled and closed read in Spanish with the English decisions, closed said plainly', () => {
  const open = data(), restricted = data(), scheduled = data(), closed = data();
  restricted.species.lingcod.windows = [{start: '2026-04-01', end: '2026-12-31', restriction: 'Synthetic: shoreward of the 20-fathom line only.'}];
  scheduled.species.lingcod.windows = [{start: '2026-04-01', end: '2026-12-31', requires_opening_review: true}];
  closed.species.lingcod.windows = [{start: '2026-04-01', end: '2026-10-31'}];
  for (const [d, date, kind, status, badge] of [[open, '2026-10-14', 'open', 'open', 'Abierto'], [restricted, '2026-10-14', 'open', 'restricted', 'Abierto · con límites'],
    [scheduled, '2026-10-14', 'open', 'scheduled', 'Apertura sin confirmar'], [closed, '2026-11-10', 'closed', 'closed', 'Cerrado']]) {
    const en = m.planRuleLine(d, 'lingcod', date, MORRO, NOW), es = m.planRuleLine(d, 'lingcod', date, MORRO, NOW, 'es');
    assert.deepEqual([es.kind, es.status, en.kind, en.status], [kind, status, kind, status], status);
    assert.deepEqual([es.name, es.reason, es.link], [en.name, en.reason, en.link], `${status}: names, the registry's reason and the link are not translated`);
    const out = esHtml(d, 'lingcod', date), t = text(out);
    assert.match(out, new RegExp(`<span class="app-mark-regs-badge" data-status="${status}">${badge}</span>`), status);
    assert.match(out, /<section class="export-card plan-rules" aria-label="Reglas para la fecha del plan">/, status);
    assert.match(out, new RegExp(`<h2>Reglas para el ${date}</h2>`), status);
    assert.match(t, /No es asesoría legal; consulta la página oficial\./, status);
    assert.doesNotMatch(t, /Consulta las reglas oficiales antes de este viaje/, `${status}: a confirmed state carries no check line`);
    assert.doesNotMatch(t, /Rules on|Check the official rules|Not legal advice|Closed on|Verified|Checked today/, `${status}: none of the card's own words stay English`);
  }
  const out = esHtml(closed, 'lingcod', '2026-11-10'), t = text(out);
  assert.match(t, /Cerrado Lingcod \. Cerrado el 2026-11-10\. Outside the reviewed local season\./);
  assert.doesNotMatch(out, /Abierto/); assert.doesNotMatch(out, /data-status="open"/);
  assert.match(text(esHtml(open, 'lingcod')), /Verificado el .* Revisado hoy/);
  const reef = esHtml(data(), 'reef');
  assert.equal((reef.match(/class="plan-rule"/g) ?? []).length, 2, 'reef stays two species in Spanish');
  assert.match(reef, /<strong>Lingcod<\/strong>/); assert.match(reef, /<strong>Rockfish \/ rock cod<\/strong>/);
  assert.deepEqual(hrefs(reef), hrefs(html(data(), 'reef')), 'the same official pages in both languages');
});

test('plan_rules_es_check_fail_closed: every unconfirmed reading says check the official rules in Spanish, never open or verified', () => {
  const stale = data(NOW - 50 * HOUR), overdue = data(NOW - 30 * HOUR), unreviewed = data(), geo = data();
  unreviewed.rules_review_status = 'draft';
  geo.species.lingcod.windows = geo.species.lingcod.windows.map(w => ({...w, geography: {kind: 'latitude-band', south: 34.5, north: 36, source_id: geo.species.lingcod.source_ids[0], note: 'Synthetic band.'}}));
  const cases = [[stale, 'lingcod', '2026-10-14', 'stale'], [overdue, 'lingcod', '2026-10-14', 'overdue'], [unreviewed, 'lingcod', '2026-10-14', 'not reviewed'],
    [data(), 'lingcod', '2027-03-01', 'outside the reviewed period'], [geo, 'lingcod', '2026-10-14', 'needs a fishing location'], [data(), 'nosuchfish', '2026-10-14', 'unknown species'],
    [null, 'lingcod', '2026-10-14', 'no registry']];
  for (const [d, species, date, label] of cases) {
    const es = m.planRuleLine(d, species, date, MORRO, NOW, 'es');
    assert.equal(es.kind, 'check', label); assert.equal(m.planRuleLine(d, species, date, MORRO, NOW).kind, 'check', label);
    assert.equal(es.label, 'Revisa las reglas', label);
    const out = esHtml(d, species, date, d), t = text(out);
    assert.match(t, /Consulta las reglas oficiales antes de este viaje\./, label);
    assert.match(out, /<span class="app-mark-regs-badge" data-status="unknown">Revisa las reglas<\/span>/, label);
    assert.match(out, /<span lang="en">[^<]+<\/span> \(en inglés\)/, `${label}: the registry's reason stays English and says so`);
    assert.doesNotMatch(out, /data-status="(?:open|restricted|scheduled)"/, label);
    assert.doesNotMatch(t, /Abierto|Verificado|Revisado hoy|Check the official rules/, label);
    assert.match(out, /<a href="https:\/\/[^"]+" target="_blank" rel="noopener" hreflang="en"/, `${label}: the official link stays`);
  }
  m.regsData.value = {region: 'other-region', data: data()};
  const other = inSpanish(() => m.render(m.h(m.PlanRules, {date: '2026-10-14', species: 'lingcod', region: {id: 'morro-bay'}, now: NOW})));
  assert.match(text(other), /Consulta las reglas oficiales antes de este viaje/, 'another region\'s registry is never read');
  assert.doesNotMatch(other, /data-status="open"/);
  // The opening day without an hour is restricted to the opening time, not open: its timing note stays the registry's English.
  const opening = data(); opening.species.lingcod.windows = [{start: '2026-10-14', end: '2026-12-31', start_at: '2026-10-14T14:00:00Z'}];
  const day = esHtml(opening, 'lingcod');
  assert.match(day, /data-status="restricted">Abierto · con límites</); assert.doesNotMatch(day, /data-status="open"/);
  assert.match(day, /<span lang="en">Season starts [^<]+The opening date is not an all-day opening\.<\/span> \(en inglés\)/);
  for (const date of ['', '2026-1-4', 'tomorrow']) assert.equal(esHtml(data(), 'lingcod', date), '', `blank or malformed date ${JSON.stringify(date)} renders nothing`);
});

test('plan_rules_official_english_and_escape: official wording and links stay English and marked; translated words are not; English bytes keep no new markup', () => {
  const out = esHtml(data(), 'lingcod'), en = html(data(), 'lingcod');
  assert.match(out, /<p lang="en">2 per person daily<\/p>/); assert.match(out, /<p lang="en">22 in min total length<\/p>/);
  assert.match(out, /<p>Todas las profundidades<\/p>/, 'the app-written depth line is Spanish and not marked English');
  assert.match(out, /<p class="export-note">El texto de las reglas se muestra tal como se publica, en inglés\.<\/p>/);
  assert.match(out, /<span lang="en">Local closures, MPAs and gear restrictions still apply\.<\/span> \(en inglés\)/);
  assert.match(out, /<a href="https:\/\/[^"]+" target="_blank" rel="noopener" hreflang="en" aria-label="Reglas oficiales para Lingcod \(página oficial, se abre en una pestaña nueva\)">Reglas oficiales<\/a>/);
  assert.deepEqual(hrefs(out), hrefs(en), 'the same official destination');
  assert.doesNotMatch(out, /lang="en">(?:Reglas|Todas|Abierto|Verificado|Revisado)/, 'no Spanish chrome is tagged English');
  assert.doesNotMatch(en, / lang=|hreflang|en inglés|in English/, 'English output gains no language markup');
  assert.match(en, /<a href="https:\/\/[^"]+" target="_blank" rel="noopener" aria-label="Official rules for Lingcod \(official page, opens in a new tab\)">Official rules<\/a>/);
  assert.match(text(en), /Rules on 2026-10-14/);
  const restricted = data(); restricted.species.lingcod.windows = [{start: '2026-04-01', end: '2026-12-31', restriction: 'Synthetic: shoreward of the 20-fathom line only.'}];
  assert.match(esHtml(restricted, 'lingcod'), /<span lang="en">Synthetic: shoreward of the 20-fathom line only\.<\/span> \(en inglés\)/);
  const hostile = data(); hostile.species.lingcod.name = '<img src=x onerror=alert(1)>{date}'; hostile.species.lingcod.bag = '<b>{name}</b> per person daily';
  const bad = esHtml(hostile, 'lingcod');
  assert.doesNotMatch(bad, /<img|<b>/, 'registry text is escaped, never markup');
  assert.match(bad, /&lt;b>\{name}&lt;\/b> per person daily|&lt;b&gt;\{name\}&lt;\/b&gt; per person daily/);
  assert.match(bad, /aria-label="Reglas oficiales para &lt;img src=x onerror=alert\(1\)>\{date\}|aria-label="Reglas oficiales para &lt;img src=x onerror=alert\(1\)&gt;\{date\}/, 'braces in a name are not filled');
});

// RF1925-3: the combined reef plan shows an identical unconfirmed reading once, with both species and both official links.
test('reef_missing_rules_one_notice_two_links: no registry groups the two unconfirmed species into one notice', () => {
  for (const lang of ['en', 'es']) {
    m.language.value = lang;
    try {
      {
        const out = html(data(), 'reef', '2026-10-14', null), t = text(out);
        assert.equal((out.match(/class="plan-rule"/g) ?? []).length, 1, lang);
        assert.equal((out.match(/app-mark-regs-badge/g) ?? []).length, 1, lang);
        assert.equal(t.split(m.t('planRules.check', lang)).length - 1, 1, `${lang}: one caution`);
        assert.equal((out.match(/class="export-note"/g) ?? []).length, 2, `${lang}: one freshness line and the one legal note`);
        assert.match(out, /<strong>lingcod, rockfish<\/strong>/);
        assert.equal(hrefs(out).length, 2, lang);
        assert.doesNotMatch(out, /data-status="open"/);
      }
    } finally { m.language.value = 'en'; }
  }
});

test('only_identical_unknowns_group: differing readings stay separate, with one caution; confirmed species stay distinct', () => {
  const mixed = data();
  mixed.species.lingcod.windows = [{start: '2026-04-01', end: '2026-10-01'}];
  for (const [d, label] of [[mixed, 'closed beside open']]) {
    const lines = ['lingcod', 'rockfish'].map(s => m.planRuleLine(d, s, '2026-10-14', MORRO, NOW));
    const out = html(d, 'reef');
    assert.equal((out.match(/class="plan-rule"/g) ?? []).length, 2, label);
    assert.equal(hrefs(out).length, 2, label);
    assert.equal(text(out).split(m.CHECK_RULES).length - 1, lines.some(l => l.kind === 'check') ? 1 : 0, label);
  }
  assert.equal((html(data(), 'reef').match(/class="plan-rule"/g) ?? []).length, 2);
  assert.doesNotMatch(text(html(data(), 'reef')), new RegExp(m.CHECK_RULES));
  assert.equal((html(data(), 'lingcod', '2026-10-14', null).match(/class="plan-rule"/g) ?? []).length, 1);
});
