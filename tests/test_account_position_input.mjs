import test from 'node:test';
import assert from 'node:assert/strict';

const {logBody, spotBody, positionFieldHTML, submitPositionForm} = await import('../dist/account.js');

const near = (a, b, tol) => assert.ok(Math.abs(a - b) <= tol, `${a} is not within ${tol} of ${b}`);
const withFormat = (fmt, fn) => {
  const prev = Object.getOwnPropertyDescriptor(globalThis, 'localStorage');
  Object.defineProperty(globalThis, 'localStorage', {configurable: true, value: {getItem: () => fmt}});
  try { return fn(); } finally { prev ? Object.defineProperty(globalThis, 'localStorage', prev) : delete globalThis.localStorage; }
};

test('each format is read into the same decimal degrees, as numbers', () => {
  for (const make of [logBody, spotBody]) {
    const b = text => make({name: 'x', outcome: 'blank', ...text});
    const dd = b({lat: '35.3576', lon: '-120.8578'});
    assert.equal(typeof dd.lat, 'number');
    assert.deepEqual([dd.lat, dd.lon], [35.3576, -120.8578]);
    const ddm = b({lat: '35 21.456 N', lon: '-120 51.468'});
    near(ddm.lat, 35.3576, 1e-6); near(ddm.lon, -120.8578, 1e-6);
    const dms = b({lat: '35°21′27.36″N', lon: '120°51′28.08″W'});
    near(dms.lat, 35.3576, 1e-6); near(dms.lon, -120.8578, 1e-6);
  }
});

test('the body for a plain decimal input is today\'s body', () => {
  assert.deepEqual(spotBody({name: 'Reef', lat: '35.5', lon: '-121', note: 'n'}), {name: 'Reef', lat: 35.5, lon: -121, note: 'n'});
  const b = logBody({started: '2026-11-01T14:00', outcome: 'fish', count: '3', lat: '35.5', lon: '-121'});
  assert.equal(b.lat, 35.5); assert.equal(b.lon, -121); assert.equal(b.count, 3);
});

test('a refused position names its box and carries the parser reason', () => {
  for (const [make, extra] of [[logBody, {outcome: 'blank'}], [spotBody, {name: 'x'}]]) {
    assert.throws(() => make({...extra, lat: '35 61 N', lon: '-121'}), e => e.field === 'lat' && /less than 60/.test(e.message));
    assert.throws(() => make({...extra, lat: '35 E', lon: '-121'}), e => e.field === 'lat' && /longitude/.test(e.message));
    assert.throws(() => make({...extra, lat: '35', lon: 'abc'}), e => e.field === 'lon' && e.message.length > 5);
  }
});

test('the log form sends both or neither; the spot form needs both', () => {
  const none = logBody({outcome: 'blank', lat: '', lon: ' '});
  assert.equal(none.lat, null); assert.equal(none.lon, null);
  assert.throws(() => logBody({outcome: 'blank', lat: '35.5', lon: ''}), e => e.field === 'lon' && /both latitude and longitude, or neither/.test(e.message));
  assert.throws(() => logBody({outcome: 'blank', lat: '', lon: '-121'}), e => e.field === 'lat');
  assert.throws(() => spotBody({name: 'x', lat: '35.5', lon: ''}), e => e.field === 'lon');
});

test('the hint shows an example in each chosen format and the box is text', () => {
  const want = {dd: '35.35760° N', ddm: '35° 21.456′ N', dms: '35° 21′ 27.36″ N'};
  for (const [fmt, lat] of Object.entries(want)) {
    const html = withFormat(fmt, () => positionFieldHTML('log', 'lat', 'Latitude'));
    assert.ok(html.includes(lat), `${fmt} example`);
    assert.match(html, /id="log-lat" type="text"/);
    assert.match(html, /id="log-lat-error"[^>]* hidden/);
  }
  assert.ok(withFormat('ddm', () => positionFieldHTML('spot', 'lon', 'Longitude')).includes('120° 51.468′ W'));
});

function fakeDom() {
  const els = {};
  const $ = sel => els[sel] ??= {textContent: '', hidden: true, attrs: {}, focused: false,
    setAttribute(k, v) { this.attrs[k] = v; }, removeAttribute(k) { delete this.attrs[k]; }, focus() { this.focused = true; }};
  return {$, els};
}

test('a refusal is shown beside its field, focuses it and sends nothing; a good parse clears it', async () => {
  const {$, els} = fakeDom();
  const sent = [];
  const send = async body => sent.push(body);
  const ok = await submitPositionForm($, 'spot', () => spotBody({name: 'x', lat: '35 61 N', lon: '-121'}), send);
  assert.equal(ok, false); assert.equal(sent.length, 0);
  assert.match(els['#spot-lat-error'].textContent, /less than 60/);
  assert.equal(els['#spot-lat-error'].hidden, false);
  assert.equal(els['#spot-lat'].attrs['aria-invalid'], 'true');
  assert.equal(els['#spot-lat'].focused, true);
  assert.equal(els['#spot-lon-error'].textContent, '');

  const ok2 = await submitPositionForm($, 'spot', () => spotBody({name: 'x', lat: '35 21.456 N', lon: '-120 51.468'}), send);
  assert.equal(ok2, true); assert.equal(sent.length, 1);
  near(sent[0].lat, 35.3576, 1e-6); near(sent[0].lon, -120.8578, 1e-6);
  assert.equal(els['#spot-lat-error'].hidden, true); assert.equal(els['#spot-lat-error'].textContent, '');
  assert.equal(els['#spot-lat'].attrs['aria-invalid'], undefined);
});

test('log form with only latitude shows the error on longitude and sends nothing', async () => {
  const {$, els} = fakeDom();
  const sent = [];
  await submitPositionForm($, 'log', () => logBody({outcome: 'blank', lat: '35.5', lon: ''}), async b => sent.push(b));
  assert.equal(sent.length, 0);
  assert.match(els['#log-lon-error'].textContent, /both latitude and longitude/);
  assert.equal(els['#log-lon'].focused, true);
});

test('an error that is not a field error is rethrown', async () => {
  const {$} = fakeDom();
  await assert.rejects(submitPositionForm($, 'log', () => { throw Error('boom'); }, async () => {}), /boom/);
});
