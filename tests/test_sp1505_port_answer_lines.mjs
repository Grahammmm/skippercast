// SP-15-v1 SP1505 A1-A4: the daily answer keeps its text when the closing port
// self-link (and its "Full picture:" lead-in) starts on a new line. Complete
// unchanged-API module server/advisor/pages/port.ts: the exported withoutSelfLink
// and the named request function portPage over real migrations in in-memory
// node:sqlite with a synthetic stored advisor_daily_answers row. Offline sentinels
// are installed before any product import; feeds are a throwing double.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
await import('./fixtures/sp1505_port_answer_lines/bootstrap.mjs');
const {advisorDatabase, sqliteUnavailable} = await import('./_advisor_d1.mjs');
if (sqliteUnavailable) throw Error(sqliteUnavailable); // Never convert a capability failure into a skip.

const read = p => JSON.parse(readFileSync(new URL(p, import.meta.url), 'utf8'));
const fixture = read('./fixtures/sp1505_port_answer_lines/cases.json');
const fill = s => s.replaceAll('{url}', fixture.url).replaceAll('{other}', fixture.other);
const NOW = Date.parse(fixture.now);

// Build-injected globals are bound at import (server/config.ts); inject, import, restore.
const globals = ['REGIONS', 'DEPLOYMENT', 'SHELLS', 'BUILD_ID', 'ADVISOR_ASSETS'];
const saved = new Map(globals.map(k => [k, Object.getOwnPropertyDescriptor(globalThis, k)]));
function restore() {
  for (const [k, descriptor] of saved) {
    if (descriptor) Object.defineProperty(globalThis, k, descriptor);
    else delete globalThis[k];
  }
}
function inject() {
  globalThis.REGIONS = {[fixture.port]: read(`../regions/${fixture.port}/region.json`)};
  globalThis.DEPLOYMENT = read('../deployments/production.json');
  globalThis.SHELLS = {'/': '/index.sp1505.html'};
  globalThis.BUILD_ID = 'sp1505-synthetic';
  globalThis.ADVISOR_ASSETS = {};
}
inject();
const {withoutSelfLink, portPage} = await import('../server/advisor/pages/port.ts');
restore();

function scenario(name, fn) {
  test(name, {concurrency: false}, async () => {
    const before = Object.getOwnPropertyDescriptor(globalThis, 'fetch');
    try { await fn(); }
    finally { restore(); Object.defineProperty(globalThis, 'fetch', before); }
  });
}
const check = (rows, tag) => {
  for (const c of rows) assert.equal(withoutSelfLink(fill(c.input), fixture.url), fill(c.expected), `${tag}: ${c.name}`);
};

// Exactly this pair is registered in baseline; no filtering-induced skips.
scenario('primary regression', () => {
  const observed = withoutSelfLink(fill(fixture.primary.input), fixture.url);
  assert.equal(observed, fixture.primary.expected, `SP1505_PRIMARY_SEMANTIC_MISMATCH observed=${JSON.stringify(observed)}`);
});
scenario('healthy control', () => {
  assert.equal(withoutSelfLink(fill(fixture.control.input), fixture.url), fixture.control.expected);
});

if (process.env.SP1505_SUITE !== 'baseline') {
  scenario('A1 a closing self-link on a new line keeps the sentence before it', () => check(fixture.a1, 'A1'));
  scenario('A2 CRLF, blank lines, tabs and !/? line ends keep every preceding sentence', () => check(fixture.a2, 'A2'));
  scenario('A3 no-link, period-space, bare-link and middle-link behavior is unchanged', () => check(fixture.a3, 'A3'));
  // Round 2 (sol-reviewer run 1859 must-fix 1): line breaks between the lead-in colon and the link.
  const colon = read('./fixtures/sp1505_port_answer_lines/colon_whitespace.json');
  scenario('A2 LF, CRLF or a blank line between the lead-in colon and the link still drops the lead-in', () => check(colon.a2, 'A2-colon'));

  for (const [label, rows] of [['', fixture.a4], [', line break after the lead-in colon', colon.a4]]) for (const language of ['en', 'es']) {
    scenario(`A4 portPage renders a stored multi-line daily answer without its self-link (${language}${label})`, async () => {
      inject();
      const {sql, db} = advisorDatabase();
      try {
        const row = rows[language];
        const other = rows[language === 'es' ? 'en' : 'es'];
        // Synthetic stored answer for today; feeds are down, so the stored row is the one shown (todaysAnswer).
        sql.prepare('INSERT INTO advisor_daily_answers(key,text_en,text_es,inputs_hash,generated_at) VALUES(?,?,?,?,?)')
          .run(`${fixture.port}:${fixture.date}`, fill(language === 'en' ? row.stored : other.stored), fill(language === 'es' ? row.stored : other.stored),
            'sp1505-synthetic-hash', fixture.now);
        const feedCalls = [];
        const deps = {clock: () => NOW, feeds: async url => { feedCalls.push(url); throw Error('SP1505 synthetic feed outage'); }};
        const page = await portPage({DB: db}, fixture.port, language, {publicBase: fixture.base, number: null}, deps);
        assert.equal(typeof page, 'string');
        const today = page.match(/<section class="adv-card adv-today"[^>]*>\n<h2 id="today-title">[^<]*<\/h2>\n<p>([\s\S]*?)<\/p>\n<\/section>/);
        assert.ok(today, 'the today section renders');
        assert.equal(today[1], fill(row.shown), 'every stored sentence before the self-link is rendered unchanged');
        assert.ok(!page.includes('?s=txt'), 'no link back to itself');
        assert.ok(feedCalls.length > 0, 'the feed double was consulted (offline outage path)');
      } finally { sql.close(); }
    });
  }
}
