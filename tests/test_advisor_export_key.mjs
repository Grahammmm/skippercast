// RF1050-4: "send me my data" export keys (server/advisor/exports.ts) name only
// real calendar dates in years 2000-2999; an impossible day or a bad contact id
// throws the same 'invalid export key'. Token mint/read/verify are unchanged.
// Offline: no R2, a generated HMAC key.
import test from 'node:test';
import assert from 'node:assert/strict';

const {exportKey, mintExportToken, readExportToken, verifyExportToken} = await import('../server/advisor/exports.ts');
const invalid = {message: 'invalid export key'};

test('a real day gives the unchanged key', () => {
  assert.equal(exportKey('c_1', '2026-11-02'), 'advisor/exports/c_1/2026-11-02.json');
  assert.equal(exportKey('c-1', '2000-01-01'), 'advisor/exports/c-1/2000-01-01.json');
  assert.equal(exportKey('c_1', '2999-12-31'), 'advisor/exports/c_1/2999-12-31.json');
});

test('impossible days and years outside 2000-2999 throw invalid export key', () => {
  for (const date of ['2026-13-01', '2026-00-10', '2026-02-30', '2026-04-31', '2026-01-32', '2026-01-00', '0000-00-00', '1999-12-31', '3000-01-01'])
    assert.throws(() => exportKey('c_1', date), invalid, date);
});

test('the wrong shape still throws invalid export key', () => {
  for (const date of ['yesterday', '2026-1-02', '2026-11-2', ' 2026-11-02', '2026-11-02 ', '2026-11-02T00:00', '2026/11/02', '+02026-11-02', '', undefined])
    assert.throws(() => exportKey('c_1', date), invalid, String(date));
});

test('leap days: 2028-02-29 and 2000-02-29 accepted; 2026-02-29 and 2100-02-29 refused', () => {
  assert.equal(exportKey('c_1', '2028-02-29'), 'advisor/exports/c_1/2028-02-29.json');
  assert.equal(exportKey('c_1', '2000-02-29'), 'advisor/exports/c_1/2000-02-29.json');
  assert.throws(() => exportKey('c_1', '2026-02-29'), invalid);
  assert.throws(() => exportKey('c_1', '2100-02-29'), invalid);
});

test('a bad contact id still throws the same error on a real day', () => {
  for (const id of ['a b', 'x'.repeat(65), '', 'a/b', 'a.b'])
    assert.throws(() => exportKey(id, '2026-11-02'), invalid, id);
  assert.equal(exportKey('x'.repeat(64), '2026-11-02'), `advisor/exports/${'x'.repeat(64)}/2026-11-02.json`);
});

test('a token minted for a key still verifies; tokens are not date-checked', async () => {
  const uploadKey = await crypto.subtle.generateKey({name: 'HMAC', hash: 'SHA-256'}, false, ['sign', 'verify']);
  const keys = {uploadKey}, now = Date.parse('2026-11-02T20:00:00Z');
  const key = exportKey('c_1', '2026-11-02');
  const token = await mintExportToken(keys, 'c_1', key, now);
  assert.deepEqual(await verifyExportToken(keys, token, now + 1000), {contactId: 'c_1', key});
  assert.equal((await readExportToken(keys, token)).expiresAt, Math.floor(now / 1000) * 1000 + 24 * 3600000);
  assert.equal(await verifyExportToken(keys, token, now + 24 * 3600000 + 1000), null);
  // A key written before this change under an impossible day keeps its token shape (KEY regex unchanged).
  const legacy = 'advisor/exports/c_1/2026-02-30.json';
  assert.deepEqual(await verifyExportToken(keys, await mintExportToken(keys, 'c_1', legacy, now), now), {contactId: 'c_1', key: legacy});
});
