// SC0452-09: the verdict's reasons in Spanish. web/brief/verdict.ts decides everything in English-keyed data; web/brief/verdict-copy.ts
// phrases the result from the catalogue (catalog/app/strings.json, `verdict.`). These tests pin the Spanish sentences, that the English
// output and every decision are unchanged by the language, that no warning reads milder in Spanish, and that every reason the profile
// graders can write has a Spanish form. Synthetic feeds, values invented; no network.
import assert from 'node:assert/strict';
import test from 'node:test';
import {boatVerdict, briefVerdict, longPeriodHour, profileVerdict, feedReader, windowHours, ALERT_CHECK_MISSING, NO_ALERT_CHECK, NO_DAYLIGHT} from '../web/brief/verdict.ts';
import {verdictCopy} from '../web/brief/verdict-copy.ts';
import {t} from '../web/i18n.ts';
import {kayakVerdict} from '../packages/coast/src/kayak.ts';
import {shoreVerdict} from '../packages/coast/src/shore-conditions.ts';
import {spearVerdict} from '../packages/coast/src/spear.ts';
import catalogue from '../catalog/app/strings.json' with {type: 'json'};

const TZ = 'America/Los_Angeles';
const DATE = '2026-10-13';
const NOW = new Date('2026-10-13T12:00:00Z'); // 5 am PDT
const SUNRISE = '2026-10-13T14:10:00Z', SUNSET = '2026-10-14T01:30:00Z'; // 7:10 am, 6:30 pm PDT
const START = Date.parse('2026-10-13T07:00:00Z') / 1000;
const TIMES = Array.from({length: 48}, (_, i) => START + i * 3600);

const BASE = {
  wind_speed_10m: 6, wind_gusts_10m: 9, wind_direction_10m: 315,
  ecmwf_wind: 6, ecmwf_gust: 9, wave_height: 2.5, wave_period: 11, wind_wave_height: 0.3, wind_wave_period: 4,
  swell_wave_height: 2.4, swell_wave_period: 11, swell_wave_direction: 300, secondary_swell_wave_height: 0.5, secondary_swell_wave_direction: 200, wam: 2.5,
};
const UNITS = {wind_speed_10m: 'kn', wind_gusts_10m: 'kn', wind_direction_10m: '°', wave_height: 'ft', wave_period: 's', wind_wave_height: 'ft', wind_wave_period: 's',
  swell_wave_height: 'ft', swell_wave_period: 's', swell_wave_direction: '°', secondary_swell_wave_height: 'ft', secondary_swell_wave_direction: '°'};

/** A parsed ConditionsForecast at one point; `at(epoch)` overrides values per hour; `drop` leaves models out; runs issued `runAgeH` before NOW. */
function forecast({over = {}, at = () => ({}), drop = [], runAgeH = 4} = {}) {
  const v = epoch => ({...BASE, ...over, ...at(epoch)});
  const series = keys => ({utc_offset_seconds: 0, hourly_units: {time: 'unixtime', ...Object.fromEntries(keys.map(([k]) => [k, UNITS[k]]))},
    hourly: {time: TIMES, ...Object.fromEntries(keys.map(([k, src]) => [k, TIMES.map(t0 => v(t0)[src ?? k])]))}});
  const run = (id, keys) => ({id, issued: NOW.getTime() / 1000 - runAgeH * 3600, end: TIMES.at(-1), data: series(keys)});
  const models = {
    gfs_global: run('gfs_global', [['wind_speed_10m'], ['wind_gusts_10m'], ['wind_direction_10m']]),
    ncep_gfswave016: run('ncep_gfswave016', ['wave_height', 'wave_period', 'wind_wave_height', 'wind_wave_period', 'swell_wave_height', 'swell_wave_period', 'swell_wave_direction', 'secondary_swell_wave_height', 'secondary_swell_wave_direction'].map(k => [k])),
    ecmwf_ifs025: run('ecmwf_ifs025', [['wind_speed_10m', 'ecmwf_wind'], ['wind_gusts_10m', 'ecmwf_gust']]),
    ecmwf_wam: run('ecmwf_wam', [['wave_height', 'wam']]),
  };
  for (const id of drop) delete models[id];
  return {region: 'morro-bay', retrieved: NOW.getTime(), point: {id: 'morro-bay', lat: 35.37, lon: -120.9}, models};
}
const brief = (over = {}) => ({profile: 'boat', date: DATE, sunrise: SUNRISE, sunset: SUNSET, alerts: [], missing: [], bar: null, shore: null, spear: null, kayak: null, tiles: [], ...over});
const hourAt = h => Date.parse(`2026-10-13T${String(h + 7).padStart(2, '0')}:00:00Z`) / 1000; // local hour h -> epoch
const windy = (wind, gust) => ({wind_speed_10m: wind, ecmwf_wind: wind, wind_gusts_10m: gust, ecmwf_gust: gust});

const en = (b, f, now = NOW) => boatVerdict(b, f, now, TZ);
const es = (b, f, now = NOW) => boatVerdict(b, f, now, TZ, undefined, 'es');
/** A sentence's numbers in order, whichever decimal mark, with the clock hours taken out (they are not measurements). */
const numbers = s => (s.replace(/ at (?:\d+ (?:am|pm)|noon|midnight)|(?: a las| hasta las) \d+/g, '').replace(/,/g, '.').match(/\d+(?:\.\d+)?/g) ?? []);

test('verdict_es_each_charge_and_numeric_bound: every charge is named in Spanish with the same numbers and units; English is byte-identical', () => {
  // wind, with and without gusts (a gust is named from 3 kt above the wind)
  assert.equal(es(brief(), forecast({at: t0 => t0 === hourAt(10) ? windy(20, 26) : {}})).limit, 'Viento de 20 kt con ráfagas de 26 a las 10.');
  assert.equal(es(brief(), forecast({over: windy(16, 18)})).limit, 'Viento de 16 kt a las 8.');
  assert.equal(en(brief(), forecast({over: windy(16, 18)})).limit, '16 kt wind at 8 am.');
  // seas: GFS-Wave's period only with GFS-Wave's height; the maximum rounds up and takes a decimal comma
  const seas = {wave_height: 7.31, wam: 7, wave_period: 8, swell_wave_height: 6.5};
  assert.equal(es(brief(), forecast({over: seas})).limit, 'Mar de 7,4 ft a 8 s a las 8.');
  assert.equal(en(brief(), forecast({over: seas})).limit, '7.4 ft seas at 8 s at 8 am.');
  assert.equal(es(brief(), forecast({over: {wave_height: 7, wam: 7.4, wave_period: 8, swell_wave_height: 6.5}})).limit, 'Mar de 7,4 ft a las 8.', 'WAM seas: no period that is not WAM\'s');
  assert.equal(es(brief(), forecast({over: {wave_height: 2.5000001, wam: 2.5000001, swell_wave_height: 2, wave_period: 11, ...windy(6, 9)}})).limit.startsWith('Viento de hasta 6 kt y mar de hasta 2,6 ft'), true, 'a printed maximum is never below the value used (up, not nearest)');
  // wind chop, and the short steep kind
  const chop = {wind_wave_height: 2.2, wind_wave_period: 3, ...windy(12, 15)};
  assert.equal(es(brief(), forecast({over: chop})).limit, 'Viento de 12 kt con ráfagas de 15 a las 8, con oleaje corto y empinado por viento de 2,2 ft.');
  assert.equal(en(brief(), forecast({over: chop})).limit, '12 kt wind gusting 15 at 8 am, with 2.2 ft of short, steep wind chop.');
  // the calm sentence: the window's top wind and seas, through the window's end (Spanish clock, not a label split)
  assert.equal(es(brief(), forecast()).limit, 'Viento de hasta 6 kt y mar de hasta 2,5 ft hasta las 12.');
  assert.equal(NO_DAYLIGHT, 'No daylight left on this day.'); assert.equal(NO_ALERT_CHECK, 'No current marine alert check.');
  // a grid of charged hours: the Spanish sentence has the English sentence's numbers, in order, the same verdict and score, and names a second charge only when English does
  let charged = 0, second = 0;
  for (const wind of [6, 10, 14, 18, 24]) for (const sea of [2.5, 3.5, 5, 7.25]) for (const chopFt of [0.3, 1.2, 2.2]) for (const secondary of [0.5, 3]) for (const from of [200, null]) {
    const f = forecast({over: {...windy(wind, wind + 4), wave_height: sea, wam: sea, swell_wave_height: sea - 0.5, wind_wave_height: chopFt, wind_wave_period: 3, secondary_swell_wave_height: secondary, secondary_swell_wave_direction: from}});
    const a = en(brief(), f), b = es(brief(), f), label = `wind ${wind}, seas ${sea}, chop ${chopFt}, secondary ${secondary}, from ${from}`;
    assert.deepEqual([b.verdict, b.score, b.held, b.window, b.basis], [a.verdict, a.score, a.held, a.window, a.basis], `${label}: the language never changes the rating`);
    assert.deepEqual(numbers(b.limit), numbers(a.limit), `${label}: ${a.limit} / ${b.limit}`);
    if (a.verdict === 'comfortable') continue;
    charged++;
    assert.equal(/ with | con /.test(a.limit), /, con /.test(b.limit), `${label}: second charge`);
    if (/, con /.test(b.limit)) second++;
    assert.doesNotMatch(b.limit, /\b(?:wind|seas|gusting|swell|chop|with|am|pm|noon)\b/, `${label}: no English left: ${b.limit}`);
  }
  assert.ok(charged >= 40 && second >= 5, `the grid reaches charged and second-charge hours (${charged}, ${second})`);
  // a crossing swell costs 0.7, under the point a second charge needs, so it is named only alone under an alert; the direction is named when the feed has one
  const cross = {wave_height: 1, wam: 1, swell_wave_height: 0.9, secondary_swell_wave_height: 3, secondary_swell_wave_direction: 200};
  const alerted = lang => boatVerdict(brief({alerts: [{event: 'Small Craft Advisory'}]}), forecast({over: cross}), NOW, TZ, undefined, lang);
  assert.equal(alerted('en').limit, 'Small Craft Advisory in effect. A 3 ft cross swell from the SSW at 8 am.');
  assert.equal(alerted('es').limit, 'Small Craft Advisory en vigor. Mar de fondo cruzado de 3 ft del SSW a las 8.');
  const rating = {wind: 6, gust: 9, sea: 1, chop: 0, costs: {short: 0}}, copy = verdictCopy('es');
  assert.equal(copy.phrase('cross', rating, {secondary: 3.5, secondary_from: null}), 'mar de fondo cruzado de 3,5 ft', 'no direction in the feed: none is invented');
  assert.equal(copy.phrase('cross', rating, {secondary: 3, secondary_from: 200}), 'mar de fondo cruzado de 3 ft del SSW');
  assert.equal(verdictCopy('en').phrase('cross', rating, {secondary: 3, secondary_from: null}), 'a 3 ft cross swell');
  // language omitted or 'en' is the same object content
  for (const f of [forecast(), forecast({over: chop}), forecast({over: seas})]) assert.ok(JSON.stringify(boatVerdict(brief(), f, NOW, TZ)) === JSON.stringify(boatVerdict(brief(), f, NOW, TZ, undefined, 'en')), 'omitted and en are identical');
});

test('verdict_es_all_holds_and_missing_alert: each hold, the missing alert check and an active alert say why in Spanish and never read milder', () => {
  const held = (b, f) => ({en: en(b, f), es: es(b, f)});
  const cases = [
    ['partial detail', brief(), forecast({drop: ['ecmwf_ifs025', 'ecmwf_wam']}), 'Se mantiene en Marginal: el detalle del pronóstico es parcial.'],
    ['unrated hours', brief(), forecast({at: t0 => t0 === hourAt(9) ? {wind_speed_10m: null, ecmwf_wind: null} : {}}), 'Se mantiene en Marginal: 1 de 4 horas no tienen pronóstico.'],
    ['stale run', brief(), forecast({runAgeH: 20}), 'Se mantiene en Marginal: la corrida del pronóstico tiene 20 h de antigüedad.'],
    ['alert check missing', brief({missing: [ALERT_CHECK_MISSING]}), forecast(), 'Se mantiene en Marginal: la revisión de avisos marinos no está disponible.'],
    ['hazardous bar', brief({bar: {hazardous: [{at: '2026-10-13T16:00:00Z'}]}}), forecast(), 'Se mantiene en Marginal: la estimación de la barra indica condiciones peligrosas a las 9.'],
    ['long-period swell', brief(), forecast({over: {wave_height: 5, wam: 5, wave_period: 16, swell_wave_period: 16}}), 'Se mantiene en Marginal: mar de fondo de período largo (5 ft a 16 s) a las 8.'],
  ];
  for (const [name, b, f, want] of cases) {
    const v = held(b, f);
    assert.equal(v.es.held, want, name);
    assert.ok(v.en.held?.startsWith('Held at Marginal: '), `${name}: English hold is the old sentence`);
    assert.deepEqual([v.es.verdict, v.es.score], [v.en.verdict, v.en.score], `${name}: held at Marginal in both languages`);
    assert.equal(v.es.verdict, 'marginal');
    assert.deepEqual(numbers(v.es.held), numbers(v.en.held), `${name}: same numbers`);
  }
  // all six together, in the original order, joined as before
  const all = held(brief({missing: [ALERT_CHECK_MISSING], bar: {hazardous: [{at: '2026-10-13T16:00:00Z'}]}}),
    forecast({drop: ['ecmwf_ifs025', 'ecmwf_wam'], runAgeH: 20, over: {wave_height: 5, wam: 5, wave_period: 16, swell_wave_period: 16}, at: t0 => t0 === hourAt(10) ? {wind_speed_10m: null, ecmwf_wind: null} : {}}));
  assert.equal(all.en.held, 'Held at Marginal: forecast detail is partial; 1 of 4 hours have no forecast; the forecast run is 20 h old; the marine alert check is unavailable; the bar estimate reads hazardous at 9 am; long-period swell (5 ft at 16 s) at 8 am.');
  assert.equal(all.es.held, 'Se mantiene en Marginal: el detalle del pronóstico es parcial; 1 de 4 horas no tienen pronóstico; la corrida del pronóstico tiene 20 h de antigüedad; la revisión de avisos marinos no está disponible; la estimación de la barra indica condiciones peligrosas a las 9; mar de fondo de período largo (5 ft a 16 s) a las 8.');
  // on a day that is already Marginal or Rough a missing alert check is still named, and nothing is held
  const marginal = held(brief({missing: [ALERT_CHECK_MISSING]}), forecast({over: windy(16, 22)}));
  assert.deepEqual([marginal.es.verdict, marginal.es.held, marginal.es.limit], ['marginal', null, 'Viento de 16 kt con ráfagas de 22 a las 8. No hay una revisión actual de avisos marinos.']);
  assert.ok(marginal.en.limit.endsWith(' No current marine alert check.'));
  const rough = held(brief({missing: [ALERT_CHECK_MISSING]}), forecast({over: windy(30, 38)}));
  assert.deepEqual([rough.es.verdict, rough.es.held], ['rough', null]);
  assert.ok(rough.es.limit.endsWith(' No hay una revisión actual de avisos marinos.'), rough.es.limit);
  // an active alert stays Rough with no score and names the event verbatim, even one that looks like a template
  for (const event of ['Small Craft Advisory', '{limit} Gale $& Warning']) {
    const v = es(brief({alerts: [{event}], missing: [ALERT_CHECK_MISSING]}), forecast());
    assert.deepEqual([v.verdict, v.score, v.held], ['rough', null, null]);
    assert.ok(v.limit.startsWith(`${event} en vigor. `), v.limit);
    assert.equal(v.limit.split(' en vigor. ')[1], 'Mar de 2,5 ft a 11 s a las 8.', 'the alert does not alter the reason after it');
  }
  // the profile path: unknown hours and the missing check hold a Comfortable window, in Spanish
  const at = h => `2026-10-13T${String(h + 7).padStart(2, '0')}:00:00Z`;
  const hours = [8, 9, 10, 11].map((h, i) => ({at: at(h), verdict: i ? 'Calmer' : 'Unknown', reasons: ['small surf']}));
  const b = brief({profile: 'shore', shore: {hours}, missing: [ALERT_CHECK_MISSING]});
  const p = profileVerdict(b, NOW, TZ, 'es'), q = profileVerdict(b, NOW, TZ);
  assert.equal(p.held, 'Se mantiene en Marginal: se desconocen 1 de 4 horas; la revisión de avisos marinos no está disponible.');
  assert.equal(q.held, 'Held at Marginal: 1 of 4 hours are unknown; the marine alert check is unavailable.');
  assert.equal(p.limit, 'Oleaje de rompiente pequeño hasta las 12.');
  assert.equal(p.verdict, q.verdict);
});

test('verdict_es_unknown_and_time_edges: no forecast, a day beyond it, no daylight and no rated hours stay Unknown in Spanish, with the region clock', () => {
  assert.deepEqual([es(brief(), null).verdict, es(brief(), null).limit], ['unknown', 'Aún no hay pronóstico para este día.']);
  const beyond = es(brief({date: '2026-10-20'}), forecast());
  assert.deepEqual([beyond.verdict, beyond.limit], ['unknown', 'El pronóstico aún no cubre este día.']);
  assert.equal(en(brief({date: '2026-10-20'}), forecast()).limit, 'The forecast does not reach this day yet.');
  const dark = es(brief(), forecast(), new Date('2026-10-14T02:30:00Z'));
  assert.deepEqual([dark.verdict, dark.limit], ['unknown', 'Ya no quedan horas de luz en este día.']);
  const blank = forecast({over: {wind_speed_10m: null, ecmwf_wind: null}});
  assert.deepEqual([es(brief(), blank).verdict, es(brief(), blank).limit], ['unknown', 'No hay pronóstico de viento y mar para esta ventana.']);
  const at = h => `2026-10-13T${String(h + 7).padStart(2, '0')}:00:00Z`;
  const unknownHours = [8, 9, 10, 11].map(h => ({at: at(h), verdict: 'Unknown', reasons: ['Wind unknown']}));
  const prof = profileVerdict(brief({profile: 'kayak', kayak: {hours: unknownHours}}), NOW, TZ, 'es');
  assert.deepEqual([prof.verdict, prof.limit], ['unknown', 'Se desconocen el viento o el mar para esta ventana.']);
  assert.deepEqual([profileVerdict(brief({profile: 'shore', shore: null}), NOW, TZ, 'es').verdict, profileVerdict(brief({profile: 'shore', shore: null}), NOW, TZ, 'es').limit], ['unknown', 'Aún no hay pronóstico para este día.']);
  // the afternoon window ends at the sunset hour and is said on the 24-hour clock, never as pm
  const afternoon = es(brief(), forecast(), new Date('2026-10-13T20:30:00Z'));
  assert.equal(afternoon.limit, 'Viento de hasta 6 kt y mar de hasta 2,5 ft hasta las 18.');
  assert.equal(en(brief(), forecast(), new Date('2026-10-13T20:30:00Z')).limit, 'Wind to 6 kt and seas to 2.5 ft through 6 pm.');
  // the clock follows the region's zone and its daylight-saving change, in both languages
  const c = lang => (ms, tz) => verdictCopy(lang).clock(Date.parse(ms), tz);
  assert.deepEqual(['2026-11-01T08:00:00Z', '2026-11-01T09:00:00Z', '2026-11-01T10:00:00Z'].map(ms => c('es')(ms, TZ)), ['1', '1', '2']);
  assert.deepEqual(['2026-11-01T08:00:00Z', '2026-11-01T09:00:00Z', '2026-11-01T10:00:00Z'].map(ms => c('en')(ms, TZ)), ['1 am', '1 am', '2 am']);
  assert.equal(c('es')('2026-11-01T10:00:00Z', 'America/New_York'), '5');
  assert.equal(c('es')('2026-11-01T20:00:00Z', TZ), '12', 'noon is 12, not "noon"'); assert.equal(c('en')('2026-11-01T20:00:00Z', TZ), 'noon');
  assert.equal(c('es')('2026-11-02T00:00:00Z', 'America/New_York'), '19'); assert.doesNotMatch(c('es')('2026-11-02T00:00:00Z', 'America/New_York'), /pm|am/);
  // the long-period hour helper keeps its English default and a Spanish form
  const rows = [{ms: hourAt(8) * 1000, hour: {sea: 5, other_sea: null, sea_period: 16, swell_period: null}}];
  assert.equal(longPeriodHour(rows, TZ), 'long-period swell (5 ft at 16 s) at 8 am');
  assert.equal(longPeriodHour(rows, TZ, 'es'), 'mar de fondo de período largo (5 ft a 16 s) a las 8');
  assert.equal(briefVerdict(null, forecast(), NOW, TZ, undefined, 'es'), null);
});

/** Every reason the three graders can write, from their real functions over synthetic bands. */
function producerReasons() {
  const out = new Set();
  const sides = [null, 'onshore', 'offshore', 'cross-shore'];
  for (const band of ['Small', 'Moderate', 'Large', 'Heavy']) for (const [heightFt, periodS, basis] of [[5.5, 9, 'nearshore'], [4, null, 'offshore'], [null, null, null]]) for (const sneaker of [false, true])
    for (const wband of ['Light', 'Breezy', 'Strong']) for (const side of sides) for (const phase of ['rising', 'falling', 'high', 'low', null]) for (const twilight of [false, true]) {
      const surf = {band, heightFt, periodS, basis, longPeriodS: 18, sneaker, sneakerScore: 1};
      for (const r of shoreVerdict(surf, {band: wband, side}, {phase, heightFt: 2, veryLow: false, bonus: false}, twilight).reasons) out.add(r);
    }
  for (const r of shoreVerdict({band: 'Unknown', heightFt: null, periodS: null, basis: null, longPeriodS: null, sneaker: false, sneakerScore: 0}, {band: 'Unknown', side: null}, {phase: null, heightFt: null, veryLow: false, bonus: false}, false).reasons) out.add(r);
  for (const wband of ['Light', 'Moderate', 'Fresh', 'Strong']) for (const side of sides) for (const [windKnots, gustKnots] of [[12, 18], [12, null]]) for (const sband of ['Small', 'Moderate', 'Large', 'Heavy'])
    for (const [heightFt, periodS] of [[3.5, 8], [3, null]]) for (const chop of [false, true]) for (const fog of [false, true]) for (const daylight of [true, false]) for (const lb of ['Small', 'Large']) {
      const launch = {band: lb, heightFt: 2, periodS: 8, basis: lb === 'Large' ? 'offshore' : 'nearshore', longPeriodS: null, sneaker: false, sneakerScore: 0};
      for (const r of kayakVerdict({band: wband, side, windKnots, gustKnots}, {band: sband, heightFt, periodS, chop}, launch, daylight, fog).reasons) out.add(r);
    }
  const calmLaunch = {band: 'Small', heightFt: 0, periodS: null, basis: null, longPeriodS: null, sneaker: false, sneakerScore: 0};
  for (const r of [...kayakVerdict({band: 'Unknown', side: null, windKnots: null, gustKnots: null}, {band: 'Unknown', heightFt: null, periodS: null, chop: false}, calmLaunch, null, false).reasons]) out.add(r);
  for (const sb of ['Low', 'Moderate', 'Strong', 'Heavy']) for (const basis of ['nearshore', 'offshore']) for (const cb of ['Light', 'Choppy', 'Rough']) for (const kb of ['Likely good', 'Fair', 'Likely poor', 'Unknown']) for (const highTide of [false, true])
    for (const r of spearVerdict({band: sb, energy: 3, heightFt: 2, periodS: 8, basis}, {band: cb, windKnots: 5, gustKnots: 8}, {band: kb, drivers: [], missing: [], gaps: []}, highTide).reasons) out.add(r);
  for (const r of spearVerdict({band: 'Unknown', energy: null, heightFt: null, periodS: null, basis: null}, {band: 'Unknown', windKnots: null, gustKnots: null}, {band: 'Unknown', drivers: [], missing: [], gaps: []}, false).reasons) out.add(r);
  return [...out];
}

test('verdict_es_profile_reason_matrix: every reason the Shore, Kayak and Spear graders write has a Spanish form, with its numbers, and never falls back', () => {
  const copy = verdictCopy('es'), reasons = producerReasons();
  assert.ok(reasons.length >= 80, `the matrix reaches the producers' reasons (${reasons.length})`);
  const fallback = t('verdict.reason.fallback', 'es', {reason: ''});
  for (const r of reasons) {
    const s = copy.profileReason(r);
    assert.ok(!s.startsWith(fallback), `"${r}" has a Spanish form`);
    assert.deepEqual(numbers(s), numbers(r), `"${r}" -> "${s}": same numbers`);
    assert.doesNotMatch(s, /\b(?:wind|seas?|surf|surge|chop|tide|swell|clarity|daylight|launch|fog|offshore|onshore|estimate|unknown|dawn|dusk|gust|period|likely|fair)\b/i, `"${r}" -> "${s}": no English left`);
    assert.equal(verdictCopy('en').profileReason(r), r, 'English is returned as the grader wrote it');
  }
  const exact = {
    'Large surf (7 ft at 9 s)': 'oleaje de rompiente grande (7 ft a 9 s)', 'Heavy surf (4.5 ft, offshore estimate)': 'oleaje de rompiente muy intenso (4,5 ft, estimación mar adentro)',
    'Small surf': 'oleaje de rompiente pequeño', 'light wind onshore': 'viento leve hacia tierra', 'strong wind cross-shore': 'viento fuerte paralelo a la costa',
    'breezy wind offshore': 'viento con brisa hacia mar adentro', 'fresh wind (18 kt, gust 25) onshore': 'viento fresco (18 kt, ráfagas de 25) hacia tierra', 'moderate wind (12 kt)': 'viento moderado (12 kt)',
    'heavy seas (9.5 ft at 8 s)': 'mar muy intenso (9,5 ft a 8 s)', 'small seas (1 ft)': 'mar pequeño (1 ft)', 'Strong surge (from offshore swell)': 'vaivén del agua fuerte (según el mar de fondo mar adentro)',
    'Low surge': 'vaivén del agua leve', 'rough chop': 'oleaje corto agitado', 'choppy chop': 'oleaje corto picado', 'clarity estimate likely poor': 'estimación de claridad probablemente mala',
    'clarity estimate fair': 'estimación de claridad regular', 'clarity estimate likely good': 'estimación de claridad probablemente buena', 'clarity unknown': 'claridad desconocida',
    'long-period swell': 'mar de fondo de período largo', 'short-period chop': 'oleaje corto de período breve', 'surf at the launch': 'rompiente en el punto de salida', 'fog alert': 'aviso de niebla',
    'outside daylight': 'fuera de las horas de luz', 'rising tide': 'marea subiendo', 'falling tide': 'marea bajando', 'high tide': 'marea alta', 'low tide': 'marea baja', 'around high tide': 'cerca de la marea alta',
    'near high tide': 'cerca de la marea alta', 'dawn or dusk': 'amanecer o atardecer', 'Surf height unknown': 'altura de la rompiente desconocida', 'Wind unknown': 'viento desconocido', 'Seas unknown': 'mar desconocido',
    'Swell height or period unknown': 'altura o período del mar de fondo desconocidos',
  };
  for (const [from, want] of Object.entries(exact)) assert.equal(copy.profileReason(from), want, from);
  // an unrecognised or custom reason keeps the model's words, flagged, never a calm substitute; a known noun with an unknown band is not invented either
  assert.equal(copy.profileReason('sea state uncertain'), 'Razón del modelo no disponible en español: sea state uncertain');
  assert.equal(copy.profileReason('Gigantic surf (30 ft)'), 'Razón del modelo no disponible en español: Gigantic surf (30 ft)');
  assert.equal(copy.profileReason(''), 'Razón del modelo no disponible en español: ');
});

test('verdict_es_profile_dominance_and_severity: the reasons that decide a graded hour are chosen from the English, then translated; fog, darkness, launch surf and long-period swell keep their place', () => {
  const at = h => `2026-10-13T${String(h + 7).padStart(2, '0')}:00:00Z`;
  const day = (verdict, reasons, profile = 'kayak') => brief({profile, [profile]: {hours: [8, 9, 10, 11].map(h => ({at: at(h), verdict, reasons}))}});
  const same = (b) => { const a = profileVerdict(b, NOW, TZ), s = profileVerdict(b, NOW, TZ, 'es'); assert.deepEqual([s.verdict, s.score, s.window, s.basis, s.held], [a.verdict, a.score, a.window, a.basis, a.held], 'the language changes no decision'); return [a, s]; };
  let [a, s] = same(day('Rough', ['light wind (4 kt) onshore', 'small seas (1 ft)', 'fog alert']));
  assert.deepEqual([a.verdict, a.limit, s.limit], ['rough', 'Fog alert at 8 am.', 'Aviso de niebla a las 8.']);
  [a, s] = same(day('Rough', ['light wind (4 kt) onshore', 'small seas (1 ft)', 'outside daylight']));
  assert.equal(s.limit, 'Fuera de las horas de luz a las 8.');
  [a, s] = same(day('Marginal', ['light wind (4 kt) onshore', 'small seas (1 ft)', 'surf at the launch']));
  assert.deepEqual([a.limit, s.limit], ['Surf at the launch at 8 am.', 'Rompiente en el punto de salida a las 8.']);
  [a, s] = same(day('Rough', ['strong wind (25 kt, gust 31) onshore', 'heavy seas (9 ft at 8 s)', 'short-period chop']));
  assert.deepEqual([a.limit, s.limit], ['Strong wind (25 kt, gust 31) onshore, heavy seas (9 ft at 8 s) at 8 am.', 'Viento fuerte (25 kt, ráfagas de 31) hacia tierra, mar muy intenso (9 ft a 8 s) a las 8.']);
  [a, s] = same(day('Marginal', ['Moderate surf (3 ft at 9 s)', 'long-period swell', 'light wind onshore'], 'shore'));
  assert.match(s.limit, /^Oleaje de rompiente moderado \(3 ft a 9 s\)/);
  [a, s] = same(day('Calmer', ['Small surf', 'light wind offshore'], 'shore'));
  assert.deepEqual([a.verdict, a.limit, s.limit], ['comfortable', 'Small surf, light wind offshore through noon.', 'Oleaje de rompiente pequeño, viento leve hacia mar adentro hasta las 12.']);
  [a, s] = same(day('Rough', ['sea state uncertain'], 'spear'));
  assert.equal(s.limit, 'Razón del modelo no disponible en español: sea state uncertain a las 8.');
  assert.equal(s.verdict, 'rough', 'an unknown reason keeps the day Rough');
  // an active alert on a profile day: Rough, event verbatim, the reason after it in Spanish
  const alerted = profileVerdict({...day('Calmer', ['light wind']), alerts: [{event: 'Gale Warning'}]}, NOW, TZ, 'es');
  assert.deepEqual([alerted.verdict, alerted.limit], ['rough', 'Gale Warning en vigor. Viento leve a las 8.']);
  // a graded hour with no reason left reads the grade word in the page's language
  assert.equal(profileVerdict(day('Rough', []), NOW, TZ, 'es').limit, 'Agitado a las 8.');
  assert.equal(profileVerdict(day('Rough', []), NOW, TZ).limit, 'Rough at 8 am.');
});

test('verdict_es_catalogue: every verdict id has both languages with the same variables, and the English templates are the old literals', () => {
  const ids = Object.keys(catalogue.strings).filter(k => k.startsWith('verdict.'));
  assert.ok(ids.length >= 70, `the verdict ids are in the catalogue (${ids.length})`);
  const vars = text => [...new Set([...text.matchAll(/\{(\w+)\}/g)].map(m => m[1]))].sort();
  for (const id of ids) { const e = catalogue.strings[id]; assert.ok(e.en && e.es?.trim(), `${id} has en and es`); assert.deepEqual(vars(e.en), vars(e.es), `${id}: same variables`); }
  // a hold or a limit never leaves a placeholder unfilled in either language
  for (const lang of ['en', 'es']) {
    const f = forecast({drop: ['ecmwf_ifs025', 'ecmwf_wam'], runAgeH: 20, over: {wave_height: 5, wam: 5, wave_period: 16, swell_wave_period: 16}});
    const v = boatVerdict(brief({missing: [ALERT_CHECK_MISSING], bar: {hazardous: [{at: '2026-10-13T16:00:00Z'}]}}), f, NOW, TZ, undefined, lang);
    assert.doesNotMatch(`${v.limit} ${v.held}`, /[{}]/, lang);
  }
});
