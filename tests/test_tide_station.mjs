import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {stationsInRegion, nearestTideStation, tideRegion, readTideChoice, saveTideChoice, readSavedTideStations, saveSavedTideStations, tideChoiceKey, tideSavedKey, tidePredictionsURL, parseTidePredictions, loadTideReading, tidePackURLs, saveTidePack, withTideSelection, TIDE_DIRECTORY_URL} from '../web/tide-stations.ts';
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
const memory = () => {
  const values = new Map();
  return {values, getItem: k => values.get(k) ?? null, setItem: (k, v) => values.set(k, v), removeItem: k => values.delete(k)};
};
const c = {...b, id: '9000005', name: 'Fixture third'}, d = {...a, id: '9000006', name: 'Fixture fourth'}, e = {...b, id: '9000007', name: 'Fixture fifth'};
const savedFetcher = async url => url === TIDE_DIRECTORY_URL ? Response.json({stations: [a, b, c, d, e]}) : fetcher(url);

test('legacy single choice migrates once to a one-element saved list and active choice', () => {
  const storage = memory();
  storage.setItem(tideChoiceKey('one'), b.id);
  assert.deepEqual(readSavedTideStations('one', storage), {saved: [b.id], active: b.id});
  assert.deepEqual(JSON.parse(storage.getItem(tideSavedKey('one'))), {saved: [b.id], active: b.id});
  assert.equal(storage.getItem(tideChoiceKey('one')), null);
  storage.setItem(tideChoiceKey('one'), c.id);
  assert.deepEqual(readSavedTideStations('one', storage), {saved: [b.id], active: b.id}, 'v2 takes precedence');
  assert.deepEqual(readSavedTideStations('other', storage), {saved: [], active: null});
  const failed = memory(); failed.setItem(tideChoiceKey('one'), b.id);
  failed.setItem = () => { throw Error('blocked'); };
  assert.deepEqual(readSavedTideStations('one', failed), {saved: [b.id], active: b.id});
  assert.equal(failed.getItem(tideChoiceKey('one')), b.id, 'prior state survives write failure');
});

test('malformed saved state is not accepted or written over prior state', () => {
  const storage = memory();
  const invalid = [null, {}, {saved: null, active: null}, {saved: [b.id, b.id], active: b.id},
    {saved: [b.id, c.id, d.id, e.id], active: b.id}, {saved: ['bad'], active: null},
    {saved: [b.id], active: c.id}, {saved: [b.id]}, {saved: [1234567], active: null}];
  for (const value of invalid) {
    storage.setItem(tideSavedKey('one'), JSON.stringify(value));
    assert.deepEqual(readSavedTideStations('one', storage), {saved: [], active: null});
    storage.setItem(tideSavedKey('one'), 'previous');
    saveSavedTideStations('one', value, storage);
    assert.equal(storage.getItem(tideSavedKey('one')), 'previous');
  }
  storage.setItem(tideSavedKey('one'), '{');
  assert.deepEqual(readSavedTideStations('one', storage), {saved: [], active: null});
});

test('saved list adds three, rejects fourth with a message, switches, removes and restores per region', async () => {
  const storage = memory(), model = createTideSelection(savedFetcher, storage);
  model.configure(config); await model.list();
  for (const station of [b, c, d]) { assert.equal(model.choose(station.id), true); await model.refresh(); }
  assert.deepEqual(model.saved.value, [b.id, c.id, d.id]);
  const before = storage.getItem(tideSavedKey(config.id)), reading = model.reading.value;
  assert.equal(model.choose(e.id), false);
  assert.match(model.notice.value, /three.*Remove one/);
  assert.equal(model.error.value, '', 'cap notice is not a data failure');
  assert.deepEqual(model.saved.value, [b.id, c.id, d.id]);
  assert.equal(model.choice.value, d.id); assert.equal(model.reading.value, reading);
  assert.equal(storage.getItem(tideSavedKey(config.id)), before);
  assert.equal(model.choose(b.id), true); await model.refresh();
  assert.deepEqual(model.saved.value, [b.id, c.id, d.id], 'switch does not duplicate');
  const brief = buildCoastBrief({report: fixture, county: slo, areaId: 'central', profile: 'boat', date: '2026-10-08', now});
  const overlay = withTideSelection(brief, model.reading.value.station, model.reading.value, slo.timezone, now);
  assert.match(overlay.tiles.find(t => t.id === 'tide').source, /9000002 Fixture subordinate/);
  assert.equal(overlay.tiles.find(t => t.id === 'tide').value, 3.2);
  model.remove(c.id); assert.equal(model.choice.value, b.id); assert.ok(model.reading.value);
  assert.equal(model.choose(e.id), true); await model.refresh();
  const restarted = createTideSelection(savedFetcher, storage);
  restarted.configure(config); await restarted.refresh();
  assert.deepEqual(restarted.saved.value, [b.id, d.id, e.id]); assert.equal(restarted.choice.value, e.id);
  restarted.configure({...config, id: 'other'});
  assert.deepEqual(restarted.saved.value, []); assert.equal(restarted.choice.value, null);
  restarted.configure(config); await restarted.refresh();
  restarted.remove(e.id); assert.equal(restarted.choice.value, null); assert.equal(restarted.reading.value, null);
  assert.deepEqual(restarted.saved.value, [b.id, d.id]);
  restarted.choose(null); restarted.remove('9999999');
  assert.deepEqual(readSavedTideStations(config.id, storage), {saved: [b.id, d.id], active: null});
});

test('non-active removal preserves a prediction failure for the active station', async () => {
  const storage = memory();
  const model = createTideSelection(async url => url === TIDE_DIRECTORY_URL
    ? savedFetcher(url) : new Response('Unavailable', {status: 500}), storage);
  model.configure(config); await model.list();
  for (const station of [b, c]) { assert.equal(model.choose(station.id), true); await model.refresh(); }
  const error = model.error.value, reading = model.reading.value;
  assert.match(error, /Some chosen-station predictions are unavailable/);
  assert.equal(reading.failed, true);
  model.remove(b.id);
  assert.equal(model.error.value, error, 'removing another saved station must not hide a data failure');
  assert.equal(model.reading.value, reading); assert.equal(model.choice.value, c.id);
  assert.deepEqual(readSavedTideStations(config.id, storage), {saved: [c.id], active: c.id});
  model.remove(c.id);
  assert.equal(model.choice.value, null); assert.equal(model.error.value, '');
});

test('non-active removal preserves a directory failure for the restored active station', async () => {
  const storage = memory();
  saveSavedTideStations(config.id, {saved: [b.id, c.id], active: c.id}, storage);
  const model = createTideSelection(async () => new Response('Unavailable', {status: 500}), storage);
  model.configure(config); await model.refresh();
  const error = model.error.value;
  assert.match(error, /NOAA station directory unavailable/);
  model.remove(b.id);
  assert.equal(model.error.value, error, 'removing another saved station must not hide a directory failure');
  assert.equal(model.reading.value, null); assert.equal(model.choice.value, c.id);
  assert.deepEqual(readSavedTideStations(config.id, storage), {saved: [c.id], active: c.id});
});

test('cap refusal preserves the active data failure and exposes a separate notice', async () => {
  const storage = memory();
  const model = createTideSelection(async url => url === TIDE_DIRECTORY_URL
    ? savedFetcher(url) : new Response('Unavailable', {status: 500}), storage);
  model.configure(config); await model.list();
  for (const station of [b, c, d]) { assert.equal(model.choose(station.id), true); await model.refresh(); }
  const error = model.error.value, reading = model.reading.value, before = storage.getItem(tideSavedKey(config.id));
  assert.match(error, /Some chosen-station predictions are unavailable/); assert.equal(reading.failed, true);
  assert.equal(model.choose(e.id), false);
  assert.equal(model.error.value, error, 'a cap refusal must not replace the active data failure');
  assert.match(model.notice.value, /three.*Remove one/);
  assert.equal(model.choice.value, d.id); assert.equal(model.reading.value, reading);
  assert.deepEqual(model.saved.value, [b.id, c.id, d.id]);
  assert.equal(storage.getItem(tideSavedKey(config.id)), before);
  model.remove(b.id);
  assert.equal(model.notice.value, '', 'freeing a slot clears the cap notice, not the data failure');
  assert.equal(model.error.value, error);
  assert.equal(model.choose(e.id), true); await model.refresh();
  assert.equal(model.notice.value, ''); assert.match(model.error.value, /Some chosen-station predictions are unavailable/);
  assert.equal(model.choose(b.id), false); assert.match(model.notice.value, /three/);
  assert.equal(model.choose(c.id), true); await model.refresh();
  assert.equal(model.notice.value, '', 'switching clears the old refusal');
  assert.equal(model.choose(b.id), false); assert.match(model.notice.value, /three/);
  model.configure({...config, id: 'other'});
  assert.equal(model.notice.value, ''); assert.equal(model.error.value, '');
});

test('offline pack snapshots exactly the active station, never all saved stations', async () => {
  const model = createTideSelection(savedFetcher, memory());
  model.configure(config); await model.list();
  for (const station of [b, c, d]) model.choose(station.id);
  assert.deepEqual(await model.packURLs(config.id, now.getTime()), tidePackURLs(d, now.getTime()));
  model.choose(b.id);
  const pending = model.packURLs(config.id, now.getTime());
  model.choose(d.id);
  assert.deepEqual(await pending, tidePackURLs(b, now.getTime()), 'snapshot survives a concurrent switch');
  model.choose(null);
  assert.deepEqual(await model.packURLs(config.id), []);
  assert.deepEqual(model.saved.value, [b.id, c.id, d.id], 'default retains saved list');
});

test('unavailable restored stations stay named by ID without default substitution or invalid pack', async () => {
  const storage = memory(); saveSavedTideStations(config.id, {saved: [e.id], active: e.id}, storage);
  const model = createTideSelection(fetcher, storage);
  model.configure(config); await model.refresh();
  assert.equal(model.choice.value, e.id); assert.equal(model.reading.value, null);
  assert.match(model.error.value, /unavailable in this region/);
  await assert.rejects(model.packURLs(config.id), /could not be resolved/);
  model.remove(e.id); assert.deepEqual(model.saved.value, []); assert.equal(model.choice.value, null);
});

test('migrated model choice resolves the real catalog and blocked storage still permits this visit', async () => {
  const storage = memory(); storage.setItem(tideChoiceKey(config.id), b.id);
  const model = createTideSelection(savedFetcher, storage);
  model.configure(config); await model.refresh();
  assert.deepEqual(model.saved.value, [b.id]); assert.equal(model.reading.value.station.id, b.id);
  const blocked = {getItem() { throw Error('blocked'); }, setItem() { throw Error('blocked'); }, removeItem() { throw Error('blocked'); }};
  const visit = createTideSelection(savedFetcher, blocked);
  visit.configure(config); await visit.list();
  assert.equal(visit.choose(c.id), true); await visit.refresh();
  assert.deepEqual(visit.saved.value, [c.id]); assert.equal(visit.reading.value.station.id, c.id);
});

test('removing an active station invalidates its outstanding prediction response', async () => {
  let release;
  const model = createTideSelection(async url => url === TIDE_DIRECTORY_URL ? Response.json(directory) : new Promise(r => { release = r; }), memory());
  model.configure(config); await model.list(); model.choose(b.id); await flush();
  model.remove(b.id); release(Response.json(hilo)); await flush();
  assert.equal(model.choice.value, null); assert.equal(model.reading.value, null); assert.deepEqual(model.saved.value, []);
});

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
