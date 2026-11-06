// SC1137-09: editing a saved spot's name and private note from the account panel. The helpers behind the Edit form, the real
// PATCH route's refusals as the panel receives them, and the GPX still carrying the new name and never the note.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {DatabaseSync} from 'node:sqlite';
import {withSessions} from './fixtures/test-sessions.mjs';
import {accountOptions} from '../web/account-copy.ts';

const read = p => JSON.parse(readFileSync(new URL(p, import.meta.url)));
globalThis.REGIONS = {'morro-bay': read('../regions/morro-bay/region.json')};
globalThis.DEPLOYMENT = read('../deployments/production.json');
globalThis.BUILD_ID = 'build-test';
globalThis.SHELLS = {'/': '/index.0123456789.html', '/index.html': '/index.0123456789.html', '/landing.html': '/landing.0123456789.html', '/app.html': '/app.0123456789.html'};
const {default: deployed} = await import('../server/index.ts');
const {spotItemHTML, spotEditHTML, spotEditBody, fillSpotEdit, exportSpots, createCopy} = await import('../dist/account.js');
const {initProtectedAreas} = await import('../dist/protected-areas.js');
const {getRegion} = await import('../dist/region.js');
const worker = withSessions(deployed), ORIGIN = 'https://skippercast.com';

function database() {
  const sql = new DatabaseSync(':memory:');
  for (const {tag} of [...read('../drizzle/meta/_journal.json').entries].sort((a, b) => a.idx - b.idx)) sql.exec(readFileSync(new URL(`../drizzle/${tag}.sql`, import.meta.url), 'utf8'));
  const adapter = {prepare(query) { let args = []; const statement = sql.prepare(query); return {bind(...a) { args = a; return this; }, async first() { return statement.get(...args) || null; }, async all() { return {results: statement.all(...args)}; }, async run() { const info = statement.run(...args); return {meta: {changes: Number(info.changes)}}; }}; },
    async batch(queries) { const out = []; for (const q of queries) out.push(await q.run()); return out; }};
  return {sql, adapter};
}
const call = (env, path, {owner = 'alice', method = 'GET', body} = {}) => {
  const headers = {'Content-Type': 'application/json', 'CF-Connecting-IP': '203.0.113.9', 'x-test-owner': owner};
  if (method !== 'GET') headers.Origin = ORIGIN;
  return worker.fetch(new Request(ORIGIN + path, {method, headers, body: body === undefined ? undefined : JSON.stringify(body)}), env);
};
const MPAS = read('../dist/data/protected-areas.geojson');
async function screen() {
  const saved = {fetch: globalThis.fetch, document: globalThis.document};
  globalThis.fetch = async () => ({ok: true, json: async () => ({...MPAS, checked_at: new Date().toISOString()})});
  globalThis.document = {getElementById: () => ({classList: {toggle() {}}, textContent: ''}), dispatchEvent() {}};
  try { return await initProtectedAreas(null, () => {}); } finally { Object.assign(globalThis, saved); }
}

const NOTE = 'EDITNOTE-private <b>x</b> 🐟 & "q"';
const SPOT = {id: 'sp-1', name: 'Old <i>name</i>', lat: 35.0, lon: -121.6, note: NOTE};
const fakeForm = () => { const els = {name: {value: ''}, note: {value: ''}}; return {elements: els}; };

test('spot_edit_form_shows_position_as_text_helper_line_and_no_position_input', () => {
  const html = spotEditHTML(SPOT, {text: 'READING-kept'}, 'dd');
  assert.ok(html.includes('A different position needs a new spot.'), 'one line about a different position');
  assert.ok(html.includes('READING-kept'), 'the protected-area reading stays visible');
  assert.ok(html.includes('maxlength="80"') && !/<textarea[^>]*maxlength/.test(html), 'name capped at 80, note textarea uncapped');
  assert.ok(!/name="(lat|lon)"/.test(html) && !/id="spot-(lat|lon)/.test(html), 'no position control');
  assert.ok(!html.includes('EDITNOTE') && !html.includes('Old '), 'stored values go in through .value, not markup');
  const form = fakeForm(); fillSpotEdit(form, {...SPOT, note: '  \n keep  '});
  assert.equal(form.elements.name.value, SPOT.name); assert.equal(form.elements.note.value, '  \n keep  ');
  assert.ok(spotItemHTML(SPOT, null, 'dd').includes('data-edit-spot="sp-1"'), 'each row offers Edit');
});

test('spot_edit_body_is_only_name_and_note_untouched', () => {
  const body = spotEditBody({name: '  Reef  ', note: '', lat: 1, lon: 2, id: 'x'});
  assert.ok(Object.keys(body).sort().join() === 'name,note', 'no position, id or owner');
  assert.equal(body.name, '  Reef  '); assert.equal(body.note, '');
  assert.ok(spotEditBody({}).name === '' && spotEditBody({}).note === null);
});

test('spot_edit_copy_en_and_es', () => {
  const es = createCopy(accountOptions('es')), en = createCopy(accountOptions('en'));
  assert.equal(en('account.spotEdit.positionHelp'), 'A different position needs a new spot.');
  assert.equal(es('account.spotEdit.positionHelp'), 'Para cambiar la posición, guarda un sitio nuevo.');
  assert.equal(es('account.spotEdit.edit'), 'Editar'); assert.equal(es('account.spotEdit.saved'), 'Cambios guardados.');
  assert.match(es('account.spotEdit.failed'), /^No se pudieron confirmar/);
  assert.match(spotEditHTML(SPOT, null, 'dd', accountOptions('es')), /Guardar cambios/);
});

test('spot_edit_refusals_arrive_as_the_servers_own_words_and_change_nothing', async () => {
  const {sql, adapter} = database(), env = {DB: adapter};
  const made = await (await call(env, '/api/spots', {method: 'POST', body: {name: 'Keep', lat: 35.0, lon: -121.6, note: 'n'}})).json();
  const patch = (owner, id, body) => call(env, '/api/spots/' + encodeURIComponent(id), {owner, method: 'PATCH', body});
  const withPosition = await patch('alice', made.id, {name: 'X', lat: 36});
  assert.equal(withPosition.status, 400);
  assert.match((await withPosition.json()).error, /lat cannot be changed/);
  assert.equal((await patch('bob', made.id, {name: 'X'})).status, 404, 'not the owner');
  assert.equal((await patch('alice', 'no-such', {name: 'X'})).status, 404);
  assert.equal((await patch('alice', made.id, {})).status, 400);
  assert.deepEqual(sql.prepare('SELECT name,note,lat,lon FROM saved_spots').all().map(r => ({...r})), [{name: 'Keep', note: 'n', lat: 35, lon: -121.6}], 'refusals changed nothing');
  sql.close();
});

test('spot_edit_gpx_has_the_new_name_and_never_the_note', async () => {
  const {sql, adapter} = database(), env = {DB: adapter};
  const made = await (await call(env, '/api/spots', {method: 'POST', body: {name: 'Before', lat: 35.0, lon: -121.6, note: NOTE}})).json();
  const res = await call(env, '/api/spots/' + made.id, {method: 'PATCH', body: spotEditBody({name: 'AFTERNAME', note: 'SECOND-NOTE-private'})});
  assert.equal(res.status, 200);
  const saved = await res.json();
  assert.ok(saved.id === made.id && saved.lat === 35 && saved.lon === -121.6, 'position and id stand');
  const {spots} = await (await call(env, '/api/spots')).json();
  const out = await exportSpots(spots, await screen(), getRegion());
  assert.equal(out.exported, 1);
  assert.ok(out.gpx.includes('AFTERNAME') && !out.gpx.includes('Before'), 'the new name is exported');
  assert.ok(!out.gpx.includes('SECOND-NOTE') && !out.gpx.includes('EDITNOTE'), 'no note, old or new, in the GPX');
  sql.close();
});
