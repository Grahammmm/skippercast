// BF-tile-cost: e2e/tile-cost-publish.ts publishes one complete report from
// the per-project audit workers. Here two simulated writers share a run
// directory, as the phone and laptop workers do.
import test from 'node:test';
import assert from 'node:assert/strict';
import {existsSync, mkdtempSync, readdirSync, readFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';

const {saveAndPublish} = await import('../e2e/tile-cost-publish.ts');

const row = (project, view, pass) => ({view, project, pass, requests: 1, transfer_bytes: 1, body_bytes: 1, by_kind: {}, remote: {}, cache_reused: 0, reused_from_cold: pass === 'warm' ? 1 : null, settled: true});
const rowsFor = project => ['coast', 'plan'].flatMap(view => [row(project, view, 'cold'), row(project, view, 'warm')]);

function plan() {
  const dir = mkdtempSync(join(tmpdir(), 'tile-cost-'));
  return {runDir: join(dir, 'run'), out: join(dir, 'tile-cost.json'), projects: ['phone', 'laptop'], perProject: 4, commit: 'local'};
}

test('nothing is published until every project has finished', () => {
  const p = plan();
  assert.equal(saveAndPublish(p, 'phone', rowsFor('phone'), 'w1'), null);
  assert.equal(existsSync(p.out), false);
  const all = saveAndPublish(p, 'laptop', rowsFor('laptop'), 'w2');
  assert.equal(all.length, 8);
  const doc = JSON.parse(readFileSync(p.out, 'utf8'));
  assert.equal(doc.schema, 'tile-cost-v1');
  assert.deepEqual(doc.rows.map(r => r.project), [...Array(4).fill('phone'), ...Array(4).fill('laptop')]);
});

test('either finishing order publishes the same complete report, and no temp file is left', () => {
  const a = plan(), b = plan();
  saveAndPublish(a, 'phone', rowsFor('phone'), 'w1'); saveAndPublish(a, 'laptop', rowsFor('laptop'), 'w2');
  saveAndPublish(b, 'laptop', rowsFor('laptop'), 'w2'); saveAndPublish(b, 'phone', rowsFor('phone'), 'w1');
  assert.equal(readFileSync(a.out, 'utf8'), readFileSync(b.out, 'utf8'));
  for (const p of [a, b]) assert.deepEqual([...readdirSync(p.runDir), ...readdirSync(join(p.out, '..'))].filter(n => n.endsWith('.tmp')), []);
});

test('a later finisher never replaces the complete report with a partial one', () => {
  const p = plan();
  saveAndPublish(p, 'phone', rowsFor('phone'), 'w1');
  saveAndPublish(p, 'laptop', rowsFor('laptop'), 'w2');
  saveAndPublish(p, 'phone', rowsFor('phone'), 'w3');   // a retried phone worker finishes last
  assert.equal(JSON.parse(readFileSync(p.out, 'utf8')).rows.length, 8);   // replaced its own rows, added none
});

test('a short project refuses to save or publish', () => {
  const p = plan();
  assert.throws(() => saveAndPublish(p, 'phone', rowsFor('phone').slice(1), 'w1'), /phone: 3 rows, expected 4/);
  assert.equal(existsSync(p.out), false);
});
