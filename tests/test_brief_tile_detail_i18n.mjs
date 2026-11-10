// SC1137-02: the brief tiles' detail line and the source-gap sentences read the reader's language.
// The model keeps its English `.detail` / gap `.text`; `display` metadata is the same branches as finite parts,
// and web/brief/tile-copy.ts says them from the catalogue. Published names are never translated.
import './helpers/spanish-ready.mjs';   // SC1407-09: the Spanish table, before the Spanish renders
import test from 'node:test';
import assert from 'node:assert/strict';
import report from './fixtures/coast/skippercast-report.json' with {type: 'json'};
import montereyDaily from './fixtures/brief/monterey-daily.json' with {type: 'json'};
import montereyForecast from './fixtures/brief/monterey-forecast.json' with {type: 'json'};
import {COVERED} from '../scripts/check_copy.mjs';
import {STRINGS} from '../web/i18n.ts';

const {PROFILES} = await import('../web/profile.ts');
const {slo} = await import('../packages/coast/src/counties.ts');
const {buildCoastBrief, buildRegionalBrief, sourceGaps, reportGaps} = await import('../web/brief/model.ts');
const {withTideSelection} = await import('../web/tide-stations.ts');
const {partText, tileDetailText, sourceGapText, tideEmptyText, tileSourceName} = await import('../web/brief/tile-copy.ts');
const {TIDE_UNAVAILABLE, TIDE_NO_CURVE} = await import('../web/tides.ts');

const now = new Date(Date.parse(report.generatedAt) + 10 * 60_000);
const date = '2026-10-08';
const place = {id: 'monterey', name: 'Monterey', lat: 36.62, lon: -121.9, timezone: 'America/Los_Angeles', port: 'Monterey'};
const regional = {daily: montereyDaily, forecast: montereyForecast, place};
const join = (tile, lang) => tile.display.parts.map(p => partText(p, lang)).filter(Boolean).join(' · ');
const briefs = () => PROFILES.flatMap(profile => [buildCoastBrief({report, county: slo, areaId: 'central', profile, date, now}), buildRegionalBrief({...regional, profile, date, now})]);

test('detail_all_profiles_en_es_en: every real tile carries display parts that rebuild its English detail; English adapter returns the model line', () => {
  for (const brief of briefs()) for (const tile of brief.tiles) {
    assert.ok(tile.display, `${brief.profile}/${brief.basis}/${tile.id} has display metadata`);
    assert.equal(join(tile, 'en'), tile.detail, `${brief.profile}/${brief.basis}/${tile.id} parts say the English detail`);
    assert.equal(tileDetailText(tile), tile.detail);
    assert.equal(tileDetailText(tile, 'en'), tile.detail);
    const es = tileDetailText(tile, 'es');
    assert.equal(es, join(tile, 'es'));
    assert.equal(tileDetailText(tile, 'en'), tile.detail, 'English again after Spanish');
  }
});

test('detail_all_profiles_en_es_en: Spanish lines for the fixture tiles, names as published', () => {
  const boat = buildCoastBrief({report, county: slo, areaId: 'central', profile: 'boat', date, now});
  const swell = boat.tiles.find(t => t.id === 'swell'), water = boat.tiles.find(t => t.id === 'water'), tide = boat.tiles.find(t => t.id === 'tide'), wind = boat.tiles.find(t => t.id === 'wind');
  assert.match(tileDetailText(swell, 'es'), /pronóstico mar adentro$/);
  assert.equal(tileDetailText(water, 'es'), water.detail.replace('buoy', 'boya'));
  assert.ok(tileDetailText(wind, 'es').startsWith('ráfaga '));
  assert.ok(tileDetailText(tide, 'es').endsWith(`${slo.tideStation.name} · MLLW`), 'station and datum stay as published');
  const shore = buildRegionalBrief({...regional, profile: 'shore', date, now}).tiles.find(t => t.id === 'swell');
  assert.equal(shore.detail, 'No nearshore model site · moderate surf (offshore estimate)');
  assert.equal(tileDetailText(shore, 'es'), 'No hay sitio de modelo cercano a la costa · oleaje en la costa moderado (estimación mar adentro)');
  const spear = buildRegionalBrief({...regional, profile: 'spear', date, now}).tiles.find(t => t.id === 'swell');
  assert.equal(spear.display.sourceMissing, true);
  assert.equal(tileSourceName(spear, 'es'), 'Sin fuente');
  assert.equal(tileSourceName(spear), 'No source');
});

test('detail_all_bands_keep_qualifiers: every band, side, stage, trend and bar state says its full phrase', () => {
  const es = part => partText(part, 'es'), en = part => partText(part, 'en');
  const cases = [
    [{kind: 'surge', band: 'Low'}, 'low surge', 'vaivén del agua leve'], [{kind: 'surge', band: 'Moderate'}, 'moderate surge', 'vaivén del agua moderado'],
    [{kind: 'surge', band: 'Strong'}, 'strong surge', 'vaivén del agua fuerte'], [{kind: 'surge', band: 'Heavy'}, 'heavy surge', 'vaivén del agua muy intenso'],
    [{kind: 'surf', band: 'Small', offshore: false}, 'small surf', 'oleaje en la costa pequeño'], [{kind: 'surf', band: 'Large', offshore: false}, 'large surf', 'oleaje en la costa grande'],
    [{kind: 'surf', band: 'Heavy', offshore: true}, 'heavy surf (offshore estimate)', 'oleaje en la costa muy intenso (estimación mar adentro)'],
    [{kind: 'surf', band: 'Moderate', offshore: true}, 'moderate surf (offshore estimate)', 'oleaje en la costa moderado (estimación mar adentro)'],
    [{kind: 'longSwell'}, 'long-period swell', 'mar de fondo de período largo'],
    [{kind: 'kayakWind', band: 'Light', side: null}, 'light', 'leve'], [{kind: 'kayakWind', band: 'Moderate', side: 'onshore'}, 'moderate onshore', 'moderado hacia la costa'],
    [{kind: 'kayakWind', band: 'Fresh', side: 'offshore'}, 'fresh offshore', 'fresco hacia mar adentro'], [{kind: 'kayakWind', band: 'Strong', side: 'cross-shore'}, 'strong cross-shore', 'fuerte paralelo a la costa'],
    [{kind: 'windSide', side: 'onshore'}, 'onshore', 'hacia la costa'], [{kind: 'windSide', side: 'offshore'}, 'offshore', 'hacia mar adentro'], [{kind: 'windSide', side: 'cross-shore'}, 'cross-shore', 'paralelo a la costa'],
    [{kind: 'kayakSeas', band: 'Small'}, 'small seas', 'oleaje pequeño'], [{kind: 'kayakSeas', band: 'Moderate'}, 'moderate seas', 'oleaje moderado'],
    [{kind: 'kayakSeas', band: 'Large'}, 'large seas', 'oleaje grande'], [{kind: 'kayakSeas', band: 'Heavy'}, 'heavy seas', 'oleaje muy intenso'],
    [{kind: 'shortChop'}, 'short-period chop', 'oleaje picado de período corto'],
    [{kind: 'launchSurf', offshore: false}, 'surf at the launch', 'oleaje en el punto de salida'], [{kind: 'launchSurf', offshore: true}, 'surf at the launch (offshore estimate)', 'oleaje en el punto de salida (estimación mar adentro)'],
    [{kind: 'tideTrend', trend: 'Rising'}, 'Rising', 'Subiendo'], [{kind: 'tideTrend', trend: 'Falling'}, 'Falling', 'Bajando'], [{kind: 'tideTrend', trend: 'Turning'}, 'Turning', 'Cambiando'],
    [{kind: 'nextEvent', type: 'H'}, 'next high', 'próxima pleamar'], [{kind: 'nextEvent', type: 'L'}, 'next low', 'próxima bajamar'],
    [{kind: 'veryLow'}, 'very low', 'muy baja'],
    [{kind: 'tideStage', stage: 'ebb'}, 'ebb', 'vaciante'], [{kind: 'tideStage', stage: 'flood'}, 'flood', 'creciente'], [{kind: 'tideStage', stage: 'midEbb'}, 'mid-ebb', 'mitad de la vaciante'],
    [{kind: 'barBand', band: 'clear'}, 'no bar flag (estimate)', 'sin señal de alerta en la barra (estimación)'], [{kind: 'barBand', band: 'caution'}, 'bar caution (estimate)', 'precaución en la barra (estimación)'],
    [{kind: 'barBand', band: 'hazardous'}, 'bar hazardous (estimate)', 'condiciones peligrosas en la barra (estimación)'], [{kind: 'barBand', band: 'unknown'}, 'bar unknown (estimate)', 'estado desconocido de la barra (estimación)'],
    [{kind: 'gust', value: 18.5}, 'gust 18.5 kt', 'ráfaga 18,5 kt'], [{kind: 'gust', value: null}, 'gust unknown', 'ráfaga desconocida'], [{kind: 'direction', value: 'NW'}, 'from NW', 'desde NW'],
    [{kind: 'offshoreForecast'}, 'offshore forecast', 'pronóstico mar adentro'], [{kind: 'noNearshore'}, 'No nearshore model site', 'No hay sitio de modelo cercano a la costa'],
    [{kind: 'buoy', name: 'NDBC 46042'}, 'buoy NDBC 46042', 'boya NDBC 46042'], [{kind: 'noBuoy'}, 'no fresh buoy', 'sin boya con datos recientes'],
    [{kind: 'tideUnavailable'}, TIDE_UNAVAILABLE, 'Serie de mareas no disponible'], [{kind: 'predictionsUnavailable'}, 'Predictions unavailable', 'Predicciones no disponibles'],
  ];
  for (const [part, wantEn, wantEs] of cases) { assert.equal(en(part), wantEn, JSON.stringify(part)); assert.equal(es(part), wantEs, JSON.stringify(part)); }
  assert.ok(['clear', 'caution', 'hazardous', 'unknown'].every(b => /estimaci[oó]n/.test(es({kind: 'barBand', band: b}))), 'every bar state keeps its estimate qualifier');
  assert.equal(tideEmptyText('unavailable'), TIDE_UNAVAILABLE);
  assert.equal(tideEmptyText('noCurve'), TIDE_NO_CURVE);
  assert.equal(tideEmptyText('noCurve', 'es'), 'No hay curva de marea para este lugar. Las horas de abajo son las pleamares y bajamares previstas del día.');
});

test('detail_names_opaque_and_legacy_fallback: names are literals, never parsed; unannotated tiles keep their text', () => {
  const name = 'offshore forecast · no fresh buoy: Bahía <b>Ñ</b>';
  const tile = {id: 'swell', detail: `5 s · ${name}`, display: {parts: [{kind: 'literal', text: '5 s'}, {kind: 'literal', text: name}]}};
  assert.equal(tileDetailText(tile, 'es'), `5 s · ${name}`);
  assert.equal(tileDetailText({id: 'wind', detail: 'gust unknown · from N'}, 'es'), 'gust unknown · from N', 'legacy tile: no reconstruction');
  assert.equal(tileSourceName({source: 'No source', display: {parts: []}}, 'es'), 'No source', 'only a tile marked sourceMissing says it in Spanish');
});

test('detail_selected_station_does_not_borrow_reference: the chosen station names its own tile in both languages', () => {
  const brief = buildCoastBrief({report, county: slo, areaId: 'central', profile: 'boat', date, now});
  const station = {id: '9000002', name: 'Fixture subordinate · Ñandú'};
  const events = [{at: `${date}T20:00:00.000Z`, heightFt: 3.2, type: 'H'}];
  const selected = withTideSelection(brief, station, {station, points: [], events, fetchedAt: now.toISOString(), failed: false}, slo.timezone, now, `${date}T18:00:00.000Z`);
  const tile = selected.tiles.find(t => t.id === 'tide');
  assert.equal(join(tile, 'en'), tile.detail);
  assert.equal(tile.detail, `next high · ${station.name} · MLLW`);
  assert.equal(tileDetailText(tile, 'es'), `próxima pleamar · ${station.name} · MLLW`);
  assert.equal(tile.display.datum, 'MLLW');
  const none = withTideSelection(brief, station, null, slo.timezone, now).tiles.find(t => t.id === 'tide');
  assert.equal(none.state, 'unavailable');
  assert.equal(none.detail, `Predictions unavailable · ${station.name} · MLLW`);
  assert.equal(tileDetailText(none, 'es'), `Predicciones no disponibles · ${station.name} · MLLW`);
  assert.ok(!tileDetailText(none, 'es').includes(slo.tideStation.name), 'no default station borrowed');
});

test('gap_clock_same_evidence_in_es: each gap kind and clock reads the same evidence in Spanish', () => {
  const s = montereyDaily.sources;
  const at = h => new Date(now.getTime() + h * 3_600_000).toISOString();
  const daily = {...montereyDaily, sources: {...s,
    'buoy-46042': {...s['buoy-46042'], status: 'stale'},
    tides: {...s.tides, status: 'retained', data_retrieved_at: at(-30)},
    'alerts-PZZ535': {...s['alerts-PZZ535'], status: 'failed', data: null},
  }};
  const gaps = sourceGaps(daily, now);
  assert.equal(gaps.length, 3);
  for (const g of gaps) { assert.equal(sourceGapText(g), g.text); assert.equal(sourceGapText(g, 'en'), g.text); }
  assert.match(gaps[0].text, /: stale, newest reading 30 min old\.$/);
  assert.equal(sourceGapText(gaps[0], 'es'), `${gaps[0].label}: desactualizado, la lectura más reciente tiene 30 min de antigüedad.`);
  assert.equal(sourceGapText(gaps[1], 'es'), `${gaps[1].label}: la última revisión falló; se muestran los últimos datos válidos, recuperado hace 30 h.`);
  assert.equal(sourceGapText(gaps[2], 'es'), `${gaps[2].label}: la última revisión falló; no hay datos anteriores disponibles.`);
  const clocks = {...montereyDaily, sources: {...s,
    tides: {...s.tides, status: 'stale', data: {...s.tides.data, coverage_end: at(-3)}},
    'alerts-PZZ535': {...s['alerts-PZZ535'], status: 'stale', data: {...s['alerts-PZZ535'].data, issued_at: at(-7)}},
  }};
  const [ended, issued] = sourceGaps(clocks, now);
  assert.match(sourceGapText(ended, 'es'), /: desactualizado, la cobertura terminó hace 3 h\.$/);
  assert.match(sourceGapText(issued, 'es'), /: desactualizado, emitido hace 7 h\.$/);
  const future = sourceGaps({...montereyDaily, sources: {...s, tides: {...s.tides, status: 'stale', data: {...s.tides.data, coverage_end: at(5)}}}}, now)[0];
  assert.match(future.text, /coverage runs 5 h more\.$/);
  assert.match(sourceGapText(future, 'es'), /la cobertura continúa durante 5 h más\.$/);
  const missing = sourceGaps({...montereyDaily, sources: {...s, tides: {...s.tides, status: 'missing', data: undefined}}}, now)[0];
  assert.equal(sourceGapText(missing, 'es'), `${missing.label}: no publicado en esta fuente.`);
  const odd = sourceGaps({...montereyDaily, sources: {...s, tides: {...s.tides, status: 'degraded'}}}, now)[0];
  assert.equal(odd.display.kind, 'other');
  assert.equal(sourceGapText(odd, 'es'), odd.text, 'an unknown status keeps its raw text');
  assert.equal(sourceGapText({id: 'x', label: 'L', status: 'failed', text: 'L: raw.'}, 'es'), 'L: raw.', 'a legacy gap keeps its text');
});

test('gap_clock_same_evidence_in_es: the coast report\'s failed check', () => {
  const failed = {...report, sources: report.sources.map(x => x.kind === 'prediction' ? {...x, outcome: 'error'} : x)};
  const area = slo.areas.find(a => a.id === 'central');
  const gaps = reportGaps(failed, slo, area, now);
  assert.ok(gaps.length >= 1);
  const gap = gaps[0];
  assert.match(gap.text, /latest check failed; last fetched \d+ (min|h|d) ago\.$/);
  assert.match(sourceGapText(gap, 'es'), /: la última revisión falló; obtenido por última vez hace \d+ (min|h|d)\.$/);
  const skewed = reportGaps({...failed, sources: failed.sources.map(x => ({...x, fetchedAt: 'not a date'}))}, slo, area, now)[0];
  assert.equal(skewed.display.clock, undefined);
  assert.equal(sourceGapText(skewed, 'es'), `${skewed.label}: la última revisión falló.`);
});

test('tile_detail_catalogue_exhaustive: tile.detail / tile.gap / tile.clock ids have es and matching placeholders; adapter is covered', () => {
  const ids = Object.keys(STRINGS).filter(id => /^(tile\.(detail|gap|clock)\.|tide\.(unavailable|noCurve))/.test(id));
  assert.ok(ids.length > 50);
  const holes = x => (x.match(/\{\w+\}/g) ?? []).sort().join();
  for (const id of ids) { assert.ok(STRINGS[id].es, `${id} has es`); assert.equal(holes(STRINGS[id].es), holes(STRINGS[id].en), `${id} placeholders`); }
  assert.equal(STRINGS['tide.unavailable'].en, TIDE_UNAVAILABLE);
  assert.equal(STRINGS['tide.noCurve'].en, TIDE_NO_CURVE);
  assert.ok(COVERED.includes('web/brief/tile-copy.ts'));
  assert.throws(() => partText({kind: 'barBand', band: 'nope'}, 'es'));
});
