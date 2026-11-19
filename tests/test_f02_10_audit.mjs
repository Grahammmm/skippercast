// SCA-577 / F02-10: null must not be summed into a measured zero or hidden in a partial total.
// `node --test tests/test_f02_10_audit.mjs` runs the controls.
// `node tests/test_f02_10_audit.mjs --baseline` also reports the unchanged renderer's gaps.
import assert from 'node:assert/strict';
import test from 'node:test';
// Synthetic compile-time binding; do not load runtime configuration.
globalThis.REGIONS = {};
globalThis.DEPLOYMENT = {allowed_origins: []};
const {speciesPage} = await import('../server/advisor/pages/species.ts');

const languages = {
  en: {missing: 'Not reported', partial: 'partial'},
  es: {missing: 'No reportado', partial: 'parcial'},
};
// Reverse the columns in the second group so neither can borrow the other's completeness.
const cases = [
  {name: 'missing kept', counts: [[null, 0]], want: ['missing', 0]},
  {name: 'missing released', counts: [[0, null]], want: [0, 'missing']},
  {name: 'partial kept', counts: [[2, 0], [null, 0]], want: ['partial:2', 0]},
  {name: 'partial released with a known zero', counts: [[0, 0], [0, null]], want: [0, 'partial:0']},
];
const columns = ['kept', 'released'];

function expected({want}, lang) {
  const {missing, partial} = languages[lang];
  return want.map(w => w === 'missing' ? missing : typeof w === 'number' ? String(w) : `${w.split(':')[1]} (${partial})`);
}

function gaps(input, lang, cells) {
  const {missing, partial} = languages[lang];
  return input.want.flatMap((want, i) => {
    const cell = cells[i];
    const ok = want === 'missing' ? cell.toLowerCase() === missing.toLowerCase()
      : typeof want === 'number' ? cell === String(want)
      : cell.match(/\d+(?:[.,]\d+)?/g)?.join() === want.split(':')[1] && new RegExp(`\\b${partial}\\b`, 'i').test(cell);
    return ok ? [] : [`${lang} ${input.name}: ${columns[i]} expected ${expected(input, lang)[i]}, got ${cell}`];
  });
}

// Exercise real aggregation + HTML over a SELECT-only D1 double. Each synthetic
// report has one species line; there are no account, contact or location records.
async function cellsFor(input, lang) {
  const results = input.counts.map(([kept, released], i) => ({
    boat_id: `fixture-${i}`, port: 'fixture-port', report_date: '2026-11-01',
    counts_json: JSON.stringify([{label: 'lingcod', species_key: 'lingcod', kept, released}]),
  }));
  const DB = {prepare(query) {
    assert.match(query, /^SELECT\b/i);
    assert.match(query, /FROM advisor_(?:rules|reports)\b/);
    return {bind: () => ({all: async () => ({results: query.includes('FROM advisor_reports') ? results : []})})};
  }};
  const page = await speciesPage({DB}, 'lingcod', lang,
    {publicBase: 'https://example.test', number: null, regionDefault: 'fixture-region'},
    {clock: () => Date.parse('2026-11-01T19:00:00Z')});
  const body = page.match(/<tbody>([\s\S]*?)<\/tbody>/)?.[1];
  assert.ok(body, 'the synthetic catch table rendered');
  const rows = [...body.matchAll(/<tr>([\s\S]*?)<\/tr>/g)];
  assert.equal(rows.length, 1, 'both reports belong to the same catch day');
  const cells = [...rows[0][1].matchAll(/<td>([\s\S]*?)<\/td>/g)];
  assert.equal(cells.length, 5);
  return cells.slice(2, 4).map(m => m[1].replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim());
}

test('F02-10: the bilingual catch-cell oracle accepts complete/missing/partial and rejects a bare subtotal', async () => {
  for (const lang of Object.keys(languages)) {
    assert.deepEqual(await cellsFor({counts: [[0, 0]]}, lang), ['0', '0']);
    for (const input of cases) {
      const valid = expected(input, lang);
      assert.deepEqual(gaps(input, lang, valid), []);
      const i = input.want.findIndex(w => typeof w !== 'number');
      const flattened = valid.with(i, input.want[i].split(':')[1] ?? '0');
      assert.deepEqual(gaps(input, lang, flattened), [`${lang} ${input.name}: ${columns[i]} expected ${valid[i]}, got ${flattened[i]}`]);
    }
  }
});

if (process.argv.includes('--baseline')) {
  test('F02-10 read-only baseline receipt (differences are diagnostic)', async t => {
    const differences = [];
    for (const lang of Object.keys(languages)) {
      for (const input of cases) differences.push(...gaps(input, lang, await cellsFor(input, lang)));
    }
    t.diagnostic(differences.length ? differences.join('\n') : 'NO GAP');
  });
}
