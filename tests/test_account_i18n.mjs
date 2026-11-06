// SC0922-14: the account panel (dist/account.js, imported on demand) takes its language and words from openAccount({lang, strings}).
// Synthetic rows and a fixed clock; no network. The real dialog runs in e2e/v2-account-i18n.spec.ts.
import test from 'node:test';
import assert from 'node:assert/strict';
import {isDeepStrictEqual} from 'node:util';
import {mkdirSync, mkdtempSync, readFileSync, writeFileSync} from 'node:fs';
import {join} from 'node:path';
import {tmpdir} from 'node:os';
import {accountOptions} from '../web/account-copy.ts';
import {catalogueProblems} from '../scripts/check_copy.mjs';

const account = await import('../dist/account.js');
const {createCopy, passkeyMessage, logItemHTML, logCountsText, spotItemHTML, spotVerdicts, exportSpots, positionFieldHTML, logBody, drawLogView} = account;
const {initProtectedAreas} = await import('../dist/protected-areas.js');
const {getRegion} = await import('../dist/region.js');
const read = p => JSON.parse(readFileSync(new URL(p, import.meta.url)));
const STRINGS = read('../catalog/app/strings.json').strings;
const IDS = Object.keys(STRINGS).filter(id => id.startsWith('account.'));
const SOURCE = readFileSync(new URL('../dist/account.js', import.meta.url), 'utf8');
const ES = accountOptions('es'), EN = accountOptions('en');

test('account_options_cover_every_account_id_with_es_values', () => {
  assert.ok(IDS.length > 100);
  assert.ok(isDeepStrictEqual(Object.keys(ES.strings).sort(), IDS.slice().sort()), 'the bridge sends exactly the account.* ids');
  assert.equal(ES.lang, 'es'); assert.equal(EN.lang, 'en');
  for (const id of IDS) {
    assert.equal(ES.strings[id], STRINGS[id].es, id); assert.equal(EN.strings[id], STRINGS[id].en, id);
    assert.ok(STRINGS[id].es?.trim(), `${id} has an es value`);
    assert.ok(SOURCE.includes(`'${id}'`), `${id} is used by dist/account.js`);   // no unused id and no id the panel cannot find
  }
  for (const m of SOURCE.matchAll(/\bt\(\s*'(account\.[\w.]+)'/g)) assert.ok(IDS.includes(m[1]), `${m[1]} is in the catalogue`);
  assert.equal(accountOptions('fr').lang, 'en'); assert.equal(accountOptions(null).lang, 'en');
});

test('account_english_defaults_without_options_equal_english_options', async () => {
  const t0 = createCopy(), t1 = createCopy(EN), t2 = createCopy({lang: 'xx', strings: {}});
  for (const id of IDS) { assert.equal(t0(id, {n: 2}), STRINGS[id].en.replace(/\{n\}/g, '2')); assert.equal(t1(id), t0(id)); assert.equal(t2(id), t0(id)); }
  const rows = [{id: 'a', started_at: '2026-03-04T12:00:00Z', outcome: 'fish', count: 3, species: 'Lingcod', method: 'jig', lat: 35.5, lon: -120.9, note: '<b>x</b>', trip_id: 't1'},
    {id: 'b', started_at: '2026-03-05T12:00:00Z', outcome: 'blank'}, {id: 'c', started_at: null, outcome: 'weird'}];
  const trips = [{id: 't1', date: '2026-03-04'}];
  for (const row of rows) assert.equal(logItemHTML(row, trips, 'dd'), logItemHTML(row, trips, 'dd', EN));
  const html = logItemHTML(rows[0], trips, 'dd');
  assert.match(html, /3 fish · Lingcod · jig · .* · Trip: 2026-03-04<\/span><p class="account-hint">&lt;b&gt;x&lt;\/b&gt;<\/p>/);
  assert.match(html, />Remove<\/button>/);
  assert.match(logItemHTML(rows[1], trips, 'dd'), /Blank: no fish/);
  assert.match(logItemHTML(rows[2], trips, 'dd'), /weird/);
  const counts = {entries: 2, fish: 1, fishTotal: 3, blank: 1, unknown: 0, species: [{name: 'Lingcod', count: 1}]};
  assert.equal(logCountsText(counts), 'In the 2 entries: 1 fish trips (3 fish), 1 blanks, 0 not sure. Most logged: Lingcod 1.');
  assert.equal(logCountsText({...counts, entries: 1, species: []}, {filtered: true, more: true}), 'In the 1 loaded entry that match: 1 fish trips (3 fish), 1 blanks, 0 not sure. Older entries are not loaded yet.');
  assert.equal(logCountsText(counts, {more: true}), logCountsText(counts, {more: true}, EN));
  assert.equal(spotItemHTML({id: 's', name: '  ', lat: 35, lon: -120, note: 'n'}, null, 'dd'), spotItemHTML({id: 's', name: '  ', lat: 35, lon: -120, note: 'n'}, null, 'dd', EN));
  assert.match(spotItemHTML({id: 's', name: '', lat: 35, lon: -120}, null, 'dd'), /Unnamed spot/);
  assert.match(positionFieldHTML('log', 'lat', 'Latitude', '', 'dd'), /For example 35\.3576/);
  assert.throws(() => logBody({lat: '35', lon: ''}), /Enter both latitude and longitude, or neither\./);
  assert.throws(() => createCopy()('account.nope'), /unknown account string/);
});

test('account_injected_strings_fall_back_to_english', () => {
  const bad = createCopy({lang: 'es', strings: {'account.create': '', 'account.signin': 42, 'account.in.titleNamed': 'Hola', 'account.signout': 'Salir', 'account.nope': 'x', 'toString': 'y'}});
  assert.equal(bad('account.create'), 'Create account');                       // empty
  assert.equal(bad('account.signin'), 'Sign in with a passkey');               // not a string
  assert.equal(bad('account.in.titleNamed', {name: 'Q'}), 'Signed in as Q');    // placeholder {name} missing
  assert.equal(bad('account.signout'), 'Salir');                               // valid
  assert.throws(() => bad('account.nope'), /unknown/);
  assert.equal(bad('account.err.detail', {detail: '$&{x}'}), '$&{x}');          // values are inserted as plain text
  const one = createCopy(ES), two = createCopy(EN);
  assert.equal(one('account.create'), 'Crear cuenta'); assert.equal(two('account.create'), 'Create account');   // no shared language
});

test('account_passkey_errors_are_spanish_by_class_and_detail_stays_verbatim', () => {
  const es = e => passkeyMessage(e, ES);
  assert.equal(es({name: 'InvalidStateError'}), 'Este dispositivo ya tiene una clave de acceso para esta cuenta.');
  assert.equal(es({code: 'ERROR_AUTHENTICATOR_PREVIOUSLY_REGISTERED'}), 'Este dispositivo ya tiene una clave de acceso para esta cuenta.');
  assert.equal(es({name: 'NotAllowedError'}), 'La solicitud de clave de acceso se canceló o agotó su tiempo. Inténtalo de nuevo cuando estés listo.');
  assert.equal(es({name: 'AbortError'}), es({name: 'NotAllowedError'}));
  assert.equal(es({name: 'SecurityError'}), 'Las claves de acceso no están disponibles en esta dirección.');
  assert.equal(es({status: 429, message: 'slow down'}), 'Demasiados intentos. Espera un minuto e inténtalo de nuevo.');
  assert.equal(es({}), 'Algo salió mal. Inténtalo de nuevo.');
  assert.equal(es({code: 'PASSKEY_LIBRARY_UNAVAILABLE'}), STRINGS['account.err.library'].es);
  assert.equal(es({message: 'database is on fire', status: 500}), 'No se pudo completar la solicitud. Detalles del servidor (en inglés): database is on fire');
  assert.equal(es({message: 'Could not complete this request.', apiFallback: true}), 'No se pudo completar esta solicitud.');
  // English keeps its capitalisation and added period, whatever the options say.
  assert.equal(passkeyMessage({message: 'database is on fire'}), 'Database is on fire.');
  assert.equal(passkeyMessage({message: 'database is on fire'}, EN), 'Database is on fire.');
  assert.equal(passkeyMessage({}), 'Something went wrong. Try again.');
});

test('account_log_and_form_are_spanish_and_stored_values_are_not_translated', () => {
  const row = {id: 'a', started_at: '2026-03-04T12:00:00Z', outcome: 'fish', count: 1, species: 'Lingcod <i>', method: 'jig', note: '<b>x</b>', trip_id: 't1'};
  const html = logItemHTML(row, [{id: 't1', date: '2026-03-04'}], 'dd', ES);
  assert.match(html, /1 pez · Lingcod &lt;i&gt; · jig · Viaje: 2026-03-04/);
  assert.match(html, /marzo|mar\b/i);                                              // the date reads in es
  assert.match(html, /&lt;b&gt;x&lt;\/b&gt;/); assert.match(html, />Eliminar<\/button>/);
  assert.match(logItemHTML({...row, count: 4}, [], 'dd', ES), /4 peces/);
  assert.match(logItemHTML({...row, outcome: 'blank'}, [], 'dd', ES), /Sin capturas: ningún pez/);
  assert.match(logItemHTML({...row, outcome: 'strange'}, [], 'dd', ES), /strange/);
  const counts = {entries: 3, fish: 2, fishTotal: 5, blank: 1, unknown: 0, species: [{name: 'Lingcod', count: 2}]};
  assert.equal(logCountsText(counts, {filtered: true, more: true}, ES), 'En las 3 entradas cargadas que coinciden: 2 salidas con peces (5 peces), 1 sin capturas, 0 sin certeza. Más registradas: Lingcod 2. Las entradas anteriores aún no están cargadas.');
  assert.match(positionFieldHTML('log', 'lat', 'Latitud', '', 'dd', ES), /Por ejemplo 35\.3576/);
  assert.throws(() => logBody({lat: '', lon: '-120'}, ES), /Ingresa latitud y longitud, o ninguna de las dos\./);
  const els = {list: {}, counts: {}, species: {}};
  drawLogView(els, {entries: [row], view: {outcome: 'blank', species: ''}, copy: ES});
  assert.equal(els.counts.textContent, 'Ninguna entrada cargada coincide con estos filtros.');
  assert.match(els.species.innerHTML, /<option value="">Cualquiera<\/option>/);
});

// Protected areas through the real shared screen, as tests/test_saved_spots.mjs does (offline fetch).
const MPAS = read('../dist/data/protected-areas.geojson');
const buchon = MPAS.features.find(f => f.properties.NAME === 'Point Buchon SMR');
const ring = buchon.geometry.type === 'Polygon' ? buchon.geometry.coordinates[0] : buchon.geometry.coordinates[0][0];
async function screenAt(checkedAt) {
  const saved = {fetch: globalThis.fetch, document: globalThis.document};
  globalThis.fetch = async () => ({ok: true, json: async () => ({...MPAS, checked_at: checkedAt})});
  globalThis.document = {getElementById: () => ({classList: {toggle() {}}, textContent: ''}), dispatchEvent() {}};
  try { return await initProtectedAreas(null, () => {}); } finally { Object.assign(globalThis, saved); }
}
const spot = (name, lat, lon, note = 'PRIVATE-NOTE-7') => ({id: 'id-' + name.replace(/\W/g, ''), name, lat, lon, note});
const NOW = new Date('2026-03-04T12:00:00Z');

test('account_spots_es_refusals_keep_every_caveat_and_gpx_is_identical_across_languages', async () => {
  const screen = await screenAt(new Date().toISOString()), region = getRegion();
  const inside = spot('Inside', ring[0][1], ring[0][0]), open = spot('Open water', 35.0, -121.6);
  const [vi] = await spotVerdicts([inside], screen, ES), [vc] = await spotVerdicts([open], screen, ES);
  assert.equal(vi.status, 'excluded'); assert.equal(vc.status, 'clear'); assert.equal(vc.text, '');
  assert.match(vi.text, /^(?:Dentro de un área protegida, según su límite; SkipperCast lo excluye como objetivo de pesca\.|Dentro o a 70 m o menos de un área protegida, según su límite; SkipperCast lo excluye como objetivo de pesca\.)( .*\.)? No exportado\.$/);
  const [en] = await spotVerdicts([inside], screen);
  assert.match(en.text, /^Inside a protected-area boundary; excluded as a fishing target by SkipperCast\.( .*\.)? Not exported\.$/);
  const stale = await screenAt(new Date(Date.now() - 40 * 3600e3).toISOString());
  for (const s of [null, stale]) {
    const [u] = await spotVerdicts([open], s, ES);
    assert.deepEqual(u, {status: 'unavailable', text: 'Áreas protegidas no revisadas para este sitio: fuera de cobertura o comprobación no disponible; no exportado.'});
    await assert.rejects(exportSpots([open], s, region, NOW, ES), {message: 'Las comprobaciones de áreas protegidas no están disponibles o tienen más de 36 horas, o un sitio guardado está fuera de cobertura. No se exportó nada.'});
    await assert.rejects(exportSpots([open], s, region, NOW), /unavailable or older than 36 hours/);
  }
  await assert.rejects(exportSpots([], screen, region, NOW, ES), {message: 'No tienes sitios guardados para exportar.'});
  await assert.rejects(exportSpots([inside], screen, region, NOW, ES), {message: 'Todos los sitios guardados están dentro o cerca de un área protegida, por lo que no se exportó nada.'});
  await assert.rejects(exportSpots([inside], screen, region, NOW), {message: 'Every saved spot is inside or near a protected area, so nothing was exported.'});
  // Success and partial export: the same bytes in both languages, and no note in either.
  for (const spots of [[open], [open, inside]]) {
    const a = await exportSpots(spots, screen, region, NOW), b = await exportSpots(spots, screen, region, NOW, ES);
    assert.ok(a.gpx === b.gpx, 'identical GPX bytes');
    assert.ok(!a.gpx.includes('PRIVATE-NOTE-7') && !b.gpx.includes('PRIVATE-NOTE-7'), 'notes never in the GPX');
    assert.equal(a.exported, 1); assert.equal(b.withheld, spots.length - 1);
  }
  const item = spotItemHTML(inside, vi, 'dd', ES);
  assert.match(item, /No exportado\./); assert.ok(item.includes('PRIVATE-NOTE-7'));   // on screen for its owner only
});

test('account_spots_fine_print_es_adds_the_gpx_note_sentence_and_keeps_privacy_terms', () => {
  assert.match(STRINGS['account.spots.notesGpx'].es, /^Las notas privadas nunca se incluyen en el GPX\.$/);
  const es = STRINGS['account.spots.fine'].es;
  for (const term of ['nunca se comparten', 'dentro de un área protegida', 'se excluyen del archivo GPX']) assert.ok(es.includes(term), term);
  // owner-only spots may be shown on their own Chart; only notes are never mapped or in the GPX
  assert.ok(es.includes('Puedes mostrar tus sitios guardados en tu propia Carta'));
  assert.ok(es.includes('Las notas privadas nunca se dibujan en el mapa ni se incluyen en el GPX'));
  assert.ok(!/sitio y su nota nunca[^.]*se muestran en el mapa/.test(es));
  assert.match(STRINGS['account.log.fine'].es, /Una posición nunca se comparte/);
  assert.match(STRINGS['account.out.fine'].es, /solo almacena su clave pública/);
  assert.match(STRINGS['account.del.body'].es, /No se puede deshacer\.$/); assert.match(STRINGS['account.del.confirm'].es, /No se puede deshacer\.$/);
  assert.match(STRINGS['account.exp.unavailable'].es, /36 horas/);
  assert.match(STRINGS['account.spots.unchecked'].es, /no revisadas/);
  // the English panel never gains the Spanish-only paragraph
  assert.ok(!SOURCE.includes('Private notes are never included in the GPX.'));
});

test('account_lint_rejects_bare_text_in_an_account_template_and_unknown_ids', () => {
  const root = mkdtempSync(join(tmpdir(), 'acct-lint-'));
  const put = (path, text) => { mkdirSync(join(root, path.split('/').slice(0, -1).join('/')), {recursive: true}); writeFileSync(join(root, path), text); };
  const catalogue = {strings: {'account.a': {en: 'Hello there friend', es: 'Hola amigo mío'}}};
  const check = source => { put('catalog/app/strings.json', JSON.stringify(catalogue)); put('dist/account.js', source); return catalogueProblems(root); };
  assert.deepEqual(check("const f = t => `<p class=\"x-y\">${t('account.a')}</p><button id=\"b\" title=\"${t('account.a')}\">${t('account.a')}</button>`;"), []);
  assert.match(check('const f = t => `<p>${t(\'account.a\')}</p><p>Bare words in a paragraph</p>`;')[0], /bare literal "Bare words in a paragraph"/);
  assert.match(check('const f = t => `<button title="Add another passkey now">${t(\'account.a\')}</button>`;')[0], /bare literal "Add another passkey now"/);
  assert.match(check('const f = t => `<button aria-label="Close the whole account">x</button>`;')[0], /bare literal "Close the whole account"/);
  assert.match(check('const f = t => `<input placeholder="e.g. some example name" />`;')[0], /bare literal/);
  assert.match(check("const f = t => ` disabled title=\"Bare attribute text here\"`;")[0], /bare literal/);
  assert.match(check("const f = t => t('account.missing');")[0], /account\.missing/);
  // a missing es value fails
  catalogue.strings['account.b'] = {en: 'Only English'};
  assert.match(check("const f = t => t('account.a');").join('\n'), /account\.b has no es value/);
  // non-HTML literals keep the original scan
  delete catalogue.strings['account.b'];
  assert.match(check("const f = () => 'A bare sentence of prose';")[0], /bare literal/);
});
