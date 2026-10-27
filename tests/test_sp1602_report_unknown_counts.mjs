import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import {dirname, resolve} from 'node:path';
globalThis.REGIONS = {};
globalThis.DEPLOYMENT = {allowed_origins: []};
const {countsText, countLines, copyFor} = await import('../server/advisor/pages/render.ts');
const copy = copyFor('en');
const line = (label, kept, released) => ({label, species_key: 'lingcod', kept, released});

test('primary regression', () => {
  const observed = countsText([line('lingcod', null, null)], copy);
  assert.equal(observed, '', `unmeasured catch rendered as ${JSON.stringify(observed)}`);
});

test('healthy control', () => {
  assert.equal(countsText([line('lingcod', 0, 0)], copy), '0 lingcod');
});

test('A1-A4: measured rows preserve order, formatting, empty output, escaping and producer parsing', async () => {
  assert.equal(countsText([line('lingcod', null, null)], copy), '');
  assert.equal(countsText([line('lingcod', 0, 0), line('rockfish', 3, null)], copy), '0 lingcod, 3 rockfish');
  assert.equal(countsText([line('lingcod', null, null), line('rockfish', 3, null)], copy), '3 rockfish');
  assert.equal(countsText([], copy), '');
  assert.equal(countsText([line('lingcod', null, 2)], copy), copy.releasedOnly(2, 'lingcod'));
  assert.equal(countsText([line('lingcod', 3, 2)], copy), `3 lingcod (${copy.released(2)})`);
  const fixturePath = resolve(dirname(fileURLToPath(import.meta.url)), 'fixtures/sp1602_report_unknown_counts/counts.json');
  const fixture = JSON.parse(await readFile(fixturePath, 'utf8'));
  assert.equal(countsText(fixture, copy), ['3 rockfish', '0 lingcod', copy.releasedOnly(2, 'lingcod')].join(', '));
  const parsed = countLines(JSON.stringify([{label: '<lingcod>', species_key: 'lingcod', kept: null, released: null}, {label: 'rockfish', species_key: 'rockfish', kept: 3, released: null}]));
  assert.equal(countsText(parsed, copy), '3 rockfish');
  assert.equal(countsText(parsed.map(x => x.label === '<lingcod>' ? {...x, kept: 0, released: 0} : x), copy), '0 <lingcod>, 3 rockfish');
});

test('A5: advisor report-table consumer escapes measured text and omits unmeasured rows', async () => {
  const {reportsTable} = await import('../server/advisor/pages/data.ts');
  const table = reportsTable([
    {id: 'unknown', report_date: '2026-01-02', trip_type: null, anglers: null, counts_json: JSON.stringify([line('<lingcod>', null, null)]), verified: 0, version: 1},
    {id: 'measured', report_date: '2026-01-01', trip_type: null, anglers: null, counts_json: JSON.stringify([line('<lingcod>', 0, 0)]), verified: 0, version: 1},
  ], 'en', {boats: false, label: 'Reports'}).value;
  assert.equal((table.match(/<td>0 &lt;lingcod&gt;<\/td>/g) ?? []).length, 1);
  assert.match(table, /<td><\/td><\/tr>/);
  assert.doesNotMatch(table, /<td>0 <lingcod><\/td>/);
  const privateBoat = reportsTable([
    {id: 'private-boat', report_date: '2026-01-03', trip_type: null, anglers: null, counts_json: '[]', verified: 0, version: 1, boat_name: 'DO NOT DISCLOSE', boat_slug: 'private', boat_status: 'unverified'},
  ], 'en', {boats: true, label: 'Reports'}).value;
  assert.ok(privateBoat.includes(copy.anotherBoat));
  assert.ok(!privateBoat.includes('DO NOT DISCLOSE'));
});
