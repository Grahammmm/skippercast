import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import http from 'node:http';
import https from 'node:https';
import net from 'node:net';
import tls from 'node:tls';
import dgram from 'node:dgram';
import {syncBuiltinESMExports} from 'node:module';

// Preload mode guards the unchanged compatibility suites before their imports.
// These sentinels detect accidental calls, not hostile-code sandbox escapes.
const attempts = [];
const deny = name => function () { attempts.push(name); throw Error(`SP80 offline sentinel: ${name}`); };
globalThis.fetch = deny('fetch');
globalThis.WebSocket = deny('WebSocket');
http.request = deny('http.request'); http.get = deny('http.get');
https.request = deny('https.request'); https.get = deny('https.get');
net.Socket.prototype.connect = deny('socket.connect');
tls.connect = deny('tls.connect');
dgram.Socket.prototype.send = deny('datagram.send');
syncBuiltinESMExports();
process.on('exit', () => { if (attempts.length) { console.error('SP80 unexpected offline attempts', attempts); process.exitCode = 1; } });

if (process.env.SP80_GUARD_ONLY !== '1') {
  // No browser identity may be touched, even when a product catches exceptions.
  for (const name of ['document', 'localStorage', 'window']) {
    Object.defineProperty(globalThis, name, {configurable: true, get: deny(name), set: deny(`${name}.set`)});
  }
  // The complete actual module has only a type import; no runtime import side effects.
  const {homeURL} = await import('../packages/coast/src/coast3d/preferences.ts');
  const fixture = JSON.parse(readFileSync(new URL('./fixtures/sp80_home_geography/cases.json', import.meta.url), 'utf8'));
  const preferences = Object.freeze(fixture.preferences);
  const invoke = (input, reset = false) => {
    const before = input.href, saved = JSON.stringify(preferences);
    const result = homeURL(input, preferences, reset);
    assert.notEqual(result, input, 'URL is cloned');
    assert.equal(input.href, before, 'input URL unchanged');
    assert.equal(JSON.stringify(preferences), saved, 'preferences unchanged');
    assert.deepEqual(attempts, [], 'no network, DOM, cookie or localStorage use');
    return result;
  };
  test('A4 primary explicit-region preserves geography', t => {
    // Capture product return/exception as data BEFORE the semantic assertion.
    let observation;
    try { observation = {place: invoke(new URL('https://example.test/coast?region=southern-california')).searchParams.get('place')}; }
    catch (error) { observation = {exception: {name: error.name, message: error.message}}; }
    t.diagnostic('SP80_OBSERVATION ' + JSON.stringify(observation));
    assert.deepEqual(observation, {place: null}, 'A4_REGION_MUST_NOT_GAIN_HOME_PLACE');
  });
  test('A4 healthy bare-address restores home', () => {
    const url = invoke(new URL('https://example.test/coast'));
    assert.equal(url.href, 'https://example.test/coast?place=morro&profile=boat');
  });
  if (process.env.SP80_BASELINE !== '1') {
    for (const row of fixture.locations) {
      for (const explicitProfile of [false, true]) {
        test(`A1/A2 ${row.id} ${explicitProfile ? 'explicit-profile' : 'saved-profile'}`, () => {
          const input = new URL(`https://example.test:8443/coast?${row.query}${explicitProfile ? '&profile=shore' : ''}#forecast`);
          const result = invoke(input);
          const expected = new URL(input);
          if (!explicitProfile) expected.searchParams.set('profile', preferences.mode);
          assert.equal(result.href, expected.href, 'all original query/hash values preserved; no home place injection');
        });
      }
    }
    test('A2 explicit empty profile wins presence-based rule on bare URL', () => {
      assert.equal(invoke(new URL('https://example.test/coast?profile=')).href, 'https://example.test/coast?profile=&place=morro');
    });
    test('A2 bare query/hash preserved with saved place and profile', () => {
      assert.equal(invoke(new URL('https://example.test/coast?utm_source=friend#map')).href, 'https://example.test/coast?utm_source=friend&place=morro&profile=boat#map');
    });
    for (const row of [...fixture.locations, {id: 'bare', query: ''}]) {
      test(`A3 reset ${row.id} restores exactly home`, () => {
        const input = new URL(`https://example.test:8443/coast?${row.query}&profile=spear&utm_source=friend#forecast`);
        const result = invoke(input, true);
        assert.equal(result.href, 'https://example.test:8443/coast?place=morro&profile=boat');
        assert.deepEqual([...result.searchParams], [['place', 'morro'], ['profile', 'boat']]);
        assert.equal(result.hash, '');
      });
    }
  }
}
