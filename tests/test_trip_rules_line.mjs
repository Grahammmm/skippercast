// SC2037-15: mount the actual sheet with a synthetic signed-in API and rule registry.
import assert from 'node:assert/strict';
import util from 'node:util';
import {readFile, mkdtemp, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {setImmediate} from 'node:timers/promises';
import {pathToFileURL} from 'node:url';
import test, {after} from 'node:test';
import {build} from 'esbuild';
import {rendererPlugins} from './helpers/esbuild-url.mjs';

const fixture = JSON.parse(await readFile(new URL('./fixtures/regulations/fe61-v1.json', import.meta.url)));
const region = {...fixture.region, species: ['reef', 'salmon']};
const NOW = Date.parse('2026-10-12T18:00:00Z'), HOUR = 3600000;
const COPY = 'regions/morro-bay/regulations-startup.json';
const DAILY = '/api/daily?region=morro-bay&part=regulations';
const NOTICE = 'Rules could not be loaded. Check the official rules before each trip.';
const CHECK = /Check the official rules before this trip/;
const LEGAL = 'Not legal advice; check the official page.';
const trip = (id, date, targets, extra) => ({id, date, targets, region: region.id, point: region.forecast_points[0].id,
  species: 'lingcod', start_hour: 7, end_hour: 13, wind_limit: 15, gust_limit: 20, sea_limit: 4, enabled: 1, ...extra});
function registry(age = 0, status = 'reviewed') {
  const d = structuredClone(fixture.regulations);
  d.reviewed_at = new Date(NOW - 72 * HOUR).toISOString();
  d.rules_review_status = status;
  for (const [id, s] of Object.entries(d.sources)) {
    s.approved_content_sha256 = 'a'.repeat(64);
    d.checks[id] = {url: s.url, normalization: s.normalization, status: 'unchanged', source_status: 'ok',
      content_sha256: s.approved_content_sha256, data_retrieved_at: new Date(NOW - age * HOUR).toISOString()};
  }
  for (const id of ['lingcod', 'rockfish', 'salmon']) d.species[id].windows = [{start: '2026-10-10', end: '2026-10-13'}];
  return d;
}

const dir = await mkdtemp(join(tmpdir(), 'trip-rules-')), out = join(dir, 'sheet.mjs');
after(() => rm(dir, {recursive: true, force: true}));
await build({stdin: {resolveDir: new URL('..', import.meta.url).pathname, loader: 'ts', contents: `
  export {TripAlerts} from './web/app/TripAlerts.tsx';
  export {regsData, resetRegs} from './web/regs.ts';
  export {render, h} from 'preact'; export {act} from 'preact/test-utils';`},
  bundle: true, format: 'esm', platform: 'node', outfile: out, jsx: 'automatic', jsxImportSource: 'preact', plugins: rendererPlugins});
const {TripAlerts, render, h, act, regsData, resetRegs} = await import(pathToFileURL(out).href);

// Small DOM for Preact mounting (including effects and link attributes), as in test_regs_retry.mjs.
class Node {
  constructor(type, name, data = '') { Object.assign(this, {nodeType: type, localName: name, data, childNodes: [], parentNode: null, style: {}, attrs: {}}); }
  get firstChild() { return this.childNodes[0] ?? null; }
  get nextSibling() { return this.parentNode?.childNodes[this.parentNode.childNodes.indexOf(this) + 1] ?? null; }
  get textContent() { return this.nodeType === 3 ? this.data : this.childNodes.map(c => c.textContent).join(''); }
  remove() { this.parentNode?.removeChild(this); }
  removeChild(c) { this.childNodes.splice(this.childNodes.indexOf(c), 1); c.parentNode = null; return c; }
  insertBefore(c, ref) { c.remove(); const i = ref ? this.childNodes.indexOf(ref) : -1; this.childNodes.splice(i < 0 ? this.childNodes.length : i, 0, c); c.parentNode = this; return c; }
  appendChild(c) { return this.insertBefore(c, null); }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  removeAttribute(k) { delete this.attrs[k]; }
  addEventListener(type, fn) { (this.listeners ??= {})[type] = fn; } removeEventListener() {}
}
const all = (node, pred) => [...(pred(node) ? [node] : []), ...node.childNodes.flatMap(c => all(c, pred))];
const rows = root => all(root, n => n.localName === 'p' && n.attrs['data-status']);
const matches = (root, copy) => root.textContent.split(copy).length - 1;
async function until(ready) {
  for (let i = 0; i < 30 && !ready(); i++) await act(() => setImmediate());
  assert.ok(ready(), 'sheet reached expected state');
}
async function sheet(t, trips, copy) {
  t.mock.timers.enable({apis: ['Date'], now: NOW});
  regsData.value = null; resetRegs();
  const root = new Node(1, 'div'), urls = [], posts = [], answer = {post: () => Response.json({ok: true})};
  const original = globalThis.document;
  globalThis.document = {createElement: n => new Node(1, n), createElementNS: (_, n) => new Node(1, n), createTextNode: s => new Node(3, '#text', s)};
  t.after(async () => { await act(() => render(null, root)); if (original) globalThis.document = original; else delete globalThis.document; });
  t.mock.method(globalThis, 'fetch', async (url, init) => {
    urls.push(url);
    switch (url) {
      case '/api/session': return Response.json({signedIn: true});
      case 'regions/morro-bay/region.json': return Response.json(region);
      case '/api/trips':
        if (init?.method === 'POST') { posts.push(JSON.parse(init.body)); return answer.post(); }
        return Response.json({trips, events: []});
      case '/api/comfort': return Response.json({feedback: []});
      case COPY: return copy;
      default: return new Response(null, {status: 404});
    }
  });
  const draw = target => act(() => render(h(TripAlerts, {regionId: region.id, target}), root));
  await draw(null);
  return {root, urls, draw, posts, answer};
}

test('three upcoming trips share one registry read, and each date drives its own season reading', async t => {
  const {root, urls, draw} = await sheet(t, [trip('reef', '2026-10-13', ['reef', 'lingcod']),
    trip('closed', '2026-10-14'), trip('unknown', '2026-10-15', ['no-profile']), trip('past', '2026-10-11')], Response.json(registry()));
  await until(() => rows(root).length === 4);
  const [lingcod, rockfish, closed, unknown] = rows(root);
  assert.match(lingcod.textContent, /Lingcod · Open .*Verified Oct 12.*Checked today/);
  assert.match(rockfish.textContent, /Rockfish \/ rock cod · Open /);
  const links = all(lingcod, n => n.localName === 'a');
  assert.equal(links.length, 1);
  assert.equal(links[0].attrs.href, fixture.regulations.sources['rules-central'].url);
  assert.match(closed.textContent, /Lingcod · Closed Closed on Wed 14 Oct/);
  assert.doesNotMatch(closed.textContent, /\bOpen\b/);
  assert.match(unknown.textContent, CHECK);
  assert.equal(unknown.attrs['data-status'], 'unknown');
  assert.equal(matches(root, LEGAL), 1);
  assert.equal(rows(all(root, n => n.localName === 'article')[0]).length, 0, 'past trip stays unchanged');
  await draw('reef');
  assert.equal(urls.filter(url => url === COPY).length, 1);
  assert.equal(urls.filter(url => url === DAILY).length, 1);
});

for (const [name, age, status, other] of [['Stale', 50], ['Overdue', 30], ['Unreviewed', 0, 'draft'], ['Another region’s', 0, 'reviewed', 'different']]) {
  test(`${name} rules never label a trip open`, async t => {
    const {root} = await sheet(t, [trip('a', '2026-10-13', ['lingcod'], other ? {region: other} : {})], Response.json(registry(age, status)));
    await until(() => rows(root).length === 1);
    const [reading] = rows(root);
    assert.match(reading.textContent, CHECK);
    assert.equal(reading.attrs['data-status'], 'unknown');
    assert.doesNotMatch(reading.textContent, /· Open\b|Verified/);
    assert.equal(all(reading, n => n.localName === 'a').length, 1);
  });
}

test('pending rules are quiet; a failed load says so once for the sheet, not per trip', async t => {
  const pending = Promise.withResolvers();
  const {root, urls, draw} = await sheet(t, [trip('a', '2026-10-13', ['reef']), trip('b', '2026-10-14')], pending.promise);
  await until(() => urls.includes(COPY));
  assert.match(root.textContent, /Add to calendar/);
  assert.equal(matches(root, NOTICE), 0);
  assert.equal(rows(root).length, 0);
  pending.resolve(new Response(null, {status: 503}));
  await until(() => matches(root, NOTICE) > 0);
  assert.equal(matches(root, NOTICE), 1);
  assert.ok(root.textContent.indexOf(NOTICE) < root.textContent.indexOf('Add to calendar'));
  assert.equal(rows(root).length, 0);
  await draw('salmon');
  assert.equal(urls.filter(url => url === COPY).length, 1, 'a failed read is not retried on sheet rerender');
});

// SCB2222-12 (form-input-labels-and-autofill R4). Contract: while the From/Until order problem is the current status, both hour inputs
// carry aria-invalid and aria-describedby pointing at the one rendered message; any bug that leaves the hours unmarked, marks them for
// another problem or a request failure, or leaves the marks after a correction, fails here.
const WINDOW = 'The window must end after it starts.';
const DATE_PROBLEM = 'Choose a date from today to seven days ahead.';
const named = (root, name) => {
  const n = all(root, c => c.attrs.name === name)[0];
  assert.ok(n, `control ${name} is rendered`);
  if (!('value' in n)) {
    const first = () => n.localName === 'select' ? (all(n, o => o.localName === 'option')[0]?.attrs.value ?? '') : (n.attrs.defaultValue ?? '');
    let value = first();
    Object.defineProperties(n, {
      name: {value: name},
      value: {get: () => value, set: v => { value = String(v); }},
      validity: {get: () => { const v = Number(value); return {valid: value !== '' && (n.attrs.type !== 'number' || (v >= Number(n.attrs.min) && v <= Number(n.attrs.max) && Number.isInteger(v / Number(n.attrs.step ?? 1))))}; }},
    });
  }
  return n;
};
async function form(t, root) {
  const f = all(root, n => n.attrs.id === 'save-alert')[0];
  assert.ok(f, 'the signed-in form is rendered');
  f.elements = {namedItem: name => named(f, name)};
  const Real = globalThis.FormData;
  globalThis.FormData = class { constructor(source) { this.source = source; } get(name) { return named(this.source, name).value; } };
  t.after(() => { globalThis.FormData = Real; });
  const fire = (type, target) => act(() => f.listeners[type].call(f, {type, target, currentTarget: f, preventDefault() {}}));
  return {
    submit: () => fire('submit', f),
    edit: (name, value) => { const c = named(f, name); c.value = value; return fire('input', c); },
    hours: () => ['start_hour', 'end_hour'].map(name => named(f, name)),
    status: () => all(root, n => n.attrs.id === 'alert-status')[0],
  };
}
const marked = c => ({invalid: c.attrs['aria-invalid'], described: c.attrs['aria-describedby']});
function assertHoursMarked(ui) {
  const status = ui.status();
  assert.equal(status.textContent, WINDOW, 'the existing message, once, in the general status');
  for (const c of ui.hours()) {
    assert.equal(c.attrs['aria-invalid'], 'true', `${c.attrs.name} is invalid`);
    assert.equal(all(status.parentNode.parentNode, n => n.attrs.id === c.attrs['aria-describedby'])[0], status, `${c.attrs.name} is described by the actual message`);
  }
}
function assertHoursClear(ui) {
  for (const c of ui.hours()) assert.ok(util.isDeepStrictEqual(marked(c), {invalid: undefined, described: undefined}), `${c.attrs.name} has neither attribute`);
}

for (const [label, first, last] of [['equal', '9', '9'], ['reversed', '9', '5']]) {
  test(`trip_window_order_status_describes_both_hours: ${label} hours mark both inputs and send nothing`, async t => {
    const {root, posts} = await sheet(t, [], Response.json(registry()));
    await until(() => all(root, n => n.attrs.id === 'save-alert').length === 1);
    const ui = await form(t, root);
    assertHoursClear(ui);
    await ui.edit('start_hour', first); await ui.edit('end_hour', last);
    await ui.submit();
    assertHoursMarked(ui);
    assert.equal(posts.length, 0);
    for (const name of ['date', 'point', 'wind_limit', 'gust_limit', 'sea_limit']) assert.ok(!('aria-invalid' in named(root, name).attrs), `${name} is not marked`);
  });
}

test('trip_window_correction_and_request_failure_are_distinct: only a corrected, ordered, valid window clears the marks', async t => {
  const {root, posts, answer} = await sheet(t, [], Response.json(registry()));
  await until(() => all(root, n => n.attrs.id === 'save-alert').length === 1);
  const ui = await form(t, root);
  const wrong = async () => { await ui.edit('start_hour', '9'); await ui.edit('end_hour', '9'); await ui.submit(); assertHoursMarked(ui); };
  await wrong();
  // Not a correction: another field, a tie, a blank and an out-of-bounds hour all leave the error current.
  await ui.edit('wind_limit', '1');
  await ui.edit('end_hour', '9');
  await ui.edit('end_hour', '');
  await ui.edit('end_hour', '24');
  assertHoursMarked(ui);
  // Correction through Until, then through From; nothing is sent.
  await ui.edit('end_hour', '10');
  assert.equal(ui.status().textContent, ''); assertHoursClear(ui);
  await wrong();
  await ui.edit('start_hour', '8');
  assert.equal(ui.status().textContent, ''); assertHoursClear(ui);
  assert.equal(posts.length, 0);
  // A request failure is a general status only; the hours stay unmarked.
  await wrong();
  await ui.edit('end_hour', '10');
  answer.post = () => Response.json({error: 'The server refused this alert.'}, {status: 500});
  await ui.submit();
  await until(() => ui.status().textContent === 'The server refused this alert.');
  assert.equal(posts.length, 1);
  assertHoursClear(ui);
  // The window is wrong again, and a valid submit clears the stale message before it is sent.
  await wrong();
  await ui.edit('end_hour', '10'); await ui.edit('start_hour', '9');
  await ui.submit();
  await until(() => posts.length === 2);
  assert.equal(posts[1].start_hour, 9); assert.equal(posts[1].end_hour, 10);
  assert.doesNotMatch(ui.status().textContent, /window/); assertHoursClear(ui);
});

test('trip_window_order_never_marks_hours_for_the_date_problem: the date is refused first, in the general status', async t => {
  const {root, posts} = await sheet(t, [], Response.json(registry()));
  await until(() => all(root, n => n.attrs.id === 'save-alert').length === 1);
  const ui = await form(t, root);
  await ui.edit('start_hour', '9'); await ui.edit('end_hour', '9'); await ui.edit('date', '2026-01-01');
  await ui.submit();
  assert.equal(ui.status().textContent, DATE_PROBLEM);
  assertHoursClear(ui);
  assert.equal(posts.length, 0);
});
