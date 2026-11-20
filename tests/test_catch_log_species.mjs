import test from 'node:test';
import assert from 'node:assert/strict';
import {isDeepStrictEqual} from 'node:util';
import {registerHooks} from 'node:module';

// Only region metadata is substituted. The real account render and registered submit handlers run offline.
let metadata = () => null, importFails = false;
const hooks = registerHooks({
  resolve(specifier, context, next) {
    if (specifier === './region.js' && context.parentURL?.endsWith('/dist/account.js') && importFails) throw Error('region import unavailable');
    return next(specifier, context);
  },
  load(url, context, next) {
    if (url.endsWith('/dist/region.js')) return {format: 'module', shortCircuit: true, source: 'export const getRegion = () => globalThis.__catchSpeciesRegion();'};
    if (url.endsWith('/dist/protected-areas.js')) return {format: 'module', shortCircuit: true, source: 'export const initProtectedAreas = () => null;'};
    return next(url, context);
  },
});
globalThis.__catchSpeciesRegion = () => metadata();
const {logSpeciesOptionsHTML, openAccount} = await import('../dist/account.js');
const same = (a, b, message) => assert.ok(isDeepStrictEqual(a, b), message);
const region = {species: ['reef', 'halibut', 'reef', 'fallback'], target_options: [
  {id: 'outside', name: 'Not regional'}, {id: 'reef', name: 'Lingcod & rockfish'},
  {id: 'reef', name: 'Ignored second name'}, {id: 'halibut', name: 'California halibut'},
]};
const decode = s => s.replace(/&(amp|lt|gt|quot|#39);/g, (_, c) => ({amp: '&', lt: '<', gt: '>', quot: '"', '#39': "'"})[c]);

// Synthetic DOM parses the actual generated markup (including option values/entities), not a source-regex wiring check.
class Element {
  constructor(tag) { this.tagName = tag.toUpperCase(); this.attrs = {}; this.children = []; this.parentElement = null; this.listeners = {}; this.value = ''; this.textContent = ''; this.disabled = false; this.hidden = false; }
  get id() { return this.attrs.id; }
  set className(value) { this.attrs.class = value; }
  get classList() { return {add() {}, remove() {}}; }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return this.attrs[k] ?? null; }
  hasAttribute(k) { return k in this.attrs; }
  removeAttribute(k) { delete this.attrs[k]; }
  append(child) { child.parentElement = this; this.children.push(child); }
  remove() { this.parentElement.children = this.parentElement.children.filter(c => c !== this); this.parentElement = null; }
  get isConnected() { return this === document.body || Boolean(this.parentElement?.isConnected); }
  contains(el) { return el === this || this.children.some(c => c.contains(el)); }
  all() { return this.children.flatMap(c => [c, ...c.all()]); }
  matches(s) {
    if (s.startsWith('#')) return this.id === s.slice(1);
    if (s.startsWith('.')) return (this.attrs.class ?? '').split(' ').includes(s.slice(1));
    if (s.startsWith('[')) return this.hasAttribute(s.slice(1, -1));
    return this.tagName === s.toUpperCase();
  }
  querySelectorAll(s) { return this.all().filter(el => el.matches(s)); }
  querySelector(s) { return this.querySelectorAll(s)[0] ?? null; }
  get options() { return this.querySelectorAll('option'); }
  addEventListener(type, fn) { (this.listeners[type] ??= []).push(fn); }
  async fire(type) { for (const fn of this.listeners[type] ?? []) await fn({target: this, preventDefault() {}}); }
  focus() { document.activeElement = this; }
  reset() { for (const el of this.all()) if (['INPUT', 'SELECT'].includes(el.tagName)) el.value = el.tagName === 'SELECT' ? el.options[0]?.value ?? '' : ''; }
  set innerHTML(html) {
    this._html = html;
    for (const el of this.children) el.parentElement = null;
    this.children = [];
    const stack = [this];
    for (const match of html.matchAll(/<\/?[a-z][^>]*>|[^<]+/gi)) {
      const token = match[0];
      if (!token.startsWith('<')) { stack.at(-1).textContent += decode(token); continue; }
      if (token.startsWith('</')) { if (stack.length > 1) stack.pop(); continue; }
      const tag = token.match(/^<(\w+)/)[1], el = new Element(tag);
      for (const attr of token.matchAll(/\s([\w-]+)(?:="([^"]*)")?/g)) el.attrs[attr[1]] = decode(attr[2] ?? '');
      el.hidden = el.hasAttribute('hidden'); el.disabled = el.hasAttribute('disabled'); el.value = el.attrs.value ?? '';
      stack.at(-1).append(el);
      if (!['INPUT', 'BR', 'HR'].includes(el.tagName)) stack.push(el);
    }
    for (const el of this.querySelectorAll('select')) el.value = el.options[0]?.value ?? '';
  }
  get innerHTML() { return this._html ?? ''; }
}
const document = {body: new Element('body'), createElement: tag => new Element(tag), activeElement: null};
const originals = Object.fromEntries(['document', 'location', 'fetch', '__catchSpeciesRegion'].map(k => [k, globalThis[k]]));
globalThis.document = document;
globalThis.location = {hash: '', pathname: '/map', search: ''};
let calls, posts, unexpected, trips, geoCalls = 0;
const navDescriptor = Object.getOwnPropertyDescriptor(globalThis, 'navigator');
Object.defineProperty(globalThis, 'navigator', {configurable: true, value: {geolocation: {getCurrentPosition() { geoCalls++; }}}});
const tick = () => new Promise(resolve => setImmediate(resolve));
const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return {promise, resolve, reject}; };
const $ = s => document.body.querySelector(s);
const values = () => $('#log-species-suggestions').options.map(o => o.value);
async function close() { if ($('.home-port-close')) await $('.home-port-close').fire('click'); }
async function openWith(read = () => region, tripRead = () => Promise.resolve({trips: []})) {
  await close(); metadata = read; trips = tripRead; calls = []; posts = []; unexpected = [];
  globalThis.fetch = async (url, options) => {
    calls.push(url);
    let data;
    if (url === '/api/session') data = {signedIn: true, signIn: '/#account', user: {}};
    else if (url === '/api/auth/passkeys') data = {passkeys: []};
    else if (url === '/api/catch-log' && options.method === 'POST') { posts.push(JSON.parse(options.body)); data = {}; }
    else if (url === '/api/catch-log') data = {entries: []};
    else if (url === '/api/trips') data = await trips();
    else if (url === '/api/spots') data = {spots: [{id: 'synthetic-spot', name: 'Synthetic spot', lat: 35, lon: -120}]};
    else if (url === '/api/auth/sessions') data = {sessions: []};
    else { unexpected.push(url); throw Error('unmocked request ' + url); }
    return {ok: true, json: async () => data, headers: new Headers({'X-SC-Catch-Log-Has-More': 'false'})};
  };
  await openAccount(); await tick(); await tick();
}
test.after(async () => {
  await close(); hooks.deregister(); Object.assign(globalThis, originals);
  if (navDescriptor) Object.defineProperty(globalThis, 'navigator', navDescriptor); else delete globalThis.navigator;
});

function projected(input) { const list = new Element('datalist'); list.innerHTML = logSpeciesOptionsHTML(input); return list.options.map(o => o.value); }
test('regional_species_names_only', () => {
  same(projected(region), ['Lingcod & rockfish', 'California halibut', 'fallback'], 'ordered, exact-ID deduplicated regional names only');
  same(projected({species: [null, 1, {}, '', ' ', 'ok', 'OK'], target_options: [null, {id: 'ok', name: 7}, {id: 'ok', name: ''}, {id: 'ok', name: 'First valid'}, {id: 'OK', name: ' '}] }), ['First valid', 'OK'], 'invalid metadata ignored, exact case retained');
  same(projected({species: ['a', 'b', 'c'], target_options: [{id: 'a', name: 'a'.repeat(60)}, {id: 'b', name: 'b'.repeat(61)}, {id: 'c', name: '🐟'.repeat(31)}]}), ['a'.repeat(60)], 'overlong UTF-16 values omitted, not truncated');
});
test('no_region_leaves_free_text', async () => {
  for (const data of [null, undefined, {}, {species: {}}, {species: []}, {species: [null, '', 2]}, {species: ['x'], target_options: [{id: 'x', name: 'x'.repeat(61)}]}]) {
    const wait = deferred(); await openWith(() => wait.promise); $('#log-species').value = 'Ling cod';
    wait.resolve(data); await tick();
    same(values(), [], 'no usable options'); assert.equal($('#log-species').getAttribute('list'), null);
    assert.equal($('#log-species').value, 'Ling cod'); same(unexpected, [], 'no extra request');
  }
  importFails = true;
  try { await openWith(); same(values(), [], 'failed import'); assert.equal($('#log-species').getAttribute('list'), null); }
  finally { importFails = false; }
});
test('species_options_escape_markup', async () => {
  const name = `\"'><img src=x>& fish`;
  await openWith(() => ({species: ['x'], target_options: [{id: 'x', name}]}));
  same(values(), [name], 'escaped HTML decodes to original value');
  assert.equal($('#log-species-suggestions').children.length, 1); assert.equal($('img'), null);
  same(Object.keys($('#log-species-suggestions').options[0].attrs), ['value'], 'no injected attribute');
  $('#log-species').value = values()[0]; await $('#log-form').fire('submit');
  assert.equal(posts[0].species, name, 'no escaped entity text in POST');
});
test('suggestions_do_not_wait_for_trips', async () => {
  for (const tripRead of [() => new Promise(() => {}), () => Promise.reject(Error('trips refused'))]) {
    await openWith(() => region, tripRead);
    same(values(), ['Lingcod & rockfish', 'California halibut', 'fallback'], 'suggestions independent of trips');
    assert.equal($('#log-species').getAttribute('list'), $('#log-species-suggestions').id);
    assert.equal($('#log-species').getAttribute('maxlength'), '60');
    assert.equal($('#log-species').getAttribute('type'), 'text'); assert.equal($('#log-species').value, '');
    for (const attr of ['required', 'pattern']) assert.equal($('#log-species').getAttribute(attr), null);
  }
});
test('late_region_keeps_typing_and_dialog_owner', async () => {
  const wait = deferred(); await openWith(() => wait.promise, () => new Promise(() => {}));
  const input = $('#log-species'); input.value = 'already typing'; wait.resolve(region); await tick();
  assert.equal($('#log-species'), input); assert.equal(input.value, 'already typing'); assert.ok(values().length);
  const old = deferred(); await openWith(() => old.promise, () => new Promise(() => {})); const oldList = $('#log-species-suggestions');
  await close(); await openWith(() => ({species: ['new region']}), () => new Promise(() => {}));
  $('#log-species').value = 'new draft'; old.resolve(region); await tick();
  same(values(), ['new region'], 'old dialog cannot replace new region'); assert.equal($('#log-species').value, 'new draft');
  assert.equal(oldList.options.length, 0, 'detached render not hydrated');
  await close(); await openWith(() => null); same(values(), [], 'no cached cross-dialog options');
  const expired = deferred(); await openWith(() => expired.promise); $('#log-species').value = 'still editable';
  expired.reject(Error('metadata expired')); await tick(); assert.equal($('#log-species').value, 'still editable'); same(values(), [], 'failed deferred metadata');
});
test('unlisted_species_saved_exactly', async () => {
  await openWith();
  for (const name of ['Ling cod', 'ling', '  unlisted fish  ', 'x'.repeat(60), values()[0]]) {
    $('#log-species').value = name; await $('#log-form').fire('submit'); assert.equal(posts.at(-1).species, name);
  }
  assert.equal(posts.length, 5); same(unexpected, [], 'only stubbed account requests');
});
test('new_controls_preserve_upstream_form', async () => {
  await openWith(() => region, () => Promise.resolve({trips: [{id: 'synthetic-trip', date: '2026-11-04', region: 'test-region', point: 'p'}]}));
  assert.equal(geoCalls, 0, 'metadata never asks for location');
  for (const id of ['log-use-position', 'log-spot', 'log-trip']) assert.ok($('#' + id), id);
  $('#log-species').value = 'ling'; $('#log-trip').value = 'synthetic-trip'; $('#log-spot').value = 'synthetic-spot'; await $('#log-spot').fire('change');
  assert.equal($('#log-lat').value, '35'); assert.equal($('#log-lon').value, '-120'); assert.equal($('#log-species').value, 'ling');
  await $('#log-form').fire('submit'); assert.equal(posts[0].trip_id, 'synthetic-trip'); assert.equal(posts[0].species, 'ling'); assert.equal(posts[0].lat, 35);
  same(unexpected, [], 'all external fetches refused'); assert.equal(geoCalls, 0);
});
