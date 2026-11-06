// SC0707-11: the Conditions and History views in Spanish. Everything runs the production views and the
// real packages/coast renderers on synthetic data; English output is pinned to hashes taken from main
// before this change (GOLDEN), so "byte-identical English" is a checked fact, not a claim.
import test from 'node:test';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {existsSync, readFileSync} from 'node:fs';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {rendererPlugins} from './helpers/esbuild-url.mjs';
import fixture from './fixtures/coast/history.json' with {type: 'json'};

const ROOT = new URL('..', import.meta.url).pathname;
const HAS_COPY = existsSync(join(ROOT, 'web/view-copy.ts'));
const out = join(await mkdtemp(join(tmpdir(), 'cond-hist-i18n-')), 'bundle.mjs');
await build({
  stdin: {resolveDir: ROOT, loader: 'ts', contents: `
    export {Conditions} from './web/app/views/Conditions.tsx';
    export {HourlyTable} from './web/app/views/HourlyTable.tsx';
    export {History} from './web/app/views/History.tsx';
    export {historyView} from './packages/coast/src/ui/history.ts';
    export {chart} from './packages/coast/src/charts/series.ts';
    export {regionalForecast} from './web/brief/Brief.tsx';
    export {region, profile} from './web/state.ts';
    export {language} from './web/i18n.ts';
    export {dayWord, sentence} from './web/model-disagreement.ts';
    ${HAS_COPY ? `export {coastCopy, historyCopy, conditionsCopy} from './web/view-copy.ts'; export {COAST_COPY_KEYS} from './packages/coast/src/ui/copy.ts';` : ''}
    export {render} from 'preact-render-to-string';
    export {h} from 'preact';`},
  bundle: true, format: 'esm', platform: 'node', outfile: out, write: true, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact', plugins: rendererPlugins,
});
const v = await import(pathToFileURL(out).href);
const sha = text => createHash('sha256').update(text).digest('hex');

const TZ = 'America/Los_Angeles', HOUR = 3600;
const NOW = new Date('2026-10-13T12:00:00Z');
const COUNTY = {id: 'slo', timezone: 'UTC'};
const county = {id: 'slo', timezone: 'America/Los_Angeles'};

// ---- synthetic data
const pdt = (date, h) => Date.parse(`${date}T${String(h + 7).padStart(2, '0')}:00:00Z`) / 1000;
function forecast({ecmwfWind = () => 10} = {}) {
  const start = Date.parse('2026-10-13T07:00:00Z') / 1000, times = Array.from({length: 120}, (_, i) => start + i * HOUR);
  const series = cols => ({utc_offset_seconds: 0, hourly_units: {time: 'unixtime', ...Object.fromEntries(cols.map(([k, u]) => [k, u]))}, hourly: {time: times, ...Object.fromEntries(cols.map(([k, , f]) => [k, times.map(f)]))}});
  const run = (id, cols) => ({id, issued: NOW.getTime() / 1000 - 4 * HOUR, end: times.at(-1), data: series(cols)});
  return {region: 'morro-bay', retrieved: NOW.getTime(), point: {id: 'morro-bay', lat: 35.37, lon: -120.9}, models: {
    gfs_global: run('gfs_global', [['wind_speed_10m', 'kn', () => 10], ['wind_gusts_10m', 'kn', () => 13], ['wind_direction_10m', '°', () => 300]]),
    ncep_gfswave016: run('ncep_gfswave016', [['wave_height', 'ft', () => 3.4], ['wave_period', 's', () => 10]]),
    ecmwf_ifs025: run('ecmwf_ifs025', [['wind_speed_10m', 'kn', ecmwfWind], ['wind_gusts_10m', 'kn', t => ecmwfWind(t) + 3]]),
    ecmwf_wam: run('ecmwf_wam', [['wave_height', 'ft', () => 3.4]]),
  }};
}
const disagreeing = () => forecast({ecmwfWind: t => (t === pdt('2026-10-14', 7) || t === pdt('2026-10-14', 8)) ? 20 : 10});
function hourlyForecast(t0) {
  const WIND = {wind_speed_10m: [8, 'kn'], wind_gusts_10m: [12, 'kn'], wind_direction_10m: [300, '°'], visibility: [16093, 'm']};
  const WAVE = {wave_height: [4.2, 'ft'], wave_period: [11, 's'], wind_wave_height: [1.5, 'ft'], wind_wave_period: [5, 's'], swell_wave_height: [3.1, 'ft'], swell_wave_period: [14, 's'], swell_wave_direction: [290, '°']};
  const time = Array.from({length: 72}, (_, i) => t0 + i * HOUR);
  const series = values => ({utc_offset_seconds: 0, hourly_units: {time: 'unixtime', ...Object.fromEntries(Object.entries(values).map(([k, [, u]]) => [k, u]))}, hourly: {time, ...Object.fromEntries(Object.entries(values).map(([k, [x]]) => [k, time.map(() => x)]))}});
  const run = (id, values) => ({id, issued: t0 - 6 * HOUR, end: t0 + 72 * HOUR, data: series(values)});
  return {region: 'morro-bay', retrieved: t0 * 1000, point: {id: 'central', lat: 35.36, lon: -120.94}, models: {gfs_global: run('gfs_global', WIND), ncep_gfswave016: run('ncep_gfswave016', WAVE), ecmwf_ifs025: run('ecmwf_ifs025', {...WIND, wind_speed_10m: [10, 'kn']}), ecmwf_wam: run('ecmwf_wam', WAVE)}};
}
const FALL = Date.parse('2026-10-31T07:00:00Z') / 1000, FALL_NOW = new Date((FALL + 2 * HOUR) * 1000);
const FALL_AT = Date.parse('2026-11-01T10:00:00Z');
const bundle = structuredClone(fixture);
const NOW_H = new Date('2026-10-07T15:10:00Z');
const hist = (b, metric = 'waterTempF', days = 45, copy) => v.historyView({county, now: NOW_H}, b, {station: '', metric, days}, copy);
const METRICS = ['waterTempF', 'waveFt', 'windKnots', 'airTempF', 'gustKnots', 'periodS'];
const SERIES = [
  {label: 'Wind', unit: 'kt', color: 'var(--coast-mint)', points: [0, 1, 2, 3].map(i => ({at: new Date(Date.parse('2026-10-13T12:00:00Z') + i * 3600000).toISOString(), value: 5 + i * 1.5}))},
  {label: 'Cloud', unit: '%', color: 'var(--coast-muted)', points: [], min: 0, max: 100},
];
const chartEn = (copy) => v.chart(SERIES, '2026-10-13T12:00:00Z', '2026-10-13T20:00:00Z', '2026-10-13T14:00:00Z', 'America/Los_Angeles', copy ? {copy} : {});

function renderConditions(lang) {
  v.language.value = lang; v.region.value = 'morro-bay'; v.regionalForecast.value = disagreeing();
  const html = v.render(v.h(v.Conditions, {now: NOW}));
  v.region.value = null; v.regionalForecast.value = null; v.language.value = 'en';
  return html;
}
const renderHourly = lang => { v.language.value = lang; const html = v.render(v.h(v.HourlyTable, {forecast: hourlyForecast(FALL), tide: null, at: FALL_AT, tz: TZ, now: FALL_NOW})); v.language.value = 'en'; return html; };
const renderHistory = lang => { v.language.value = lang; const html = v.render(v.h(v.History, {now: NOW_H})); v.language.value = 'en'; return html; };
const strip = html => html.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ');
const attrs = (html, name) => [...html.matchAll(new RegExp(`\\s${name}="([^"]*)"`, 'g'))].map(m => m[1]);

const snapshot = () => ({
  history: sha(METRICS.flatMap(m => [7, 14, 45].map(d => hist(bundle, m, d))).join('\n')),
  chart: sha(chartEn()),
  conditions: sha(renderConditions('en')),
  hourly: sha(renderHourly('en')),
});
// Hashes of main's English output (c8f1bec0) for exactly the calls above.
const GOLDEN = {
  history: '58a889e1e1f29b3d5eb99edc80853c4168885f98f7688549919e408c11db18ba', chart: '753164a97209761c2cdcc5afb6952cbefeeaa1042f39e0c08109043dbc0064b1', conditions: 'b91c3b15a92e0ec9d8fbbab1866f82cf4b359c8d26ca6c0176edbc1ac95278f6', hourly: '2b06a9ded393bae0a73476cfb36d54f65ea87fa6980443e4e2055f4997ef8912',
};
if (process.env.PRINT_GOLDEN) { console.log(JSON.stringify(snapshot())); process.exit(0); }

test('english output is byte-identical to main for the History renderer, the chart, the Conditions view and the hourly table', () => {
  assert.deepEqual(snapshot(), GOLDEN);
  assert.equal(hist(bundle, 'waveFt', 14, undefined), hist(bundle, 'waveFt', 14), 'no copy is the original English path');
});

test('disagreement_full_templates_preserve_values: one complete Spanish template per day class and quantity, same numbers', () => {
  const item = (date, quantity, noaa, ecmwf) => ({date, quantity, noaa, ecmwf, hours: 3});
  const es = (d, lang = 'es', now = NOW) => v.sentence(d, now, TZ, lang);
  assert.equal(es(item('2026-10-13', 'wind', 8, 17)), 'Los modelos discrepan sobre el viento de esta mañana: 8 kt (NOAA) frente a 17 kt (ECMWF). La puntuación usa el modelo más adverso.');
  assert.equal(es(item('2026-10-14', 'seas', 3.04, 5.46)), 'Los modelos discrepan sobre el oleaje de mañana por la mañana: 3 ft (NOAA) frente a 5,5 ft (ECMWF). La puntuación usa el modelo más adverso.');
  assert.equal(es(item('2026-10-15', 'wind', 8, 17)), 'Los modelos discrepan sobre el viento del jueves por la mañana: 8 kt (NOAA) frente a 17 kt (ECMWF). La puntuación usa el modelo más adverso.');
  assert.equal(es(item('2026-10-15', 'seas', 2, 4)), 'Los modelos discrepan sobre el oleaje del jueves por la mañana: 2 ft (NOAA) frente a 4 ft (ECMWF). La puntuación usa el modelo más adverso.');
  assert.equal(es(item('2026-10-13', 'seas', 3, 5.46)), 'Los modelos discrepan sobre el oleaje de esta mañana: 3 ft (NOAA) frente a 5,5 ft (ECMWF). La puntuación usa el modelo más adverso.');
  assert.equal(es(item('2026-10-14', 'wind', 4.6, 10.4)), 'Los modelos discrepan sobre el viento de mañana por la mañana: 5 kt (NOAA) frente a 10 kt (ECMWF). La puntuación usa el modelo más adverso.');
  // English: the same sentences as before, with and without the language argument.
  assert.equal(es(item('2026-10-15', 'wind', 8, 17), 'en'), 'Models disagree about Thursday morning: wind 8 kt (NOAA) vs 17 kt (ECMWF). The score uses the rougher.');
  assert.equal(v.sentence(item('2026-10-14', 'seas', 3.04, 5.46), NOW, TZ), 'Models disagree about tomorrow morning: seas 3 ft (NOAA) vs 5.5 ft (ECMWF). The score uses the rougher.');
  // The day class follows the dates, not the localized word: the evening before a November fall-back the 'next' day is still tomorrow.
  const dst = new Date('2026-11-01T06:30:00Z');   // 11:30 pm PDT on Oct 31
  assert.match(es(item('2026-11-01', 'wind', 8, 17), 'es', dst), /viento de mañana por la mañana: 8 kt/);
  assert.match(es(item('2026-11-02', 'wind', 8, 17), 'es', dst), /viento del lunes por la mañana/);
  assert.deepEqual(['2026-10-13', '2026-10-14', '2026-10-15'].map(d => v.dayWord(d, NOW, TZ, 'es')), ['hoy', 'mañana', 'jueves']);
  assert.deepEqual(['2026-10-13', '2026-10-14', '2026-10-15'].map(d => v.dayWord(d, NOW, TZ)), ['today', 'tomorrow', 'Thursday']);
});

test('conditions_en_es_en_roundtrip: Spanish chrome, row labels, caption, clocks and caveat; the numbers, clocks and paths stay', () => {
  const en = renderConditions('en'), es = renderConditions('es');
  for (const text of ['Condiciones', 'Modelo de pronóstico', 'aria-label="Diferencias entre modelos"', 'Hora seleccionada, ', 'aria-label="Gráfico de condiciones, se desplaza horizontalmente"',
    'Los modelos discrepan sobre el viento de mañana por la mañana: 10 kt (NOAA) frente a 20 kt (ECMWF). La puntuación usa el modelo más adverso.',
    '<dt class="ui-eyebrow">Viento</dt>', '<dt class="ui-eyebrow">Ráfagas</dt>', '<dt class="ui-eyebrow">Oleaje mar adentro</dt>', '<dt class="ui-eyebrow">Aire</dt>', '<dt class="ui-eyebrow">Nubes</dt>',
    'Arrastra el gráfico para cambiar la hora. Viento, ráfagas, oleaje mar adentro, aire y nubes: modelos NOAA en el punto de pronóstico morro-bay; el informe costero local no está disponible aquí. Escalas independientes por fila; los datos faltantes quedan en blanco; las horas sombreadas tienen menor exposición.',
    'Horas de las fuentes', 'Fuente regional de pronóstico', 'ejecución', 'recuperado', 'Eventos de marea', 'Antes de salir', 'Corriente superficial',
    'El mapa muestra la fuente elegida aquí o en la capa Corrientes.',
    'Hora por hora, ', 'Hora</th>', 'Viento (kt · desde)', 'Puntuación de comodidad (0–10)', 'Tabla hora por hora, desplazable'])
    assert.ok(es.includes(text), text);
  assert.ok(!/Conditions<|Source clocks|Before you go|Forecast model/.test(es), 'no English chrome is left');
  assert.ok(es.includes('Habitat') === false && es.includes('El hábitat describe un lugar donde buscar'), 'the boat caveat is the catalogue one');
  // Values, model names, clocks and chart geometry are the same in both languages.
  assert.deepEqual(es.match(/<dd class="ui-mono">[^<]*<\/dd>/g).map(x => x.replace(',', '.')), en.match(/<dd class="ui-mono">[^<]*<\/dd>/g));
  assert.ok(strip(es).includes('NOAA GFS-Wave ejecución') && es.includes('PDT') && !es.includes('GMT-7'), 'model names stay as published');
  assert.equal(renderConditions('en'), en, 'switching back gives the English markup again');
  assert.equal(sha(en), GOLDEN.conditions);
});

test('profile caveats: each profile reads its own Spanish sentence in the Conditions notes', () => {
  const want = {boat: 'El hábitat describe un lugar donde buscar; la presencia de peces no está verificada.', shore: 'El oleaje mar adentro no mide las rompientes de tu playa; revisa el oleaje, el acceso y la calidad del agua.',
    spear: 'La visibilidad bajo el agua no está verificada; las corrientes superficiales no pueden autorizar una inmersión.', kayak: 'El viento, la deriva mar adentro y el oleaje en el punto de salida determinan el día en kayak; un pronóstico no puede autorizar una salida a remo.'};
  for (const [name, text] of Object.entries(want)) {
    v.profile.value = name;
    assert.ok(renderConditions('es').includes(`<li>${text}</li>`), name);
    assert.ok(!renderConditions('en').includes(text), name);
  }
  v.profile.value = 'boat';
});

test('hourly_es_dst_and_missing: Spanish headers and notes; the repeated November hour keeps every row and both zone labels', () => {
  const en = renderHourly('en'), es = renderHourly('es');
  for (const text of ['Hora por hora, ', 'Tabla hora por hora, desplazable', '>Hora<', 'Viento (kt · desde)', 'Ráfaga (kt)', 'Oleaje (ft)', 'Mar de fondo (ft · s · desde)', 'Segundo mar de fondo (ft · desde)', 'Olas de viento (ft · s)',
    'Marea (donde hay informe local)', 'Visibilidad (mi)', 'Puntuación de comodidad (0–10)', '8 kt desde WNW', '4,2 ft', '3,1 ft · 14 s · 290°']) assert.ok(es.includes(text), text);
  assert.equal((es.match(/data-at=/g) ?? []).length, 25);
  assert.deepEqual(attrs(es, 'data-at'), attrs(en, 'data-at'));
  assert.equal((es.match(/aria-current="true"/g) ?? []).length, 1);
  for (const html of [en, es]) assert.ok(html.includes('PST') && html.includes('PDT'), 'the repeated hour names its zone');
  assert.equal(sha(en), GOLDEN.hourly);
  // No forecast: the empty line, in both languages.
  v.language.value = 'es';
  const none = v.render(v.h(v.HourlyTable, {forecast: null, tide: null, at: FALL_AT, tz: TZ, now: FALL_NOW}));
  v.language.value = 'en';
  assert.ok(none.includes('No hay pronóstico para este día.'));
  assert.ok(v.render(v.h(v.HourlyTable, {forecast: null, tide: null, at: FALL_AT, tz: TZ, now: FALL_NOW})).includes('No forecast for this day.'));
});

test('history_es_real_renderer_and_empty: the real historyView says it in Spanish and keeps every number and path', () => {
  const copy = v.historyCopy('es');
  for (const metric of METRICS) for (const days of [7, 14, 45]) {
    const en = hist(bundle, metric, days), es = hist(bundle, metric, days, copy);
    assert.deepEqual(attrs(es, 'd'), attrs(en, 'd'), `${metric} ${days} path`);
    assert.deepEqual(attrs(es, 'data-history-days'), attrs(en, 'data-history-days'));
    assert.deepEqual(attrs(es, 'value'), attrs(en, 'value'));
    assert.deepEqual(attrs(es, 'y1'), attrs(en, 'y1'));
    assert.ok(es.includes(`data-history-days="${days}" class="active"`) && es.includes(`>${days} días</button>`));
  }
  const seasoned = structuredClone(bundle);
  for (const st of seasoned.stations) st.baseline.months.push({month: 10, metric: 'waveFt', unit: 'ft', count: 1234, rawSampleCount: 2345, expectedHours: 3000, coverageFraction: 0.5, yearsWithData: [2025, 2026], p10: 1, median: 2.5, p90: 3, min: 1, max: 3, mean: 2});
  const es = hist(seasoned, 'waveFt', 14, copy);
  assert.ok(es.includes('2 años contribuyentes · 1.234 horas · 50,0% de cobertura') && es.includes('octubre UTC, altura de ola: 1.234 horas observadas de 3.000 horas del calendario; 2.345 muestras originales válidas. Percentil 10 / mediana / percentil 90: 1,0 / 2,5 / 3,0 ft.') && es.includes('Años contribuyentes: 2025, 2026.'));
  assert.ok(hist(seasoned, 'waveFt', 14).includes('2 contributing years · 1,234 hours · 50.0% coverage'), 'English keeps its grouping and precision');
  for (const text of ['HISTORIAL OCEÁNICO REGISTRADO', 'Conoce el patrón. Observa el cambio.', 'Synthetic buoy · mediciones registradas de boya y contexto estacional.', 'archivos anuales indexados', 'Estación', 'Medición',
    'Altura de ola', 'aria-label="Intervalo del historial"', 'Último promedio horario', 'Promedio de 14 días', 'intervalos horarios', 'de cobertura de la medición', 'Mediana registrada de octubre UTC', 'Frente a la mediana de ese mes', 'no es un pronóstico',
    '· promedios horarios · America/Los_Angeles', 'aria-label="Gráfico desplazable de observaciones registradas"', 'Desplázate horizontalmente para explorar todo el gráfico.', 'Observaciones horarias', 'Las mediciones faltantes quedan como huecos',
    'EL CONTEXTO ESTACIONAL', 'Lo que esta boya ha registrado.', 'Mediana · la banda es el percentil 10–90', 'Meses UTC · la cobertura varía', 'Estas distribuciones describen promedios horarios UTC registrados', 'Cobertura de referencia y años contribuyentes',
    'Percentil 10 / mediana / percentil 90', 'Años contribuyentes:', 'Último informe de la fuente:', 'Registro original de NOAA', 'La posición actual de la estación es una referencia;', 'Las mediciones de boyas en superficie no describen la temperatura del fondo ni las rompientes exactas de la playa.',
    'Altura de ola, últimos 14 días, ft. Las observaciones faltantes quedan como huecos.', 'registrada por mes UTC, mediana y percentiles 10 a 90, ft.', '>ENE<', '>DIC<'])
    assert.ok(es.includes(text), text);
  assert.ok(!/Know the pattern|RECORDED OCEAN|Scroll sideways|>JAN<|days<\/button>/.test(es), 'no English is left');
  assert.ok(hist(bundle, 'gustKnots', 7, copy).includes('Los promedios horarios de ráfagas no son la peor ráfaga de cada hora.'));
  assert.ok(hist(bundle, 'periodS', 7, copy).includes('Los promedios horarios del período dominante no son una distribución espectral de olas.'));
  // Empty states.
  assert.ok(v.historyView({county, now: NOW_H}, null, {station: '', metric: 'waveFt', days: 7}, copy).includes('Una perspectiva más amplia de la costa.'));
  assert.ok(v.historyView({county: {...county, id: 'other'}, now: NOW_H}, bundle, {station: '', metric: 'waveFt', days: 7}, copy).includes('Las observaciones históricas no están disponibles para este condado.'));
  const bare = structuredClone(bundle);
  for (const st of bare.stations) { for (const h of st.recent.hours) h.windKnots = null; st.baseline.months = st.baseline.months.filter(m => m.metric !== 'windKnots'); }
  const none = hist(bare, 'windKnots', 7, copy);
  for (const text of ['Esta estación no tiene mediciones válidas de viento en el registro recopilado. Elige otra medición o estación.', 'No hay observaciones válidas de viento en este intervalo.', 'No hay una referencia anual válida para esta medición.',
    'Sin medición', 'Sin comparación válida', 'No hay una referencia mensual válida para esta medición.', 'ninguno', ' · no disponible aquí']) assert.ok(none.includes(text), text);
  assert.ok(hist(bare, 'windKnots', 7).includes('This station has no supported wind measurements'), 'English unchanged');
});

test('history_es_preserves_evidence_and_navigation: wrapper states, escaping once, unchanged controls', () => {
  const unbound = renderHistory('es');
  assert.ok(unbound.includes('<h2 id="app-history-title">Historial registrado</h2>') && unbound.includes('El historial registrado no está disponible para esta región. SkipperCast recopila el historial de boyas solo donde un informe costero local cubre el área (actualmente Morro Bay y Cambria).'));
  assert.ok(renderHistory('en').includes('Recorded history is unavailable for this region.'));
  const hostile = structuredClone(bundle);
  hostile.stations[0].name = '<img src=x onerror=alert(1)> & "q"';
  const es = hist(hostile, 'waveFt', 14, v.historyCopy('es'));
  assert.ok(!es.includes('<img') && es.includes('&lt;img src=x onerror=alert(1)&gt; &amp; &quot;q&quot; · mediciones registradas de boya'), 'a station name is escaped once, in the translated template too');
  // A copy that returns markup cannot inject it.
  const evil = {text: () => '<b onclick=x>', time: (a, t, o) => '<i>', number: n => String(n), age: () => '<u>'};
  const html = hist(bundle, 'waveFt', 14, evil);
  assert.ok(!/<b onclick|<i>|<u>/.test(html), 'supplied copy is escaped, never raw HTML');
  // The numbers come from the data, not the copy.
  assert.deepEqual(attrs(hist(bundle, 'waveFt', 14, evil), 'd'), attrs(hist(bundle, 'waveFt', 14), 'd'));
});

test('shared_renderers_optional_copy_isolation: chart text, axes and gaps in Spanish only when the host supplies copy', () => {
  const copy = v.coastCopy('es');
  assert.equal(v.coastCopy('en'), undefined, 'English leaves the renderers on their own text');
  const es = chartEn(copy), en = chartEn();
  assert.ok(es.includes('Wind en kt, Cloud en %. Escalas independientes por fila; los datos faltantes quedan en blanco.') && es.includes('No hay muestras válidas'));
  assert.ok(en.includes('Wind in kt, Cloud in %. Independent row scales; gaps remain blank.') && en.includes('No supported samples'));
  assert.deepEqual(attrs(es, 'd'), attrs(en, 'd'));
  assert.equal(sha(en), GOLDEN.chart);
  assert.deepEqual(es.match(/class="axis">[^<]*<\/text>/g).filter(x => /\d/.test(x)).length, en.match(/class="axis">[^<]*<\/text>/g).filter(x => /\d/.test(x)).length);
  assert.notEqual(es.match(/class="axis">[^<]*<\/text>/g)[0], en.match(/class="axis">[^<]*<\/text>/g)[0], 'the time axis follows the language');
});

test('every renderer copy key has en and es with the same placeholders; a missing key is refused', () => {
  const strings = JSON.parse(readFileSync(join(ROOT, 'catalog/app/strings.json'), 'utf8')).strings;
  const holes = s => [...s.matchAll(/\{(\w+)\}/g)].map(m => m[1]).sort().join(',');
  for (const key of v.COAST_COPY_KEYS) {
    assert.ok(Object.hasOwn(strings, key), `${key} is in the catalogue`);
    assert.ok(strings[key].es?.trim(), `${key} has es`);
    assert.equal(holes(strings[key].es), holes(strings[key].en), `${key} placeholders`);
  }
  for (const [id, e] of Object.entries(strings)) if (/^(conditions|disagree|hourly|history|chart)\./.test(id)) assert.equal(holes(e.es), holes(e.en), `${id} placeholders`);
  assert.throws(() => v.coastCopy('es').text('history.not-a-key'), /unknown string id/);
  assert.equal(v.coastCopy('es').age('2026-10-07T14:00:00Z', new Date('2026-10-07T14:00:30Z')), 'ahora mismo');
  assert.equal(v.coastCopy('es').age('2026-10-07T12:00:00Z', new Date('2026-10-07T14:10:00Z')), 'hace 2 h');
  assert.equal(v.coastCopy('es').age('2026-10-07T15:00:00Z', new Date('2026-10-07T14:00:00Z')), 'hora no disponible');
  assert.equal(v.coastCopy('es').time('nope', 'UTC', {}), 'No disponible');
});
