// SC0922-12: the saved-trip alerts sheet's own words follow the page language; what the server wrote (assessment
// messages, hazard notes) stays English and verbatim. Synthetic records only; no network.
import './helpers/spanish-ready.mjs';   // SC1407-09: the Spanish table, before the Spanish renders
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {mkdtemp, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import test from 'node:test';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {preparedRendererPlugins} from './helpers/esbuild-url.mjs';
import * as alerts from '../web/alerts.ts';
import {readableDate} from '../web/dates.ts';
import {weekendDigest, toText, EMPTY_WEEKEND} from '../web/digest.ts';
import {catalogueProblems, COVERED} from '../scripts/check_copy.mjs';

const ROOT = new URL('..', import.meta.url).pathname;
const STRINGS = JSON.parse(readFileSync(new URL('../catalog/app/strings.json', import.meta.url), 'utf8')).strings;
const ids = Object.keys(STRINGS).filter(id => id.startsWith('alerts.') || id.startsWith('digest.'));
const vars = s => [...s.matchAll(/\{(\w+)\}/g)].map(m => m[1]).sort().join();

test('catalogue: every alerts/digest id has Spanish with the same variables; the three files are covered', () => {
  assert.ok(ids.length > 100);
  for (const id of ids) {
    assert.ok(STRINGS[id].es?.trim(), `${id} has es`);
    assert.equal(vars(STRINGS[id].es), vars(STRINGS[id].en), `${id} variables`);
  }
  for (const path of ['web/app/TripAlerts.tsx', 'web/alerts.ts', 'web/digest.ts']) assert.ok(COVERED.includes(path), path);
  assert.deepEqual(catalogueProblems(ROOT).filter(p => /TripAlerts|alerts\.ts|digest\.ts|alerts\.|digest\./.test(p)), []);
});

test('kind and delivery labels: English as before, Spanish by catalogue, unknown and inherited keys raw', () => {
  assert.deepEqual({...alerts.KIND_LABEL}, {initial: 'First assessment', update: 'Material change', retraction: 'Earlier alert withdrawn', final: 'Day-before assessment', 'missed-final': 'Day-before assessment missed'});
  assert.deepEqual({...alerts.STATUS_LABEL}, {pending: 'sending', accepted: 'sent to your device', uncertain: 'delivery not confirmed', held: 'not delivered — read it here', 'in-app': 'shown here', delivered: 'delivered', read: 'read'});
  assert.equal(alerts.eventLine({id: 1, kind: 'final', status: 'in-app', message: ''}), 'Day-before assessment · shown here');
  assert.equal(alerts.eventLine({id: 1, kind: 'final', status: 'in-app', message: ''}, 'es'), 'Evaluación del día anterior · mostrada aquí');
  assert.equal(alerts.kindLabel('missed-final', 'es'), 'No se realizó la evaluación del día anterior');
  assert.equal(alerts.statusLabel('held', 'es'), 'no entregada — léela aquí');
  for (const key of ['constructor', '__proto__', 'toString', 'Final', 'hasOwnProperty', '']) {
    assert.equal(alerts.kindLabel(key, 'es'), key, key);
    assert.equal(alerts.statusLabel(key, 'es'), key, key);
  }
});

test('form problems keep their order and carry catalogue ids; the English text is unchanged', () => {
  const range = {min: '2026-11-05', max: '2026-11-12'};
  const form = (over = {}) => ({date: '2026-11-06', point: 'p', start_hour: 7, end_hour: 13, wind_limit: 8, gust_limit: 12, sea_limit: 3, ...over});
  assert.equal(alerts.formProblemId(form(), range), null);
  assert.equal(alerts.formProblem(form(), range, 'es'), null);
  // A bad date wins over a bad window, which wins over a bad gust.
  const all = form({date: '2026-02-31', end_hour: 5, gust_limit: 1});
  assert.equal(alerts.formProblemId(all, range), 'alerts.problem.date');
  assert.equal(alerts.formProblem(all, range), 'Choose a date from today to seven days ahead.');
  assert.equal(alerts.formProblem(all, range, 'es'), 'Elige una fecha desde hoy hasta siete días después.');
  assert.equal(alerts.formProblemId(form({end_hour: 7}), range), 'alerts.problem.window');
  assert.equal(alerts.formProblem(form({end_hour: 7}), range, 'es'), 'La ventana debe terminar después de comenzar.');
  assert.equal(alerts.formProblemId(form({gust_limit: 5}), range), 'alerts.problem.gust');
  assert.equal(alerts.formProblem(form({gust_limit: 5}), range), 'The gust limit cannot be lower than the wind limit.');
});

test('local service failures keep their English message and carry an id; a server error is never mapped', async () => {
  const bad = await alerts.api('trips', {}, async () => new Response('<html>', {status: 200})).catch(e => e);
  assert.ok(bad instanceof alerts.AlertCopyError && bad instanceof Error);
  assert.equal(bad.message, 'Personal services are available on the published site.');
  assert.equal(bad.id, 'alerts.err.personal');
  const plain = await alerts.api('trips', {}, async () => Response.json({}, {status: 500})).catch(e => e);
  assert.equal(plain.message, 'Could not complete this request.');
  assert.equal(plain.id, 'alerts.err.request');
  // The server's own words, even when they look like ours, stay a plain Error shown as received.
  const server = await alerts.api('trips', {}, async () => Response.json({error: 'Could not complete this request.'}, {status: 400})).catch(e => e);
  assert.ok(!(server instanceof alerts.AlertCopyError));
  assert.equal(server.message, 'Could not complete this request.');
});

test('stop statuses: ids resolve in either language; the English helper is unchanged', () => {
  for (const [scope, result, en] of [['device', 'none', 'No notifications are enabled on this device. Other devices were not changed.'], ['all', 'partial', 'The server stopped notifications, but this browser could not unsubscribe. Try again.'],
    ['all', 'stopped', 'Notifications stopped on all devices. Saved assessments remain available here.']]) {
    assert.equal(alerts.stopStatus(scope, result), en);
    assert.notEqual(alerts.stopStatus(scope, result, 'es'), en);
  }
  assert.equal(alerts.stopStatusId('device', 'stopped'), 'alerts.stop.device');
});

test('feedback phase, trip line, saved limits and reuse notes: English unchanged, Spanish by catalogue', () => {
  const fb = phase => ({observed_at: '', rating: 7, context: JSON.stringify({phase})});
  assert.equal(alerts.feedbackPhase(fb('return')), 'return');
  assert.equal(alerts.feedbackPhase(fb('return'), 'es'), 'Regreso');
  assert.equal(alerts.feedbackPhase(fb('outbound'), 'es'), 'Ida');
  assert.equal(alerts.feedbackPhase(fb('swimming'), 'es'), 'swimming', 'an unknown phase prints as stored');
  assert.equal(alerts.feedbackPhase(fb('constructor'), 'es'), 'constructor');
  assert.equal(alerts.feedbackPhase({observed_at: '', rating: 7, context: '{'}, 'es'), '');
  const trip = {id: 't', date: '2026-11-07', point: 'p', species: 's', start_hour: 7, end_hour: 13, boat_sea: 0.7, boat_name: ''};
  assert.equal(alerts.tripLine(trip), 'Sat 7 Nov · p · s · 7:00–13:00 · saved boat');
  assert.equal(alerts.tripLine(trip, undefined, 'es'), 'sáb 7 nov · p · s · 7:00–13:00 · embarcación guardada');
  assert.equal(alerts.tripLine({...trip, boat_name: 'My <b>Boat</b>'}, undefined, 'es').endsWith('My <b>Boat</b>'), true);
  assert.equal(alerts.savedTripLimits({...trip, wind_limit: 9, gust_limit: 14}), 'Saved limits: wind 9 kt · gust 14 kt · sea not recorded');
  assert.equal(alerts.savedTripLimits({...trip, wind_limit: 9, gust_limit: 14, sea_limit: 2.5}, 'es'), 'Límites guardados: viento 9 kt · ráfaga 14 kt · oleaje 2.5 ft');
  assert.equal(alerts.reuseStatus(['area', 'limits']), 'Window copied. Choose a date, then save. Area was not copied because it is no longer offered in this region. Some saved limits could not be copied.');
  assert.ok(alerts.reuseStatus(['area'], 'es').startsWith('Ventana copiada.'));
  assert.equal(alerts.reuseLimitsNote('2026-10-24', 'some', true), "Some limits start from your saved trip on 2026-10-24; other limits were left unchanged. Alerts use your current boat settings, not the old trip's boat.");
  assert.ok(alerts.reuseLimitsNote('2026-10-24', 'all', false, 'es').includes('2026-10-24'));
  assert.equal(alerts.alertSpecies({id: 'r', timezone: 'UTC', species: ['x'], forecast_points: []}, null).options[0].group, 'Other');
  assert.equal(alerts.alertSpecies({id: 'r', timezone: 'UTC', species: ['x'], forecast_points: []}, null, 'es').options[0].group, 'Otros');
  const when = {id: 1, kind: 'final', status: 'read', message: '', created_at: '2026-11-07T20:30:00Z'};
  assert.equal(alerts.assessmentTime(when, 'America/Los_Angeles'), '07 Nov 2026, 12:30 GMT-8');
  assert.equal(alerts.assessmentTimeOrNull({...when, created_at: 'nope'}), null);
  assert.equal(alerts.assessmentTime({...when, created_at: 'nope'}), 'Time unavailable');
  assert.equal(alerts.assessmentTime({...when, created_at: 'nope'}, 'UTC', 'es'), 'Hora no disponible');
});

// A Saturday 2026-11-07 and Sunday 2026-11-08 follow Thursday 2026-11-05.
const TODAY = '2026-11-05';
const names = {point: new Map([['b', 'Bravo'], ['a', 'Alpha']]), species: new Map([['reef', 'Reef fish']])};
const HAZ = ['  Swell 9 ft at 14 s.  ', 'Bar crossing:\nnot judged', 'Swell 9 ft at 14 s.  ', 'Ünïcode <b>x</b>'];
const row = (id, point, start, status, hazards, extra = {}) => ({id, date: '2026-11-07', point, species: 'reef', start_hour: start, end_hour: start + 4,
  last_assessment: status === null ? null : JSON.stringify({status, hazards}), ...extra});

test('digest: Spanish changes the words and the hazard prefix only; stored hazards and the order are byte-for-byte the same', () => {
  const trips = [row('1', 'b', 9, 'above limits', HAZ), row('2', 'a', 7, 'within limits', []), row('3', 'zz', 7, 'unverified', undefined), row('4', 'a', 7, null),
    row('5', 'a', 6, 'something new', ['kept']), row('6', 'a', 5, 'within limits', ['ok', 7]), row('7', 'a', 4, 'held', []), row('off', 'a', 3, 'within limits', [], {enabled: 0})];
  const en = weekendDigest(trips, names, TODAY), es = weekendDigest(trips, names, TODAY, 'es');
  assert.equal(weekendDigest(trips, names, TODAY, 'en').days[0].lines.join('\n'), en.days[0].lines.join('\n'));
  assert.equal(en.days.length, es.days.length);
  assert.equal(en.days[0].lines.length, 7, 'the disabled trip is left out in both');
  assert.equal(es.days[0].lines.length, 7);
  // Same trips in the same order: the part before the status does not depend on the language except the fallback place name.
  const place = line => line.split(' · ')[0];
  assert.deepEqual(es.days[0].lines.map(place).map(p => p === 'un lugar guardado' ? 'a saved spot' : p), en.days[0].lines.map(place));
  const withNotes = es.days[0].lines.find(l => l.startsWith('Bravo'));
  const expectedTail = `por encima de tus límites guardados${HAZ.map(n => ` Nota de peligro: ${n}`).join('')}`;
  assert.ok(withNotes.endsWith(expectedTail), 'notes as stored, only the prefix is Spanish');
  assert.ok(en.days[0].lines.find(l => l.startsWith('Bravo')).endsWith(`above your saved limits${HAZ.map(n => ` Hazard note: ${n}`).join('')}`));
  const text = toText(es, 'es');
  for (const [word, spanish] of [['within your saved limits', 'dentro de tus límites guardados'], ['check incomplete', 'comprobación incompleta'], ['not assessed yet', 'aún sin evaluar']]) {
    assert.ok(toText(en).includes(word) && text.includes(spanish), word);
  }
  assert.ok(text.includes('something new Nota de peligro: kept'), 'an unknown status stays raw, its note still stored');
  assert.ok(!text.includes('Nota de peligro: ok'), 'one bad note drops the whole list, as before');
});

test('UXFIX-07 readableDate: Tue 10 Nov / mar 10 nov in the region zone; the DST day keeps its calendar day; anything unreadable prints as given', () => {
  const LA = 'America/Los_Angeles';
  assert.equal(readableDate('2026-11-10', 'en', LA), 'Tue 10 Nov');
  assert.equal(readableDate('2026-11-10', 'es', LA), 'mar 10 nov');
  assert.equal(readableDate('2026-11-01', 'en', LA), 'Sun 1 Nov', 'the day the clocks go back is still that day');
  assert.equal(readableDate('2026-11-02', 'en', LA), 'Mon 2 Nov');
  for (const zone of ['Pacific/Auckland', 'Pacific/Kiritimati', 'Etc/GMT+12']) assert.equal(readableDate('2026-11-10', 'en', zone), 'Tue 10 Nov', zone);
  for (const bad of ['2026-02-31', '11/09/2026', '', 'soon']) assert.equal(readableDate(bad, 'en', LA), bad, bad);
  assert.equal(readableDate('2026-11-10', 'en', 'Not/AZone'), '2026-11-10', 'an unknown zone does not throw');
  assert.doesNotMatch(readableDate('2026-11-10', 'es', LA), /[,.]/);
  assert.equal(alerts.tripLine({id: 't', date: '2026-11-10', point: 'p', species: 's', start_hour: 7, end_hour: 13}, undefined, 'en', 'Pacific/Auckland'), 'Tue 10 Nov · p · s · 7:00–13:00');
});

test('digest: the empty weekend says its line in the chosen language; the English export is unchanged', () => {
  const none = weekendDigest([], names, TODAY, 'es');
  assert.equal(none.empty, true);
  assert.equal(toText(none), 'No saved trips this weekend. Save a date above to get a day-before assessment.');
  assert.equal(toText(none), EMPTY_WEEKEND);
  assert.equal(toText(none, 'es'), 'No hay viajes guardados para este fin de semana. Guarda una fecha arriba para recibir una evaluación el día anterior.');
});

let ui;
async function components() {
  if (ui) return ui;
  const dir = await mkdtemp(join(tmpdir(), 'trip-alerts-i18n-')), out = join(dir, 'ui.mjs');
  await build({stdin: {resolveDir: ROOT, loader: 'ts', contents: `
    export {SavedTrips} from './web/app/TripAlerts.tsx';
    export {tripRecaps} from './web/alerts.ts';
    export {language} from './web/i18n.ts';
    export {render} from 'preact-render-to-string'; export {h} from 'preact';`},
  bundle: true, format: 'esm', platform: 'node', outfile: out, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact', plugins: preparedRendererPlugins});
  ui = await import(pathToFileURL(out).href);
  return ui;
}

test('recap: Spanish headings and catch labels; the server assessment stays English, marked only in Spanish; English output unchanged', async () => {
  const m = await components();
  const trip = (id, date) => ({id, date, point: 'a', species: 'reef', start_hour: 7, end_hour: 13, wind_limit: 9, gust_limit: 14, sea_limit: 2.5});
  const MESSAGE = 'Wind may exceed your limit.\nHazard note: <b>Bar</b> crossing';
  const events = [{id: 'e', trip_id: 'p', kind: 'final', status: 'in-app', message: MESSAGE, created_at: '2026-11-01T20:00:00Z'}];
  const entries = [{id: 'f', trip_id: 'p', started_at: '2026-11-01T15:00:00Z', outcome: 'fish', count: 3}, {id: 'b', trip_id: 'p', started_at: '2026-11-01T15:00:00Z', outcome: 'blank', count: 0},
    {id: 'u', trip_id: 'p', started_at: '2026-11-01T15:00:00Z', outcome: 'unknown', count: 0}];
  const feedback = [{observed_at: '2026-11-01T20:00:00Z', rating: 8, context: '{"phase":"fishing"}'}];
  const draw = () => m.render(m.h(m.SavedTrips, {recaps: m.tripRecaps([trip('p', '2026-11-01'), trip('n', '2026-11-06')], events, feedback, TODAY, entries),
    names, remove: () => () => {}, useAgain: () => {}, events, read: {loading: false, complete: false}, timeZone: 'America/Los_Angeles'}));
  try {
    m.language.value = 'en';
    const en = draw();
    assert.ok(en.includes('<h3>Upcoming</h3>') && en.includes('<h3>Past</h3>') && en.includes('Fish · 3 fish') && en.includes('Blank: no fish') && en.includes('Not sure'));
    assert.ok(en.includes('Older catch-log entries were not read. The entries shown may be incomplete.'));
    assert.ok(!/ lang="/.test(en), 'English output carries no language marks');
    assert.ok(en.includes('<p style="white-space:pre-line;">Wind may exceed your limit.\nHazard note: &lt;b>Bar&lt;/b> crossing</p>'), 'message verbatim and escaped once ');
    assert.ok(en.includes('Sun 1 Nov · Alpha') && en.includes('Fri 6 Nov · Alpha'), 'the rows read Sun 1 Nov / Fri 6 Nov');
    assert.ok(en.includes('Delete the trip on Sun 1 Nov at Alpha') || en.includes('Sun 1 Nov'), 'aria names use the readable date');
    assert.ok(!/\b\d{4}-\d{2}-\d{2}\b/.test(en), 'no ISO date is left in the visible text or the names');
    m.language.value = 'es';
    const es = draw();
    assert.ok(es.includes('dom 1 nov · Alpha') && !/\b\d{4}-\d{2}-\d{2}\b/.test(es), 'Spanish: the same, lower-case, no ISO');
    for (const text of ['<h3>Próximos</h3>', '<h3>Pasados</h3>', 'Tu propio registro de cada viaje. Las evaluaciones del pronóstico son lo que enviamos antes del día, no lo que hizo el mar.',
      'Evaluación del día anterior · mostrada aquí', 'Tus informes de comodidad', '8/10 · Pesca', 'Tu registro de capturas', 'Captura · 3 peces', 'Sin captura: ningún pez', 'No se sabe',
      'Eliminar</button>', 'aria-label="Eliminar el viaje del dom 1 nov en Alpha"', 'Usar de nuevo', 'Límites guardados: viento 9 kt · ráfaga 14 kt · oleaje 2.5 ft', 'Sin evaluación reciente',
      'No se leyeron las entradas más antiguas del registro de capturas.'])
      assert.ok(es.includes(text), text);
    assert.ok(es.includes(`<p lang="en" style="white-space:pre-line;">Wind may exceed your limit.\nHazard note: &lt;b>Bar&lt;/b> crossing</p>`), 'the server text is verbatim and marked English');
    assert.ok(!/Upcoming|Past<|Delete|Not sure|Fish ·/.test(es.replace(MESSAGE, '')), 'no English chrome is left');
    m.language.value = 'en';
    assert.equal(draw(), en, 'English → Spanish → English returns the same markup');
  } finally { m.language.value = 'en'; }
});

test('privacy, retention, deletion and purpose sentences keep their meaning in Spanish', () => {
  const es = id => STRINGS[id].es, en = id => STRINGS[id].en;
  assert.ok(en('alerts.privacy.body').includes('Comfort feedback is retained for one year; trips and assessments for 90 days.'));
  assert.ok(es('alerts.privacy.body').includes('Los informes de comodidad se conservan durante un año; los viajes y las evaluaciones, durante 90 días.'));
  assert.ok(es('alerts.privacy.body').includes('Elimina un viaje para detener su seguimiento.'));
  assert.ok(es('alerts.privacy.body').includes('se guardan de forma privada.'));
  assert.ok(es('alerts.privacy.body').includes('hasta que los elimines o elimines tu cuenta.'));
  assert.ok(es('alerts.confirm').endsWith('Esto no se puede deshacer.'));
  for (const word of ['claves de acceso', 'sesiones iniciadas', 'viajes guardados', 'suscripciones a notificaciones', 'evaluaciones', 'informes de comodidad', 'registro de capturas', 'lugares guardados']) assert.ok(es('alerts.confirm').includes(word), word);
  assert.ok(en('alerts.purpose').includes('they do not plan navigation or predict catches.'));
  assert.ok(es('alerts.purpose').includes('no planifican la navegación ni predicen capturas.'));
  assert.ok(es('alerts.status.saved').includes('aproximadamente cada 30 minutos') && es('alerts.status.saved').includes('permiso del dispositivo'));
  assert.ok(es('alerts.english').includes('en inglés'));
});
