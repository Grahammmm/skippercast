import test from 'node:test';
import assert from 'node:assert/strict';
import {isDeepStrictEqual} from 'node:util';
import {readFileSync} from 'node:fs';
import {registerHooks} from 'node:module';
const hooks = registerHooks({load(url, context, next) {
  if (url.endsWith('/dist/region.js')) return {format: 'module', shortCircuit: true, source: 'export const getRegion = () => null;'};
  if (url.endsWith('/dist/protected-areas.js')) return {format: 'module', shortCircuit: true, source: 'export const initProtectedAreas = () => null;'};
  return next(url, context);
}});
const {catchLogCsv, readCsvCatchLog, readLogPage, openAccount, CSV_PAGE_CAP} = await import('../dist/account.js');
const same = (a, b, message) => assert.ok(isDeepStrictEqual(a, b), message);
const catalog = JSON.parse(readFileSync(new URL('../catalog/app/strings.json', import.meta.url))).strings;
const row = (id = 'synthetic-entry', extra = {}) => ({id, started_at: '2026-11-04T12:34:56.789Z', outcome: 'fish', count: 2, ...extra});
const header = 'started_at,outcome,count,species,method,latitude,longitude,trip_date,note\r\n';
const page = (entries = [], nextCursor = null) => ({entries, hasMore: nextCursor !== null, nextCursor});
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
// Independent CSV parser: quoted CR/LF stay in a cell, record boundaries must be CRLF.
function parse(csv) {
  const rows = []; let fields = [], cell = '', quoted = false;
  for (let i = 0; i < csv.length; i++) {
    const c = csv[i];
    if (c === '"') { if (quoted && csv[i + 1] === '"') { cell += '"'; i++; } else quoted = !quoted; }
    else if (!quoted && c === ',') { fields.push(cell); cell = ''; }
    else if (!quoted && c === '\r') { assert.equal(csv[++i], '\n'); fields.push(cell); rows.push(fields); fields = []; cell = ''; }
    else { assert.ok(quoted || c !== '\n'); cell += c; }
  }
  assert.ok(!quoted && !fields.length && !cell); return rows;
}
test('csv_schema_rows_and_optional_fields', () => {
  const rows = [row('a', {species: 'cod', method: 'jig', lat: 0, lon: -120.987654321, trip_id: 'trip', note: 'private & exact', owner: 'not-a-column'}),
    row('b', {outcome: 'blank', count: 0, trip_id: 'orphan'}), row('c', {outcome: 'unknown', count: 0, trip_id: null})];
  const expected = header + '"2026-11-04T12:34:56.789Z","fish",2,"cod","jig",0,-120.987654321,"2026-02-28","private & exact"\r\n' +
    '"2026-11-04T12:34:56.789Z","blank",0,"","",,,"",""\r\n' + '"2026-11-04T12:34:56.789Z","unknown",0,"","",,,"",""\r\n';
  same(catchLogCsv(rows, [{id: 'trip', date: '2026-02-28'}, {id: 'different', date: '2026-01-01'}]), expected, 'fixed CSV bytes and exact saved date');
  assert.ok(parse(expected).every(r => r.length === 9));
  assert.ok(catchLogCsv([row('tiny', {lat: 1e-7, lon: -1e-8})], []).includes(',0.0000001,-0.00000001,'));
});
test('csv_quoting_roundtrips_text', () => {
  for (const text of ['a,b', 'a"b', 'a\r\nb', 'a\rb', 'a\nb', 'A & B', '<img src=x>', '🐟 pez café']) {
    const parsed = parse(catchLogCsv([row('a', {species: text, method: text, note: text})], []));
    same([parsed[1][3], parsed[1][4], parsed[1][8]], [text, text, text], 'independent quoted cell roundtrip');
    assert.ok(parsed.every(r => r.length === 9));
  }
});
test('formula_text_numeric_boundary', () => {
  for (const field of ['species', 'method', 'note']) for (const marker of ['=', '+', '-', '@', '\t', '\r', '  =', '\n@', ' \n-']) {
    const original = marker + 'SUM(1,2)"\r\nnext';
    const result = catchLogCsv([row('a', {[field]: original, lat: 0, lon: -120.987654321})], []);
    assert.equal(parse(result)[1][{species: 3, method: 4, note: 8}[field]], "'" + original);
    assert.ok(result.includes(',0,-120.987654321,'), 'numeric cells stay numbers');
  }
  assert.equal(parse(catchLogCsv([row('a', {note: "'=unchanged"})], []))[1][8], "'=unchanged");
  for (const change of [{outcome: '=bad'}, {outcome: {}}, {started_at: '2026-02-30T12:34:56.789Z'}, {started_at: '2026-11-04'},
    {started_at: '2026-11-04T12:34:56Z'}, {count: '2'}, {count: {}}, {count: NaN}, {count: Infinity}, {count: 0}, {count: 1.5}, {count: 10000},
    {outcome: 'blank', count: 1}, {outcome: 'unknown', count: 1}, {lat: '1', lon: 2}, {lat: {}, lon: 2}, {lat: NaN, lon: 2},
    {lat: 1, lon: Infinity}, {lat: 90, lon: 1}, {lat: 1, lon: -180}, {lat: 1}, {id: ''}, {id: 1}, {species: {}},
    {species: '🐟'.repeat(61)}, {method: 'x'.repeat(41)}, {note: 'x'.repeat(1001)}, {trip_id: ''}, {trip_id: {}}, {trip_id: 'x'.repeat(65)}]) {
    assert.throws(() => catchLogCsv([row('a', change)], []));
  }
  assert.doesNotThrow(() => catchLogCsv([row('a', {species: '🐟'.repeat(60), method: 'x'.repeat(40), note: 'x'.repeat(1000)})], []));
});
test('complete_cursor_walk', async () => {
  for (const n of [0, 200, 201, 450]) {
    let reads = 0;
    const data = Array.from({length: n}, (_, i) => row(String(i)));
    const result = await readCsvCatchLog(async cursor => {
      const start = cursor === null ? 0 : Number(cursor); reads++;
      return page(data.slice(start, start + 200), start + 200 < n ? String(start + 200) : null);
    });
    assert.equal(result.length, n); assert.equal(reads, Math.max(1, Math.ceil(n / 200)));
  }
  let reads = 0;
  const pages = [page([row('a')], 'opaque +/?='), page([], 'two'), page([row('a', {note: 'later'}), row('b')])];
  const result = await readCsvCatchLog(async cursor => { same(cursor, [null, 'opaque +/?=', 'two'][reads]); return pages[reads++]; });
  same(result.map(r => r.id), ['a', 'b']); assert.equal(result[0].note, undefined); assert.equal(reads, 3);
  await assert.rejects(readCsvCatchLog(async () => page([row('a'), row('a', {count: '2'})])));
});
test('page_cap_and_cursor_cycles_download_nothing', async () => {
  assert.equal(CSV_PAGE_CAP, 10);
  for (const ends of [true, false]) {
    let reads = 0;
    const walk = readCsvCatchLog(async () => { reads++; return page([row(String(reads))], reads === 10 && ends ? null : 'c' + reads); });
    if (ends) assert.equal((await walk).length, 10); else await assert.rejects(walk);
    assert.equal(reads, 10, 'never page eleven');
  }
  for (const next of [['same', 'same'], ['a', 'b', 'a']]) {
    let reads = 0;
    await assert.rejects(readCsvCatchLog(async () => page([], next[reads++]))); assert.equal(reads, next.length);
  }
  for (const answer of [{}, {entries: {}}, {entries: [], hasMore: false, nextCursor: 'stray'}, {entries: [], hasMore: true},
    {entries: [], hasMore: 'false'}, page([{}])]) await assert.rejects(readCsvCatchLog(async () => answer));
  let live = false, reads = 0;
  await assert.rejects(readCsvCatchLog(async () => { reads++; }, () => live)); assert.equal(reads, 0);
  live = true;
  await assert.rejects(readCsvCatchLog(async () => { reads++; live = false; return page([], 'next'); }, () => live)); assert.equal(reads, 1);
});

const originals = Object.fromEntries(['document', 'location', 'fetch', 'Blob'].map(k => [k, globalThis[k]]));
const originalCreate = URL.createObjectURL, originalRevoke = URL.revokeObjectURL;
globalThis.document = document; globalThis.location = {hash: '', pathname: '/map', search: '', reload() {}};
const $ = s => document.body.querySelector(s);
const tick = () => new Promise(resolve => setImmediate(resolve));
const deferred = () => { let resolve; const promise = new Promise(yes => { resolve = yes; }); return {promise, resolve}; };
let requests, blobs, clicks, revoked, anchors, exporting, logRead, tripRead, construction;
const response = (data, more = 'false', next = null, status = 200) => ({ok: status < 400, status,
  json: async () => data, headers: new Headers({...more === null ? {} : {'X-SC-Catch-Log-Has-More': more}, ...next === null ? {} : {'X-SC-Catch-Log-Next-Cursor': next}})});
const nativeCreate = document.createElement;
async function close() { await $('.home-port-close')?.fire('click'); }
async function setup({log = async () => response({entries: []}), trips = async () => response({trips: []}), lang = 'en', broken = ''} = {}) {
  await close(); requests = []; blobs = []; clicks = []; revoked = []; anchors = []; exporting = false; logRead = log; tripRead = trips; construction = broken;
  globalThis.Blob = class extends originals.Blob { constructor(parts, options) { if (construction === 'blob') throw Error('synthetic blob failure'); super(parts, options); blobs.push(this); } };
  URL.createObjectURL = () => { if (construction === 'url') throw Error('synthetic URL failure'); return 'blob:synthetic-csv'; };
  URL.revokeObjectURL = url => revoked.push(url);
  document.createElement = tag => {
    if (tag === 'a' && construction === 'anchor') throw Error('synthetic anchor failure');
    const el = nativeCreate(tag);
    if (tag === 'a') { anchors.push(el); el.click = () => { if (construction === 'click') throw Error('synthetic click failure'); clicks.push({name: el.download, href: el.href}); }; }
    return el;
  };
  globalThis.fetch = async (url, options) => {
    requests.push({url, method: options.method, body: options.body});
    if (url.startsWith('/api/catch-log')) return exporting ? logRead(url, options) : response({entries: [row('visible')]}, 'true', 'display-only-cursor');
    if (url === '/api/trips') return exporting ? tripRead() : response({trips: []});
    const data = {'/api/session': {signedIn: true, signIn: '/#account', user: {}}, '/api/auth/passkeys': {passkeys: []}, '/api/spots': {spots: []}, '/api/auth/sessions': {sessions: []}};
    assert.ok(Object.hasOwn(data, url), 'only existing account GETs'); return response(data[url]);
  };
  await openAccount({lang, strings: Object.fromEntries(Object.entries(catalog).map(([id, v]) => [id, v[lang]]))}); await tick(); await tick();
}
async function download() { exporting = true; await $('#log-download-csv').fire('click'); }
async function cleaned() { await new Promise(resolve => setTimeout(resolve, 10)); assert.ok(anchors.every(a => !a.isConnected)); }
function nothing(key = 'incomplete', lang = 'en') {
  assert.equal(blobs.length, 0, 'no partial Blob'); assert.equal(clicks.length, 0, 'no partial download');
  assert.equal($('#log-csv-status').textContent, catalog['account.log.csv.' + key][lang]); assert.equal($('#log-download-csv').disabled, false);
}
test.after(async () => { await cleaned(); await close(); Object.assign(globalThis, originals); URL.createObjectURL = originalCreate; URL.revokeObjectURL = originalRevoke; hooks.deregister(); });
test('real_handler_is_deliberate_and_single_flight', async () => {
  const wait = deferred(); let reads = 0;
  await setup({trips: () => wait.promise, log: async url => {
    reads++; assert.equal(url, reads === 1 ? '/api/catch-log' : '/api/catch-log?cursor=opaque%20%2B%2F%3F%3D');
    return reads === 1 ? response({entries: [row('a')]}, 'true', 'opaque +/?=') : response({entries: [row('b')]});
  }});
  assert.equal(requests.filter(r => r.url.startsWith('/api/catch-log')).length, 1, 'open reads displayed page only');
  assert.equal($('#log-download-csv').getAttribute('type'), 'button'); assert.ok($('#log-csv-limit').textContent.includes('2,000'));
  exporting = true; const pending = $('#log-download-csv').fire('click'); await tick();
  assert.equal($('#log-download-csv').disabled, true); await $('#log-download-csv').fire('click');
  assert.equal(requests.filter(r => r.url === '/api/trips').length, 2, 'one fresh trip read for the single attempt');
  assert.equal(reads, 0, 'awaits trips'); assert.equal($('#log-save').disabled, false, 'Save remains independent');
  wait.resolve(response({trips: []})); await pending;
  assert.equal(reads, 2); assert.equal(blobs.length, 1); assert.equal(parse(await blobs[0].text()).length, 3);
  assert.equal(blobs[0].type, 'text/csv;charset=utf-8'); assert.equal(clicks[0].name, 'SkipperCast-catch-log.csv');
  assert.ok(requests.every(r => r.method === 'GET' && r.body === undefined)); assert.equal($('#log-download-csv').disabled, false);
  assert.equal($('#log-csv-status').textContent, catalog['account.log.csv.done'].en);
  await cleaned(); same(revoked, ['blob:synthetic-csv']);
});
test('empty_log_downloads_header', async () => {
  await setup(); await download(); same(await blobs[0].text(), header, 'header only'); assert.equal(clicks.length, 1); await cleaned();
});
test('failed_page_and_trip_metadata_have_no_partial_file', async () => {
  for (const failed of [() => response({}, 'false', null, 401), () => response({}, 'false', null, 503),
    () => { throw Error('fetch failed'); }, () => { throw new DOMException('expired', 'TimeoutError'); },
    () => ({ok: true, json: async () => { throw Error('not JSON'); }, headers: new Headers()}),
    () => response({entries: {}}), () => response({entries: []}, null), () => response({entries: []}, 'false', 'stray'),
    () => response({entries: []}, 'true'), () => response({entries: [row('bad', {note: {}})]})]) {
    for (const later of [false, true]) {
      let reads = 0; await setup({log: () => ++reads === 1 && later ? response({entries: [row('first')]}, 'true', 'next') : failed()});
      await download(); nothing(); assert.equal(reads, later ? 2 : 1);
    }
  }
  for (const data of [{}, {trips: {}}, {trips: [null]}, {trips: [{}]}, {trips: [{id: 'trip', date: '2026-02-30'}]},
    {trips: [{id: 'trip', date: '=bad'}]}, {trips: [{id: 'trip'}, {id: 'trip'}]}]) {
    await setup({trips: async () => response(data), log: async () => response({entries: [row('a', {trip_id: 'trip'})]})}); await download(); nothing('tripsFailed');
  }
  for (const failed of [() => response({}, 'false', null, 503), () => { throw Error('trip fetch failed'); },
    () => ({ok: true, json: async () => { throw Error('not JSON'); }})]) {
    await setup({trips: failed}); await download(); nothing('tripsFailed');
  }
});
test('cap_cycle_and_malformed_duplicate_create_no_file', async () => {
  for (const mode of ['cap', 'cycle', 'duplicate']) {
    let reads = 0; await setup({log: async () => { reads++; return mode === 'duplicate'
      ? response({entries: [row('a'), row('a', {count: '2'})]})
      : response({entries: [row(String(reads))]}, 'true', mode === 'cycle' ? 'same' : 'c' + reads); }});
    await download(); nothing(); assert.equal(reads, mode === 'cap' ? 10 : mode === 'cycle' ? 2 : 1);
  }
  let reads = 0; await setup({log: async () => ++reads === 10 ? response({entries: []}) : response({entries: []}, 'true', 'c' + reads)});
  await download(); assert.equal(reads, 10); assert.equal(clicks.length, 1); await cleaned();
});
test('closing_discards_late_export', async () => {
  for (const phase of ['trips', 'page']) {
    const wait = deferred(); let oldReads = 0;
    await setup({trips: phase === 'trips' ? () => wait.promise : undefined, log: async () => { oldReads++; return wait.promise; }});
    exporting = true; const pending = $('#log-download-csv').fire('click'); await tick(); const oldStatus = $('#log-csv-status');
    await close(); await setup();
    wait.resolve(phase === 'trips' ? response({trips: []}) : response({entries: [row('a')]}, 'true', 'next'));
    await pending; assert.equal(blobs.length, 0); assert.equal(clicks.length, 0); assert.equal(oldReads, phase === 'page' ? 1 : 0);
    assert.equal($('#log-csv-status').textContent, ''); assert.equal(oldStatus.textContent, catalog['account.log.csv.loading'].en);
    await download(); assert.equal(clicks.length, 1); await cleaned();
  }
});
test('construction_failures_clean_and_allow_retry', async () => {
  for (const broken of ['blob', 'url', 'anchor', 'click']) {
    await setup({broken}); await download(); assert.equal(clicks.length, 0); assert.equal($('#log-download-csv').disabled, false);
    assert.equal($('#log-csv-status').textContent, catalog['account.log.csv.incomplete'].en); await cleaned();
    assert.equal(revoked.length, ['anchor', 'click'].includes(broken) ? 1 : 0);
    construction = ''; await download(); assert.equal(clicks.length, 1); await cleaned();
  }
});
test('csv_ui_en_es_format_stable', async () => {
  const bytes = [];
  for (const lang of ['en', 'es']) {
    await setup({lang, log: async () => response({entries: [row('a', {note: '=formula'})]})});
    for (const suffix of ['download', 'loading', 'limit', 'incomplete', 'tripsFailed', 'done']) assert.ok(catalog['account.log.csv.' + suffix][lang]);
    assert.equal($('#log-download-csv').textContent, catalog['account.log.csv.download'][lang]);
    assert.equal($('#log-csv-limit').textContent, catalog['account.log.csv.limit'][lang]);
    assert.equal($('#log-csv-status').getAttribute('role'), 'status');
    for (const id of ['log-species-suggestions', 'log-use-position', 'log-spot', 'log-trip']) assert.ok($('#' + id));
    await download(); bytes.push(await blobs[0].text()); assert.equal($('#log-csv-status').textContent, catalog['account.log.csv.done'][lang]); await cleaned();
    await setup({lang, log: async () => response({}, 'false', null, 401)}); await download(); nothing('incomplete', lang);
  }
  same(bytes[0], bytes[1], 'locale-independent wire schema');
});
