import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {advisorDatabase, sqliteUnavailable} from './_advisor_d1.mjs';

const read = path => JSON.parse(readFileSync(new URL(path, import.meta.url)));
globalThis.REGIONS = {'morro-bay': read('../regions/morro-bay/region.json')};
globalThis.DEPLOYMENT = read('../deployments/production.json');
const {getPortReport} = await import('../server/advisor/tools/get_port_report.ts');
const {advisorSettings} = await import('../server/advisor/settings.ts');
const T0 = Date.parse('2026-10-03T17:00:00Z');
const data = read('./fixtures/sp1811_report_counts/counts.json');
const dbTest = (name, fn) => test(name, {skip: sqliteUnavailable || false}, fn);

function setup(countsJson) {
  const {sql, db} = advisorDatabase();
  const stamp = '2026-10-01T00:00:00Z';
  sql.prepare(`INSERT INTO advisor_boats(id,slug,name,landing,port,region,status,created_at,updated_at)
    VALUES('b1','example-boat','Example Boat','Example Landing','morro-bay','morro-bay','verified',?,?)`).run(stamp, stamp);
  sql.prepare(`INSERT INTO advisor_reports(id,boat_id,region,port,report_date,trip_type,anglers,counts_json,source,status,verified,published_at,created_at,updated_at)
    VALUES('r1','b1','morro-bay','morro-bay','2026-10-02','full-day',10,?,'fixture','published',1,?,?,?)`).run(countsJson, stamp, stamp, stamp);
  return {sql, db};
}
async function report(countsJson) {
  const {db} = setup(countsJson);
  const ctx = {env: {DB: db}, contact: {id: 'c1', role: 'angler'}, message: {id: 'test'}, deps: {feeds: async () => null}, db,
    language: 'en', settings: advisorSettings({}), now: T0};
  return (await getPortReport.run({port: 'morro-bay'}, ctx)).result;
}

// Selectors below are deliberately isolated: BASELINE_GAP_REPRODUCED expects A1 to fail on old source.
test('A1 invalid negative, fractional and unsafe report quantities are independently unavailable', async () => {
  const result = await report(JSON.stringify([
    {species_key: 'rockfish', label: 'Reds', kept: -3, released: 0},
    {species_key: 'lingcod', label: 'Lings', kept: 2, released: 0.5},
    {species_key: 'cabezon', label: 'Cabezon', kept: 9007199254740992, released: 1},
  ]));
  assert.deepEqual(result.skipper_reports[0].counts.map(c => [c.kept, c.released]), [[null, 0], [2, null], [null, 1]]);
});

test('healthy control preserves ordinary numeric kept and released quantities', async () => {
  const result = await report(JSON.stringify([{species_key: 'lingcod', label: 'Lings', kept: 2, released: 0}]));
  assert.deepEqual(result.skipper_reports[0].counts.map(c => [c.kept, c.released]), [[2, 0]]);
});

dbTest('A2 zero, one and maximum safe integer remain exact; negative, fractional and unsafe values become null', async () => {
  const result = await report(JSON.stringify([
    {species_key:'a',label:'a',kept:0,released:1}, {species_key:'b',label:'b',kept:9007199254740991,released:-1},
    {species_key:'c',label:'c',kept:1.5,released:9007199254740992},
  ]));
  assert.deepEqual(result.skipper_reports[0].counts.map(c => [c.kept,c.released]), [[0,1],[9007199254740991,null],[null,null]]);
});

dbTest('A3 non-number types, null, absent fields, arrays and objects are not numeric claims', async () => {
  const result = await report(JSON.stringify([
    {species_key:'a',label:'a',kept:'2',released:true}, {species_key:'b',label:'b',kept:null},
    {species_key:'c',label:'c'}, {species_key:'d',label:'d',kept:[],released:{}},
  ]));
  assert.deepEqual(result.skipper_reports[0].counts.map(c => [c.kept,c.released]), [[null,null],[null,null],[null,null],[null,null]]);
});

dbTest('A4 invalid fields do not suppress a valid sibling quantity', async () => {
  const result = await report(JSON.stringify([{species_key:'a',label:'a',kept:3,released:0.5},{species_key:'b',label:'b',kept:-1,released:4}]));
  assert.deepEqual(result.skipper_reports[0].counts.map(c => [c.kept,c.released]), [[3,null],[null,4]]);
});

dbTest('A5 malformed JSON and non-array or non-object entries retain the existing safe behavior', async () => {
  assert.deepEqual((await report('{')).skipper_reports[0].counts, []);
  assert.deepEqual((await report('null')).skipper_reports[0].counts, []);
  assert.deepEqual((await report(JSON.stringify([null, 1, 'x', {label:'ok',kept:-1}]))).skipper_reports[0].counts, [{species_key:'other',label:'ok',kept:null,released:null}]);
});

dbTest('A6 count order and twelve-row bound are unchanged', async () => {
  const values = Array.from({length: 13}, (_, i) => ({species_key:`s${i}`,label:`L${i}`,kept:i,released:0}));
  const result = await report(JSON.stringify(values));
  assert.equal(result.skipper_reports[0].counts.length, 12);
  assert.deepEqual(result.skipper_reports[0].counts.map(c => c.species_key), values.slice(0, 12).map(c => c.species_key));
});

dbTest('A7 integration sends sanitized counts to skipper_reports and preserves row date and boat identity', async () => {
  const fixture = data.rows.find(row => row.id === 'a4');
  const result = await report(fixture.counts_json);
  assert.deepEqual(result.skipper_reports.map(r => [r.date,r.boat,r.counts[0].kept,r.counts[0].released]), [['2026-10-02','Example Boat',null,1]]);
});
