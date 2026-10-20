import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {stationsInRegion, nearestTideStation, tideRegion, readTideChoice, saveTideChoice, tidePredictionsURL, parseTidePredictions, loadTideReading, tidePackURLs, saveTidePack, withTideSelection, TIDE_DIRECTORY_URL} from '../web/tide-stations.ts';
import {createTideSelection} from '../web/tide-selection.ts';
import {buildCoastBrief} from '../web/brief/model.ts';
import {slo} from '../packages/coast/src/counties.ts';
import fixture from './fixtures/coast/skippercast-report.json' with {type: 'json'};
import {tideURL} from '../dist/marine-data.js';
const a = {id: '9000001', name: 'Fixture reference', lat: 35.1, lng: -121, type: 'R'};
const b = {id: '9000002', name: 'Fixture subordinate', lat: 35.8, lng: -121, type: 'S'};
const config = {id: 'fixture', bounds: [-122, 35, -120, 36], station: a.id, name: a.name};
const directory = {stations: [a, b, {...a, id: '9000003', lat: 37}, {...a, id: 'bad'}, {...a, id: '9000004', type: 'current'}]};
const hilo = {predictions: [{t: '2026-10-08 18:00', v: '3.2', type: 'H'}, {t: '2026-10-09 18:00', v: '3.3', type: 'H'}]};
const curve = {predictions: [{t: '2026-10-08 17:00', v: '1.2'}, {t: '2026-10-08 17:06', v: '1.3'}]};
const now = new Date('2026-10-08T17:00:00Z');
const fetcher = async url => Response.json(url === TIDE_DIRECTORY_URL ? directory : new URL(url).searchParams.get('interval') === 'hilo' ? hilo : curve);
const flush = () => new Promise(resolve => setImmediate(resolve));

test('configured default stays intact and no directory/prediction request runs until selection', async () => {
  const calls = [], model = createTideSelection(async url => { calls.push(url); return fetcher(url); });
  model.configure(config);
  await flush();
  assert.equal(model.choice.value, null);
  assert.equal(model.region.value.station, a.id);
  assert.deepEqual(calls, []);
  assert.deepEqual(await model.packURLs(config.id), []);
  assert.deepEqual(tideRegion(config.id, {bounds: config.bounds, stations: {tide: a.id, tide_name: a.name}}), config);
  assert.equal(tideRegion('bad', {}), null);
});

test('only CO-OPS prediction stations inside region; nearest uses port, deterministic ties', () => {
  const rows = stationsInRegion(directory, config.bounds);
  assert.deepEqual(rows, [a, b]);
  assert.equal(nearestTideStation(rows, [35.79, -121]).id, b.id);
  assert.equal(nearestTideStation(rows, [35.11, -121]).id, a.id);
  assert.equal(nearestTideStation([], [35, -121]), null);
  assert.equal(nearestTideStation(rows, [NaN, -121]), null);
});

test('browser choices are isolated per region and blocked storage degrades gracefully', () => {
  const values = new Map(), storage = {getItem: k => values.get(k), setItem: (k, v) => values.set(k, v), removeItem: k => values.delete(k)};
  saveTideChoice('one', a.id, storage); saveTideChoice('two', b.id, storage);
  assert.equal(readTideChoice('one', storage), a.id);
  assert.equal(readTideChoice('two', storage), b.id);
  saveTideChoice('one', null, storage);
  assert.equal(readTideChoice('one', storage), null);
  assert.equal(readTideChoice('two', storage), b.id);
  assert.equal(readTideChoice('bad', {getItem() { throw Error(); }}), null);
  assert.doesNotThrow(() => saveTideChoice('bad', b.id, {setItem() { throw Error(); }}));
});

test('choice loads correct station; nearest can be selected; default resets without substituting', async () => {
  const calls = [], model = createTideSelection(async url => { calls.push(url); return fetcher(url); });
  model.configure(config); await model.list();
  model.choose(nearestTideStation(model.stations.value, [35.79, -121]).id);
  await model.refresh();
  assert.equal(model.choice.value, b.id);
  assert.equal(model.reading.value.station.id, b.id);
  assert.equal(model.reading.value.points.length, 0, 'subordinate never requests a curve');
  assert.ok(calls.filter(u => u !== TIDE_DIRECTORY_URL).every(u => new URL(u).searchParams.get('station') === b.id));
  const urls = await model.packURLs(config.id, now.getTime());
  assert.deepEqual(urls, tidePackURLs(b, now.getTime()));
  assert.deepEqual(await model.packURLs('other'), []);
  model.choose('9999999'); assert.equal(model.choice.value, b.id);
  model.choose(null); assert.equal(model.reading.value, null); assert.equal(model.choice.value, null);
});

test('late station responses cannot replace another region', async () => {
  let release;
  const model = createTideSelection(async url => url === TIDE_DIRECTORY_URL ? Response.json(directory) : new Promise(r => { release = r; }));
  model.configure(config); await model.list(); model.choose(b.id); await flush();
  model.configure({...config, id: 'other'});
  release(Response.json(hilo)); await flush();
  assert.equal(model.region.value.id, 'other'); assert.equal(model.reading.value, null);
});

test('prediction URLs share offline cache identity with existing marine client', () => {
  for (const interval of ['hilo', '6']) assert.equal(tidePredictionsURL(b.id, interval, now.getTime()), tideURL(now.getTime(), interval, b.id));
});

test('invalid NOAA values rejected; saved clock preserved and subordinate has events only', async () => {
  assert.deepEqual(parseTidePredictions({predictions: [{t: 'bad', v: '1'}, {t: '2026-10-08 18:00', v: ''}, {t: '2026-10-08 18:00', v: 'NaN'}]}), {points: [], events: []});
  const saved = '2026-10-07T10:00:00Z';
  const reading = await loadTideReading(b, async () => Response.json(hilo, {headers: {'X-SC-Offline': saved}}), now.getTime());
  assert.equal(reading.fetchedAt, saved); assert.equal(reading.events.length, 2); assert.deepEqual(reading.points, []);
  const failed = await loadTideReading(b, async () => Response.json({error: {message: 'No data'}}), now.getTime());
  assert.equal(failed.failed, true); assert.deepEqual(failed.events, []);
});

test('selected tide tile/spark name actual station; safety assessments remain byte-identical', async () => {
  const brief = buildCoastBrief({report: fixture, county: slo, areaId: 'central', profile: 'boat', date: '2026-10-08', now});
  const reading = await loadTideReading(b, fetcher, now.getTime());
  const selected = withTideSelection(brief, b, reading, slo.timezone, now);
  const tile = selected.tiles.find(t => t.id === 'tide');
  assert.equal(tile.value, 3.2); assert.match(tile.source, /9000002 Fixture subordinate/);
  assert.match(tile.detail, /next high.*MLLW/);
  assert.equal(selected.tideEvents.length, 1, 'cut to selected local day');
  for (const key of ['shore', 'bar', 'windows', 'missing', 'deck', 'headline', 'status', 'confidence']) assert.deepEqual(selected[key], brief[key], key);
  assert.deepEqual(selected.tiles.slice(0, 3), brief.tiles.slice(0, 3));
  const missing = withTideSelection(brief, b, null, slo.timezone, now);
  assert.equal(missing.tiles[3].state, 'unavailable'); assert.deepEqual(missing.tides, []);
  const stale = withTideSelection(brief, b, {...reading, fetchedAt: '2026-10-01T00:00:00Z'}, slo.timezone, now);
  assert.equal(stale.tiles[3].state, 'stale');
});

test('offline save writes chosen station responses and directory; refuses NOAA errors and re-stamped offline data', async () => {
  const kept = new Map(), put = async (url, body) => kept.set(url, JSON.parse(new TextDecoder().decode(body)));
  const urls = tidePackURLs(b, now.getTime());
  await saveTidePack(urls, put, new AbortController().signal, fetcher);
  assert.deepEqual([...kept.keys()], urls);
  assert.deepEqual(kept.get(urls[1]), hilo);
  const replay = await loadTideReading(b, async url => Response.json(kept.get(url), {headers: {'X-SC-Offline': now.toISOString()}}), now.getTime());
  assert.equal(replay.events[0].heightFt, 3.2);
  for (const reply of [() => Response.json({error: 'No data'}), () => Response.json(hilo, {headers: {'X-SC-Offline': now.toISOString()}})])
    await assert.rejects(saveTidePack([urls[1]], put, new AbortController().signal, async () => reply()), /unchanged/);
  const trip = readFileSync(new URL('../web/trip.ts', import.meta.url), 'utf8');
  assert.match(trip, /await tideSelection.packURLs\(id\)/);
  assert.match(trip, /await saveTidePack\(tideURLs, put, signal\)/);
});
