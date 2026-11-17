// Synthetic saved trips only. No provider, account, network or calendar access.
import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp, readFile, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {rendererPlugins} from './helpers/esbuild-url.mjs';
import {escapeText, foldLine, zonedInstant, tripCalendar} from '../web/trip-calendar.ts';
import {calendarRegions} from '../scripts/build_trip_calendar_regions.mjs';

const trip = {id: 'synthetic-123', region: 'test-region', point: 'test-area', species: 'reef', targets: ['reef', 'retired-species'], date: '2026-11-14', start_hour: 7, end_hour: 13, wind_limit: 9, gust_limit: 14, sea_limit: 2.5};
const opts = {areaName: 'Test area', speciesNames: ['Rockfish', 'retired-species'], limits: 'Saved limits: wind 9 kt · gust 14 kt · sea 2.5 ft', appUrl: 'https://example.test', now: new Date('2026-11-10T12:34:56Z'), timeZone: 'America/Los_Angeles'};
const unfold = text => text.replace(/\r\n /g, '');
const line = (text, key) => unfold(text).split('\r\n').find(s => s.startsWith(key + ':'));

for (const [date, start_hour, end_hour, start, end] of [
  ['2026-11-14', 7, 13, '20261114T150000Z', '20261114T210000Z'],
  ['2026-03-08', 1, 5, '20260308T090000Z', '20260308T120000Z'],
  ['2026-11-01', 0, 4, '20261101T070000Z', '20261101T120000Z'],
]) test(`one UTC event on ${date}, independent of the export date`, () => {
  const text = tripCalendar({...trip, date, start_hour, end_hour}, opts);
  assert.equal(line(text, 'DTSTART'), 'DTSTART:' + start);
  assert.equal(line(text, 'DTEND'), 'DTEND:' + end);
  assert.equal(line(text, 'DTSTAMP'), 'DTSTAMP:20261110T123456Z');
  assert.equal(line(text, 'SUMMARY'), 'SUMMARY:Fishing window: Test area');
  assert.equal(line(text, 'URL'), 'URL:https://example.test/map#alerts');
  assert.equal((text.match(/BEGIN:VEVENT/g) ?? []).length, 1);
  assert.match(text, /^BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-\/\/SkipperCast\/\/Saved trip\/\/EN\r\nCALSCALE:GREGORIAN\r\n/);
  assert.match(text, /END:VEVENT\r\nEND:VCALENDAR\r\n$/);
  assert.doesNotMatch(text.replace(/\r\n/g, ''), /[\r\n]/);
  assert.doesNotMatch(text, /VTIMEZONE|TZID/);
  const description = line(text, 'DESCRIPTION');
  assert.ok(description.includes('Targets: Rockfish · retired-species\\n' + opts.limits + '\\nTrip alerts are a forecast read\\, not a clearance for the trip.'));
});

test('repeated hour chooses first occurrence; missing hour moves through spring gap; bad stored dates/hours refused', () => {
  assert.equal(zonedInstant('2026-11-01', 1, opts.timeZone).toISOString(), '2026-11-01T08:00:00.000Z');
  assert.equal(zonedInstant('2026-03-08', 2, opts.timeZone).toISOString(), '2026-03-08T10:00:00.000Z');
  assert.equal(zonedInstant(trip.date, 7, 'Pacific/Auckland').toISOString(), '2026-11-13T18:00:00.000Z');
  for (const date of ['2026-02-30', 'bad', '2026-1-01']) assert.throws(() => zonedInstant(date, 7, opts.timeZone), RangeError);
  for (const hour of [-1, 24, 1.5, NaN]) assert.throws(() => zonedInstant(trip.date, hour, opts.timeZone), RangeError);
  assert.throws(() => tripCalendar({...trip, end_hour: 7}, opts), RangeError);
  assert.throws(() => tripCalendar({...trip, date: '2026-03-08', start_hour: 2, end_hour: 3}, opts), RangeError, 'the skipped hour must not create a zero-duration event');
});

test('TEXT escaping prevents injected content lines and preserves CRLF/CR/LF as text', () => {
  assert.equal(escapeText('a,b;c\\d\r\ne\rf\ng'), 'a\\,b\\;c\\\\d\\ne\\nf\\ng');
  const text = tripCalendar(trip, {...opts, areaName: 'a,b;c\\d\nGEO:secret', speciesNames: ['a,b;c\\d\nfish'], limits: 'x;y'});
  assert.equal(line(text, 'SUMMARY'), 'SUMMARY:Fishing window: a\\,b\\;c\\\\d\\nGEO:secret');
  assert.ok(line(text, 'DESCRIPTION').includes('a\\,b\\;c\\\\d\\nfish\\nx\\;y'));
  assert.doesNotMatch(text, /\r\nGEO:/);
});

test('long multibyte SUMMARY and DESCRIPTION fold at 75 octets without broken UTF-8', () => {
  const name = 'é🐟'.repeat(70), text = tripCalendar(trip, {...opts, areaName: name, speciesNames: [name]});
  const bytes = new TextEncoder().encode(text);
  // Split bytes at CRLF before decoding, so replacement characters cannot hide a split code point.
  let begin = 0, folds = 0;
  for (let i = 0; i < bytes.length - 1; i++) if (bytes[i] === 13 && bytes[i + 1] === 10) {
    const physical = bytes.slice(begin, i);
    assert.ok(physical.length <= 75);
    const decoded = new TextDecoder('utf-8', {fatal: true}).decode(physical);
    if (decoded.startsWith(' ')) folds++;
    begin = i + 2; i++;
  }
  assert.ok(folds > 2);
  assert.equal(line(text, 'SUMMARY'), 'SUMMARY:Fishing window: ' + name);
  assert.ok(line(text, 'DESCRIPTION').includes(name));
  assert.equal(foldLine('a'.repeat(75) + '🐟'), 'a'.repeat(75) + '\r\n 🐟');
});

test('UID stable on duplicate exports, unique by trip; retired area fallback; private fields never serialized', () => {
  const privateTrip = {...trip, lat: 35.123456, lon: -120.654321, note: 'PRIVATE-NOTE', owner: 'PRIVATE-OWNER', spot: 'PRIVATE-SPOT', plan: {spots: [{name: 'PRIVATE-PLAN'}]}};
  const a = tripCalendar(privateTrip, {...opts, areaName: undefined});
  const b = tripCalendar(privateTrip, {...opts, now: new Date('2027-01-01Z')});
  assert.equal(line(a, 'UID'), 'UID:trip-synthetic-123@skippercast');
  assert.equal(line(a, 'UID'), line(b, 'UID'));
  assert.notEqual(line(a, 'UID'), line(tripCalendar({...trip, id: 'other'}, opts), 'UID'));
  assert.equal(line(a, 'SUMMARY'), 'SUMMARY:Fishing window: test-area');
  assert.doesNotMatch(a, /GEO|35\.123456|120\.654321|PRIVATE/);
});

test('offline calendar names track all published region configs', async () => {
  assert.deepEqual(JSON.parse(await readFile('web/trip-calendar-regions.generated.json', 'utf8')), await calendarRegions());
});

test('upcoming-only action downloads the local file, uses the known region zone, cleans URLs, sends nothing', async t => {
  const dir = await mkdtemp(join(tmpdir(), 'trip-ics-'));
  try {
    const out = join(dir, 'view.mjs');
    await build({stdin: {resolveDir: new URL('..', import.meta.url).pathname, loader: 'ts', contents: `
      export {SavedTrips} from './web/app/TripAlerts.tsx';
      export {tripRecaps} from './web/alerts.ts';
      export {language, prepareCatalogue} from './web/i18n.ts';
      export {render} from 'preact-render-to-string'; export {h, options} from 'preact';`},
      bundle: true, platform: 'node', format: 'esm', outfile: out, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact', plugins: rendererPlugins});
    const {SavedTrips, tripRecaps, language, prepareCatalogue, render, h, options} = await import(pathToFileURL(out).href);
    let buttons = [], blobs = [], clicks = [], revoked = [];
    options.vnode = v => { if (v.type === 'button') buttons.push(v.props); };
    const names = {point: new Map([[trip.point, 'Test area']]), species: new Map([['reef', 'Rockfish']])};
    const draw = (trips, extra = {}) => {
      buttons = [];
      return render(h(SavedTrips, {recaps: tripRecaps(trips, [], [], trip.date), names, remove: () => () => {}, useAgain: () => {}, regionId: trip.region, timeZone: 'Pacific/Auckland', ...extra}));
    };
    const action = (label = 'Add to calendar') => buttons.find(p => [p.children].flat(Infinity).includes(label));
    t.mock.method(globalThis, 'fetch', () => { throw Error('Calendar export must not fetch'); });
    t.mock.method(URL, 'createObjectURL', blob => { blobs.push(blob); return 'blob:synthetic-' + blobs.length; });
    t.mock.method(URL, 'revokeObjectURL', url => revoked.push(url));
    t.mock.timers.enable({apis: ['setTimeout']});
    const oldDocument = Object.getOwnPropertyDescriptor(globalThis, 'document'), oldLocation = Object.getOwnPropertyDescriptor(globalThis, 'location');
    Object.defineProperty(globalThis, 'document', {configurable: true, value: {createElement: tag => { assert.equal(tag, 'a'); return {click() { clicks.push({href: this.href, download: this.download}); }}; }}});
    Object.defineProperty(globalThis, 'location', {configurable: true, value: {origin: 'https://example.test'}});
    try {
      assert.doesNotMatch(draw([{...trip, date: '2026-11-13'}]), /Add to calendar/);
      assert.equal(action(), undefined, 'expired/past trip has no export action');
      assert.doesNotMatch(draw([]), /Add to calendar/, 'deleted trip has no export action');
      assert.match(draw([trip]), /Add to calendar/);
      assert.equal(blobs.length, 0, 'opening/dismissing the sheet alone creates no file');
      action().onClick(); action().onClick();
      assert.equal(blobs.length, 2);
      assert.equal(blobs[0].type, 'text/calendar;charset=utf-8');
      assert.equal(clicks[0].download, 'skippercast-trip-2026-11-14.ics');
      assert.equal(clicks[0].href, 'blob:synthetic-1');
      const text = await blobs[0].text();
      assert.equal(line(text, 'DTSTART'), 'DTSTART:20261113T180000Z');
      assert.equal(line(text, 'SUMMARY'), 'SUMMARY:Fishing window: Test area');
      assert.ok(line(text, 'DESCRIPTION').includes('Rockfish · retired-species'));
      assert.equal(line(text, 'UID'), line(await blobs[1].text(), 'UID'));
      t.mock.timers.tick(1000);
      assert.equal(revoked.length, 2);
      draw([{...trip, point: 'retired-area'}]); action().onClick();
      assert.equal(line(await blobs[2].text(), 'SUMMARY'), 'SUMMARY:Fishing window: retired-area');
      draw([{...trip, region: 'unknown'}]); action().onClick();
      const unknown = await blobs[3].text();
      assert.equal(line(unknown, 'DTSTART'), 'DTSTART:20261114T150000Z', 'unknown region uses DEFAULT_ZONE, not the opened region');
      assert.equal(line(unknown, 'SUMMARY'), 'SUMMARY:Fishing window: test-area');
      draw([{...trip, date: '2026-03-08', start_hour: 2, end_hour: 3}], {recaps: {upcoming: [{...trip, date: '2026-03-08', start_hour: 2, end_hour: 3}], past: []}, timeZone: 'America/Los_Angeles'});
      assert.doesNotThrow(() => action().onClick(), 'a bad stored window reports failure rather than throwing from the action');
      assert.equal(blobs.length, 4, 'a skipped-hour-only window creates no invalid event or download');
      await prepareCatalogue('es'); language.value = 'es';
      assert.match(draw([trip]), /Añadir al calendario/);
      action('Añadir al calendario').onClick();
      assert.match(unfold(await blobs[4].text()), /SUMMARY:Horario de pesca: Test area/);
      assert.match(unfold(await blobs[4].text()), /no una autorización para el viaje/);
      assert.equal(globalThis.fetch.mock.callCount(), 0);
      language.value = 'en';
      draw([{...trip, region: 'morro-bay', point: 'north', species: 'reef', targets: ['reef', 'retired-species']}]);
      await action().onClick();
      const other = await blobs[5].text();
      assert.equal(line(other, 'SUMMARY'), 'SUMMARY:Fishing window: Point Estero');
      assert.ok(line(other, 'DESCRIPTION').includes('Lingcod & rockfish · retired-species'));
      assert.equal(line(other, 'DTSTART'), 'DTSTART:20261114T150000Z');
      assert.equal(globalThis.fetch.mock.callCount(), 0, 'cross-region export sends nothing');
    } finally {
      language.value = 'en';
      for (const [key, descriptor] of [['document', oldDocument], ['location', oldLocation]]) {
        if (descriptor) Object.defineProperty(globalThis, key, descriptor); else delete globalThis[key];
      }
    }
  } finally { await rm(dir, {recursive: true, force: true}); }
});
