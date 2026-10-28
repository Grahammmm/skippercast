// Synthetic-only SP79 assertions. Also preloaded by the launcher to guard
// the unchanged original regression suite before its product imports.
import test, {after} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {syncBuiltinESMExports} from 'node:module';
import http from 'node:http';
import https from 'node:https';
import net from 'node:net';
import tls from 'node:tls';
import dns from 'node:dns';
import dgram from 'node:dgram';
import childProcess from 'node:child_process';

let attempts = 0;
const deny = () => { attempts++; throw new Error('SP79 offline boundary: network/model/child call prohibited'); };
globalThis.fetch = deny;
globalThis.WebSocket = class { constructor() { deny(); } };
for (const [object, keys] of [
  [http, ['request', 'get']], [https, ['request', 'get']],
  [net, ['connect', 'createConnection', 'createServer']], [net.Socket.prototype, ['connect']],
  [tls, ['connect', 'createServer']], [dns, ['lookup', 'resolve']],
  [dns.promises, ['lookup', 'resolve']], [dgram, ['createSocket']],
  [childProcess, ['exec', 'execFile', 'execSync', 'execFileSync', 'spawn', 'spawnSync', 'fork']],
]) for (const key of keys) object[key] = deny;
syncBuiltinESMExports();
// Never use browser/profile persistence, even if a transitive store is loaded.
const storage = new Map();
Object.defineProperty(globalThis, 'localStorage', {configurable: true, value: {
  getItem: key => storage.get(key) ?? null,
  setItem: (key, value) => storage.set(key, String(value)),
  removeItem: key => storage.delete(key), clear: () => storage.clear(),
}});
after(() => {
  console.log(`SP79_OFFLINE_ATTEMPTS ${attempts}`);
  assert.equal(attempts, 0, 'no network, model or subprocess call was attempted');
});

const suite = process.env.SP79_SUITE ?? 'focused';
if (!['baseline', 'focused', 'regression'].includes(suite)) throw new Error('Unknown SP79 test mode');
if (suite !== 'regression') {
  // The complete actual module is imported only AFTER all sentinels exist.
  const {sourceStation, stationText, ndbcStationURL, tideStationURL, tidePredictionURL, sharedStation} = await import('../web/station-label.ts');
  const fixtures = JSON.parse(readFileSync(new URL('./fixtures/sp79_backup_identity/cases.json', import.meta.url), 'utf8'));
  for (const item of [fixtures.primary, fixtures.control]) test(item.name, () => {
    let observed;
    try { observed = {returned: sourceStation(item.source, item.fallback)}; }
    catch (error) { observed = {exception: {name: error.name, message: error.message}}; }
    // Capture actual behavior as data before the semantic assertion.
    if (item === fixtures.primary) console.log(`SP79_PRIMARY_OBSERVED ${JSON.stringify(observed)}`);
    assert.deepEqual(observed, {returned: item.expected}, item.name);
  });
  if (suite === 'focused') {
    test('A1 no identity matrix never fabricates either caller fallback', () => {
      const missing = Symbol('absent');
      for (const explicit of [missing, ...fixtures.invalid_identifiers]) {
        for (const dataId of [missing, ...fixtures.invalid_identifiers]) {
          for (const fallback of fixtures.caller_fallbacks) {
            const source = {fallback_for: '46053', data: {observations: []}};
            if (explicit !== missing) source.station = explicit;
            if (dataId !== missing) source.data.station = dataId;
            assert.equal(sourceStation(source, fallback), null, JSON.stringify({source, fallback}));
          }
        }
      }
      for (const data of [undefined, null, false, 17, '46054', [], {}]) {
        assert.equal(sourceStation({fallback_for: '46053', data}, '46053'), null, `data shape ${JSON.stringify(data)}`);
      }
      assert.equal(sourceStation({fallback_for: '46053'}), null, 'no caller fallback either');
    });
    for (const item of fixtures.identified) test(item.name, () => {
      assert.deepEqual(sourceStation(item.source, item.fallback), item.expected, item.name);
    });
    test('A2 empty and every invalid explicit identity use valid data identity', () => {
      for (const station of fixtures.invalid_identifiers) {
        assert.deepEqual(sourceStation({station, fallback_for: '46053', data: {station: '46054'}}, '46053'), {id: '46054', backupFor: '46053'});
      }
    });
    test('A3 null missing and invalid backup declarations retain legacy fallback', () => {
      for (const source of [undefined, null, {}, {data: {station: '46054'}}]) {
        assert.deepEqual(sourceStation(source, ' 46053 '), {id: '46053', backupFor: null});
        assert.equal(sourceStation(source), null);
      }
      for (const fallback_for of fixtures.invalid_identifiers) {
        assert.deepEqual(sourceStation({fallback_for, data: {station: '46054'}}, '46053'), {id: '46053', backupFor: null});
        assert.deepEqual(sourceStation({fallback_for, station: '46054'}, '46053'), {id: '46054', backupFor: null});
      }
    });
    test('A3 identifier grammar and trimming remain unchanged in every identity position', () => {
      for (const value of fixtures.valid_identifiers) {
        const id = value.trim();
        assert.deepEqual(sourceStation({station: value}, 'OTHER_1'), {id, backupFor: null});
        assert.deepEqual(sourceStation(null, value), {id, backupFor: null});
        assert.deepEqual(sourceStation({fallback_for: 'PRIMARY', data: {station: value}}), {id, backupFor: 'PRIMARY'});
        assert.deepEqual(sourceStation({fallback_for: value, station: 'BACKUP'}), {id: 'BACKUP', backupFor: id});
        assert.equal(sourceStation({fallback_for: value}, 'OTHER_1'), null);
      }
      for (const value of fixtures.invalid_identifiers) {
        assert.equal(sourceStation({station: value}), null);
        assert.equal(sourceStation(null, value), null);
      }
    });
    test('A3 station labels official URL strings and sharing of identified readings unchanged', () => {
      const backup = sourceStation(fixtures.control.source, fixtures.control.fallback);
      const primary = sourceStation({station: '46054'}, '46054');
      assert.equal(stationText(backup), '46054 (backup for 46053)');
      assert.equal(stationText(primary), '46054');
      assert.equal(ndbcStationURL(backup.id), 'https://www.ndbc.noaa.gov/station_page.php?station=46054');
      assert.equal(tideStationURL('9411340'), 'https://tidesandcurrents.noaa.gov/stationhome.html?id=9411340');
      assert.equal(tidePredictionURL('9411340'), 'https://tidesandcurrents.noaa.gov/noaatidepredictions.html?id=9411340');
      assert.equal(ndbcStationURL('A B/'), 'https://www.ndbc.noaa.gov/station_page.php?station=A%20B%2F');
      assert.equal(tideStationURL('A B/'), 'https://tidesandcurrents.noaa.gov/stationhome.html?id=A%20B%2F');
      assert.equal(tidePredictionURL('A B/'), 'https://tidesandcurrents.noaa.gov/noaatidepredictions.html?id=A%20B%2F');
      assert.equal(sharedStation(backup, primary), true);
      assert.equal(sharedStation(primary, backup), true);
      assert.equal(sharedStation(primary, primary), false);
      assert.equal(sharedStation(backup, {id: '46055', backupFor: null}), false);
      assert.equal(sharedStation(null, backup), false);
      assert.equal(sharedStation(backup, undefined), false);
    });
  }
}
