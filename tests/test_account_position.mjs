import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

const {createPositionControl, positionFromFix, positionFailure, positionControlsHTML, POSITION_OPTIONS, createCopy} = await import('../dist/account.js');
const catalog = JSON.parse(readFileSync(new URL('../catalog/app/strings.json', import.meta.url), 'utf8')).strings;
const source = readFileSync(new URL('../dist/account.js', import.meta.url), 'utf8');

// A small stand-in for the form's elements: just what the control touches.
function el(extra = {}) {
  const attrs = new Map(), listeners = {};
  return {value: '', disabled: false, textContent: '', hidden: false, isConnected: true, events: [], ...extra,
    setAttribute(k, v) { attrs.set(k, String(v)); }, getAttribute: k => attrs.has(k) ? attrs.get(k) : null, removeAttribute: k => attrs.delete(k),
    addEventListener(type, fn) { (listeners[type] ??= []).push(fn); },
    dispatchEvent(event) { this.events.push(event.type); return true; },
    click() { for (const fn of listeners.click ?? []) fn({}); }};
}
function form(prefix = 'log') {
  const els = {[`#${prefix}-use-position`]: el(), [`#${prefix}-lat`]: el({value: ''}), [`#${prefix}-lon`]: el({value: ''}), [`#${prefix}-save`]: el(),
    [`#${prefix}-lat-error`]: el({hidden: true}), [`#${prefix}-lon-error`]: el({hidden: true}), [`#${prefix}-position-status`]: el()};
  return {els, $: sel => els[sel] ?? null, button: els[`#${prefix}-use-position`], lat: els[`#${prefix}-lat`], lon: els[`#${prefix}-lon`], save: els[`#${prefix}-save`], status: els[`#${prefix}-position-status`]};
}
const fix = (latitude, longitude, accuracy) => ({coords: {latitude, longitude, accuracy}});
function geo() {
  const g = {calls: [], watch: 0, getCurrentPosition(ok, fail, options) { g.calls.push({ok, fail, options}); }, watchPosition() { g.watch++; }};
  return g;
}
const make = (f, g, extra = {}) => createPositionControl({$: f.$, prefix: 'log', copy: undefined, geolocation: () => g, ...extra});
const said = f => f.status.textContent;
const en = (id, vars) => createCopy()(id, vars);

test('importing and building the control ask nothing; only a press asks once, for a fresh high-accuracy fix', () => {
  const f = form(), g = geo();
  make(f, g);
  assert.equal(g.calls.length, 0, 'wiring a form asks for no position');
  f.button.click();
  assert.equal(g.calls.length, 1);
  assert.deepEqual(g.calls[0].options, {enableHighAccuracy: true, timeout: 15000, maximumAge: 0});
  assert.equal(POSITION_OPTIONS.maximumAge, 0);
  assert.equal(g.watch, 0, 'never a watch');
  f.button.click(); f.button.click();
  assert.equal(g.calls.length, 1, 'a second press while pending does nothing');
  assert.equal(said(f), en('account.position.finding'));
  assert.ok([f.button, f.lat, f.lon, f.save].every(x => x.disabled), 'controls rest while pending');
});

test('opening the panel asks nothing: the only geolocation call sits in the button handler', () => {
  const calls = source.split('\n').filter(line => /getCurrentPosition|watchPosition|permissions\.query/.test(line)).filter(line => !/^\s*(\/\/|\*|\/\*)/.test(line));
  assert.equal(calls.length, 2, calls.join('\n'));   // the typeof check and the one call
  assert.ok(!/watchPosition|permissions\.query/.test(source.replace(/\/\/.*$/gm, '').replace(/'never a watch'/g, '')));
  const handler = source.slice(source.indexOf("button.addEventListener('click'"), source.indexOf('return {invalidate, get pending'));
  assert.ok(handler.includes('geo.getCurrentPosition('), 'the call is inside the click handler');
});

test('a fix fills both boxes with six decimals, says the accuracy rounded up, and saves nothing', () => {
  const f = form(), g = geo(); make(f, g);
  f.button.click();
  g.calls[0].ok(fix(35.12345678, -120.98765432, 34.2));
  assert.equal(f.lat.value, '35.123457'); assert.equal(f.lon.value, '-120.987654');
  assert.equal(said(f), en('account.position.filled', {accuracy: 35}));
  assert.deepEqual(f.lat.events, ['input']); assert.deepEqual(f.lon.events, ['input']);
  assert.ok([f.button, f.lat, f.lon, f.save].every(x => !x.disabled), 'controls come back');
  f.button.click();
  assert.equal(g.calls.length, 2, 'a deliberate retry is allowed');
});

test('an accuracy of 0 is valid; negative zero is written as zero; a fix is never kept beyond the pair', () => {
  assert.deepEqual(positionFromFix(fix(-0.0000001, 0.0000004, 0)), {lat: '0.000000', lon: '0.000000', accuracy: 0});
  assert.deepEqual(positionFromFix({coords: {latitude: 1, longitude: 2, accuracy: 3, altitude: 9, speed: 4}}), {lat: '1.000000', lon: '2.000000', accuracy: 3});
});

test('a refusal, a time-out, an unavailable device and a throw each say so in words and leave the boxes as they were', () => {
  for (const [how, want] of [[{code: 1}, 'denied'], [{code: 2}, 'unavailable'], [{code: 3}, 'timeout'], [{}, 'unavailable'], [null, 'unavailable']]) {
    const f = form(); f.lat.value = '35.5'; const g = geo(); make(f, g);
    f.button.click(); g.calls[0].fail(how);
    assert.equal(said(f), en('account.position.' + want), String(how?.code));
    assert.equal(f.lat.value, '35.5'); assert.equal(f.lon.value, '');
    assert.ok(!f.button.disabled && !f.save.disabled, 'retry is possible');
  }
  for (const [error, want] of [[Object.assign(Error('x'), {name: 'SecurityError'}), 'denied'], [Error('boom'), 'unavailable']]) {
    const f = form(); f.lon.value = '-121'; const g = {getCurrentPosition() { throw error; }}; make(f, g);
    f.button.click();
    assert.equal(said(f), en('account.position.' + want));
    assert.equal(f.lat.value, ''); assert.equal(f.lon.value, '-121'); assert.ok(!f.button.disabled);
  }
  assert.equal(positionFailure({code: 1}), 'denied');
});

test('no geolocation says so, throws nothing and changes nothing', () => {
  for (const missing of [undefined, null, {}]) {
    const f = form(); f.lat.value = '1'; f.lon.value = '2'; make(f, missing);
    f.button.click();
    assert.equal(said(f), en('account.position.unsupported'));
    assert.equal(f.lat.value, '1'); assert.equal(f.lon.value, '2'); assert.ok(!f.button.disabled);
  }
});

test('an unusable fix is unavailable and changes neither box', () => {
  for (const bad of [null, {}, fix(NaN, 1, 1), fix(1, Infinity, 1), fix(1, 1, NaN), fix(1, 1, -1), fix(1, 1, undefined), fix('1', 2, 3), fix(90, 0, 5), fix(-90, 0, 5), fix(0, 180, 5), fix(0, -180, 5), fix(89.9999996, 0, 5), fix(0, 179.9999996, 5)]) {
    const f = form(); f.lat.value = '10'; const g = geo(); make(f, g);
    f.button.click(); g.calls[0].ok(bad);
    assert.equal(said(f), en('account.position.unavailable'), JSON.stringify(bad));
    assert.equal(f.lat.value, '10'); assert.equal(f.lon.value, '');
  }
});

test('a late answer after invalidation, close or a replaced render changes nothing; controls return to their earlier state', () => {
  const f = form(), g = geo(); f.save.disabled = true;
  const c = make(f, g);
  f.button.click(); assert.ok(c.pending);
  c.invalidate();
  assert.ok(!c.pending); assert.equal(said(f), ''); assert.equal(f.save.disabled, true, 'a Save that was already disabled stays disabled'); assert.ok(!f.button.disabled);
  g.calls[0].ok(fix(1, 2, 3)); g.calls[0].fail({code: 1});
  assert.equal(f.lat.value, ''); assert.equal(said(f), '');

  const f2 = form(), g2 = geo(); let live = true; make(f2, g2, {alive: () => live});
  f2.button.click(); live = false; g2.calls[0].ok(fix(1, 2, 3));
  assert.equal(f2.lat.value, '');
  const f3 = form(), g3 = geo(); make(f3, g3);
  f3.button.click(); f3.button.isConnected = false; g3.calls[0].ok(fix(1, 2, 3));
  assert.equal(f3.lat.value, '');
  const f4 = form(), g4 = geo(); let blocked = true; make(f4, g4, {blocked: () => blocked});
  f4.button.click(); assert.equal(g4.calls.length, 0, 'a blocked form never asks'); blocked = false; f4.button.click(); assert.equal(g4.calls.length, 1);
});

test('each form is independent', () => {
  const a = form('log'), b = form('spot'), g = geo();
  createPositionControl({$: a.$, prefix: 'log', geolocation: () => g}); createPositionControl({$: b.$, prefix: 'spot', geolocation: () => g});
  a.button.click(); b.button.click();
  assert.equal(g.calls.length, 2);
  g.calls[1].ok(fix(1, 2, 3));
  assert.equal(b.lat.value, '1.000000'); assert.equal(a.lat.value, ''); assert.ok(a.button.disabled);
});

test('the new words exist in English and Spanish with matching placeholders, and the privacy sentences are kept', () => {
  const ids = ['use', 'finding', 'filled', 'unsupported', 'denied', 'unavailable', 'timeout', 'hint'].map(n => 'account.position.' + n);
  for (const id of ids) {
    assert.ok(catalog[id]?.en && catalog[id]?.es, id);
    assert.equal(catalog[id].en.match(/\{\w+\}/g)?.join() ?? '', catalog[id].es.match(/\{\w+\}/g)?.join() ?? '', id);
  }
  assert.equal(catalog['account.position.use'].es, 'Usar mi ubicación');
  assert.ok(positionControlsHTML('log').includes('id="log-use-position"') && positionControlsHTML('spot').includes('Use my position'));
  assert.ok(positionControlsHTML('log', createCopy({lang: 'es', strings: Object.fromEntries(ids.map(id => [id, catalog[id].es]))})).includes('Usar mi ubicación'));
  assert.ok(catalog['account.log.fine'].en.includes('A position is never shared, mapped or put in a feed.'));
  const privacy = readFileSync(new URL('../dist/privacy.html', import.meta.url), 'utf8').replace(/\s+/g, ' ');
  assert.ok(privacy.includes('asks your browser for one fresh location only when you press it'));
  assert.ok(privacy.includes('Nothing is sent to SkipperCast until you press Save'));
  assert.ok(privacy.includes('your location is used in the browser only and is not sent to SkipperCast'));
});

test('the catch-log redraw keeps Save off while a position request is pending, and lets it go afterwards', () => {
  // drawLog rewrites Save on every filter change, older-page load and initial read: its calculation must include logPos.pending.
  const line = source.split('\n').find(l => l.includes("$('#log-save').disabled ="));
  assert.ok(line && /logPos\?\.pending/.test(line), 'drawLog counts the pending position request');
  assert.match(source, /let editing = null, tripRegion = null, logPos = null;/, 'logPos exists before the first redraw can read it');
  // The same calculation, run as drawLog runs it, on a control whose redraw is wired as `after`.
  const f = form(), g = geo(); let editing = null, busy = false, c = null;
  const draw = () => { f.save.disabled = Boolean((editing && (busy || editing.pending)) || c?.pending); };
  c = make(f, g, {after: draw});
  f.button.click(); assert.ok(c.pending); assert.equal(f.save.disabled, true);
  busy = true; draw(); busy = false; draw();   // a filter change / older-page load / log read finishing mid-request
  assert.equal(f.save.disabled, true, 'a redraw during the request does not re-enable Save');
  g.calls[0].ok(fix(1, 2, 3));
  assert.equal(f.save.disabled, false, 'Save returns once the answer arrives');
});
