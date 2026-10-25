import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {coastlineMark} from '../web/map/coastline.ts';

const fixtures = JSON.parse(readFileSync(new URL('./fixtures/sp1805_shoreline_date/shoreline-properties.json', import.meta.url), 'utf8'));
const impossible = fixtures.impossible_date;
const healthy = fixtures.valid_leap_day;

test('A1 primary regression: impossible calendar date is withheld, valid leap-day unchanged', () => {
  assert.equal(coastlineMark(impossible), null, '2026-02-31 is not a real calendar date');
  assert.equal(coastlineMark(healthy).source, 'NOAA NGS CUSP · source date 2024-02-29');
});

test('A1 healthy control: valid leap-day accepted and nondatelike strings rejected', () => {
  assert.equal(coastlineMark(healthy).source, 'NOAA NGS CUSP · source date 2024-02-29');
  assert.equal(coastlineMark({...healthy, source_date: 'not-a-date'}), null);
});

test('A2 rejects impossible month/day, malformed and absent values', () => {
  for (const source_date of ['2026-00-10', '2026-13-01', '2026-01-00', '2026-04-31', '2025-02-29', '1900-02-29', '2026-2-01', '2026-02-31']) {
    assert.equal(coastlineMark({...healthy, source_date}), null, source_date);
  }
  for (const properties of [{...healthy, source_date: undefined}, {}, null]) assert.equal(coastlineMark(properties), null);
  assert.ok(coastlineMark({...healthy, source_date: '2000-02-29'}));
});

test('A3 preserves literal historical/future dates and existing text conversion', () => {
  for (const source_date of ['1900-02-28', '2096-02-29', '2037-12-31']) {
    assert.equal(coastlineMark({...healthy, source_date}).source, `NOAA NGS CUSP · source date ${source_date}`);
  }
  assert.equal(coastlineMark({...healthy, source_date: ' 2024-02-29 '}).source, 'NOAA NGS CUSP · source date 2024-02-29');
  assert.equal(coastlineMark({...healthy, source_date: 20240229}), null);
});

test('A4 preserves metadata and does not mutate input across accuracy/source identity variants', () => {
  for (const extra of [{HOR_ACC: undefined, SOURCE_ID: 'id'}, {HOR_ACC: '2.5', SOURCE_ID: 'id'}, {HOR_ACC: '0', SOURCE_ID: '', source_tile: 'tile/1'}]) {
    const props = {...healthy, ...extra};
    const before = structuredClone(props);
    const mark = coastlineMark(props);
    assert.ok(mark);
    assert.equal(mark.name, 'Shoreline');
    assert.equal(mark.source, 'NOAA NGS CUSP · source date 2024-02-29');
    assert.deepEqual(props, before);
    if (extra.SOURCE_ID) assert.equal(mark.id, 'coastline:id');
    else assert.equal(mark.id, 'coastline:tile/1');
  }
});
