import './fixtures/sp1605_reports_source_key/offline.mjs';
import assert from 'node:assert/strict';
import test from 'node:test';
import {load, transport, labels, A} from './fixtures/sp1605_reports_source_key/harness.mjs';

test('primary regression', async () => {
  const m = await load(), calls = [], fetchFn = transport(calls);
  await m.openReports('synthetic-region', 'reef', null, fetchFn);
  assert.equal(m.reportsData.peek().data.charters, null);
  await m.openReports('synthetic-region', 'reef', A, fetchFn);
  assert.deepEqual(labels(m), ['Synthetic A'], 'A1_SOURCE_IDENTITY: null-to-path must load current charter evidence');
  assert.equal(calls.filter(url => url === A).length, 1);
  assert.match(m.render(m.h(m.ReportsBody, {data: m.reportsData.peek().data, catches: null})), /Synthetic A/);
});

test('healthy control', async () => {
  const m = await load(), calls = [], fetchFn = transport(calls);
  await m.openReports('synthetic-region', 'reef', A, fetchFn);
  await m.openReports('synthetic-region', 'halibut', A, fetchFn);
  assert.equal(calls.filter(url => url === A).length, 2, 'changing target still starts a matching load');
  assert.deepEqual(labels(m), ['Synthetic A']);
});

if (process.env.SP1605_SUITE === 'focused') await import('./fixtures/sp1605_reports_source_key/focused.mjs');
