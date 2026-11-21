import test from 'node:test';
import assert from 'node:assert/strict';
import { exportConditions, withConditions, exportEntries } from '../server/catch-conditions-export.ts';
import { CONDITIONS_MAX_BYTES, parseConditionsV1 } from '../server/conditions-v1.ts';

const at = '2024-02-29T01:02:03Z';
const snapshot = { v: 1, at, layers: { water_temp: { value: 56.9, unit: 'F', product: 'SST', sample_at: at } } };
const pending = { v: 1, pending: true };
const missing = { v: 1, missing: 'not archived' };
const unreadable = { v: 1, missing: 'unreadable' };

test('C1: absent column values remain null, not unreadable', () => {
  assert.deepEqual(exportConditions(null), null);
  assert.deepEqual(exportConditions(undefined), null);
});

test('C1: stored snapshots, including pending and missing, export as objects', () => {
  for (const expected of [snapshot, pending, missing]) {
    assert.deepEqual(exportConditions(JSON.stringify(expected)), expected);
  }
});

test('C1: enforce the UTF-8 limit on stored bytes, not characters or normalized JSON', () => {
  const expected = { v: 1, missing: 'océan' };
  const json = JSON.stringify(expected);
  const atLimit = json.padEnd(CONDITIONS_MAX_BYTES - 1);
  assert.deepEqual(exportConditions(atLimit), expected);
  assert.deepEqual(exportConditions(`${atLimit} `), unreadable);
});

test('C1: malformed text and validator refusals never echo the stored value', () => {
  for (const raw of ['', '{"v":1,', 'null', '[]', 'true', '1', '"pending"', '{"v":2,"pending":true}',
    '{"v":1,"pending":false}', '{"v":1,"pending":true,"extra":"fixture"}']) {
    assert.deepEqual(exportConditions(raw), unreadable, raw);
  }
});

test('C1: non-string present values are not coerced or accepted directly', () => {
  for (const raw of [pending, 1, false, [], new String(JSON.stringify(pending)), Symbol('pending')]) {
    assert.deepEqual(exportConditions(raw), unreadable);
  }
});

test('C2: only the conditions value changes; other own enumerable keys survive', () => {
  const tag = Symbol('fixture tag');
  const detail = { count: 0 };
  const raw = JSON.stringify(snapshot);
  const row = Object.create({ inherited: 'do not copy' }, { hidden: { value: 'do not copy' } });
  Object.assign(row, { id: 'fixture', detail, [tag]: true, conditions: raw });
  Object.freeze(row);

  const result = withConditions(row);
  assert.deepEqual(result, { id: 'fixture', detail, [tag]: true, conditions: snapshot });
  assert.equal(result.detail, detail);
  assert.deepEqual({ ...row }, { id: 'fixture', detail: { count: 0 }, [tag]: true, conditions: raw });
});

test('C2: add an explicit null to a row that has no conditions key', () => {
  const row = Object.freeze({ id: 'fixture' });
  const result = withConditions(row);
  assert.deepEqual(result, { id: 'fixture', conditions: null });
  assert.deepEqual(row, { id: 'fixture' });
});

test('C3: keep plain rows in order, skip unreadable rows, and validate every non-null snapshot', () => {
  const brokenConditions = { get conditions() { throw new TypeError('fixture conditions'); } };
  const brokenField = { get id() { throw new TypeError('fixture field'); } };
  const revoked = Proxy.revocable({}, {});
  revoked.revoke();
  const rows = [
    null, { id: 'first', conditions: JSON.stringify(snapshot) }, 1, [], brokenConditions,
    Object.assign(Object.create(null), { id: 'second', conditions: JSON.stringify(pending) }),
    new Date(at), brokenField, undefined, revoked.proxy, { id: 'third', conditions: '{' },
    { id: 'fourth' }, { id: 'fifth', conditions: JSON.stringify(missing) },
  ];
  const result = exportEntries(rows);
  assert.deepEqual(result, [
    { id: 'first', conditions: snapshot }, { id: 'second', conditions: pending },
    { id: 'third', conditions: unreadable }, { id: 'fourth', conditions: null },
    { id: 'fifth', conditions: missing },
  ]);
  for (const { conditions } of result) {
    if (conditions !== null) assert.deepEqual(parseConditionsV1(conditions), { ok: true, value: conditions });
  }
});

test('C3: a throwing array slot does not hide later rows', () => {
  const rows = [undefined, { id: 'survives' }];
  Object.defineProperty(rows, 0, { get() { throw new TypeError('fixture slot'); } });
  assert.deepEqual(exportEntries(rows), [{ id: 'survives', conditions: null }]);
});

test('C3: empty and unreadable arrays yield an empty export', () => {
  assert.deepEqual(exportEntries([]), []);
  const revoked = Proxy.revocable([], {});
  revoked.revoke();
  assert.deepEqual(exportEntries(revoked.proxy), []);
});
