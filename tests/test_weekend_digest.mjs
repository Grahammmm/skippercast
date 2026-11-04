import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile, mkdtemp, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {nextWeekend, weekendDigest, toText, EMPTY_WEEKEND} from '../web/digest.ts';
import {eventLine, STATUS_LABEL} from '../web/alerts.ts';

const names = {point: new Map([['a', 'Alpha'], ['z', 'Zulu']]), species: new Map([['reef', 'Rockfish']])};
const trip = (extra = {}) => ({id: 'fixture', date: '2026-11-07', point: 'a', species: 'reef', start_hour: 7, end_hour: 13, enabled: 1, last_assessment: null, ...extra});
const compose = trips => weekendDigest(trips, names, '2026-11-04');

test('weekday, Saturday, Sunday, DST and year boundaries are calendar dates', () => {
  for (const [today, sat, sun] of [
    ['2026-11-02', '2026-11-07', '2026-11-08'],
    ['2026-11-04', '2026-11-07', '2026-11-08'],
    ['2026-11-06', '2026-11-07', '2026-11-08'],
    ['2026-11-07', '2026-11-07', '2026-11-08'],
    ['2026-11-08', null, '2026-11-08'],
    ['2026-11-01', null, '2026-11-01'],
    ['2026-12-31', '2027-01-02', '2027-01-03'],
  ]) assert.deepEqual(nextWeekend(today), {sat, sun});
});

test('both days retain their trips but exclude Friday, past and next weekend', () => {
  const trips = ['2026-11-06', '2026-11-07', '2026-11-08', '2026-11-14'].map(date => trip({date}));
  assert.deepEqual(compose(trips).days.map(d => [d.date, d.lines.length]), [['2026-11-07', 1], ['2026-11-08', 1]]);
  assert.deepEqual(weekendDigest(trips, names, '2026-11-07').days.map(d => d.lines.length), [1, 1]);
  const sunday = weekendDigest(trips, names, '2026-11-08');
  assert.deepEqual(sunday.days.map(d => [d.date, d.lines.length]), [['2026-11-08', 1]]);
});

test('same-day trips sort by hour then displayed point name without mutating or dropping duplicates', () => {
  const trips = Object.freeze([trip({point: 'z', start_hour: 9}), trip({point: 'z'}), trip(), trip({id: 'second'})].map(Object.freeze));
  const lines = compose(trips).days[0].lines;
  assert.deepEqual(lines.map(l => l.split(' · ')[0]), ['Alpha', 'Alpha', 'Zulu', 'Zulu']);
  assert.match(lines[3], /9:00–13:00/);
  assert.equal(trips[0].start_hour, 9);
});

test('assessment parsing is fail-soft and shares the existing status map and unknown fallback', () => {
  for (const assessment of [undefined, null, '{', 'null', '[]', '{}', '{"status":5}']) {
    assert.match(compose([trip({last_assessment: assessment})]).days[0].lines[0], /— not assessed yet$/);
  }
  for (const status of [...Object.keys(STATUS_LABEL), 'review-required', 'constructor']) {
    const line = compose([trip({last_assessment: JSON.stringify({status})})]).days[0].lines[0];
    assert.equal(line.slice(line.indexOf(' — ') + 3), eventLine({kind: '', status}).slice(3));
  }
});

const lineOf = last_assessment => compose([trip({last_assessment})]).days[0].lines[0];
const prefix = 'Alpha · Rockfish · 7:00–13:00 — ';
const assessed = (status, hazards) => JSON.stringify(hazards === undefined ? {status} : {status, hazards});
const STATUS_WORDS = [['within limits', 'within your saved limits'], ['above limits', 'above your saved limits'], ['unverified', 'check incomplete']];
const SWELL = 'Long-period swell is forecast; the numbers above do not cover it.';
const BAR = 'Harbour bar crossing may be rough at the ebb.';
const BAR_UNJUDGED = 'Harbour bar not judged.';

test('each assessment status reads as its own plain words, not a delivery label or the raw code', () => {
  for (const [status, words] of STATUS_WORDS) assert.equal(lineOf(assessed(status)), `${prefix}${words}`);
  assert.match(lineOf(assessed('unverified')), /check incomplete$/);
  for (const status of ['pending', 'in-app', 'delivered', 'read']) assert.equal(lineOf(assessed(status)), `${prefix}${STATUS_LABEL[status]}`);
});

test('a stored note follows the status as stored, with one Hazard note prefix and no kind word added by the digest', () => {
  for (const [status, words] of STATUS_WORDS) {
    for (const note of [SWELL, BAR, BAR_UNJUDGED]) assert.equal(lineOf(assessed(status, [note])), `${prefix}${words} Hazard note: ${note}`);
  }
  assert.doesNotMatch(lineOf(assessed('within limits', [BAR])), /swell/i);
  assert.doesNotMatch(lineOf(assessed('within limits', [SWELL])), /\bbar\b/i);
  assert.doesNotMatch(lineOf(assessed('within limits', ['Note without a kind.'])), /swell|\bbar\b/i);
  assert.equal(lineOf(assessed('within limits', ['  spaced, as stored.  '])), `${prefix}within your saved limits Hazard note:   spaced, as stored.  `);
});

test('mixed notes are all shown, unmerged, in stored order, duplicates kept, and the status word never changes', () => {
  const stored = Object.freeze([SWELL, BAR_UNJUDGED]);
  const trips = Object.freeze([Object.freeze(trip({last_assessment: assessed('above limits', stored)}))]);
  assert.equal(compose(trips).days[0].lines[0], `${prefix}above your saved limits Hazard note: ${SWELL} Hazard note: ${BAR_UNJUDGED}`);
  assert.equal(lineOf(assessed('above limits', [BAR_UNJUDGED, SWELL])), `${prefix}above your saved limits Hazard note: ${BAR_UNJUDGED} Hazard note: ${SWELL}`);
  assert.equal(lineOf(assessed('within limits', [BAR, BAR])), `${prefix}within your saved limits Hazard note: ${BAR} Hazard note: ${BAR}`);
  assert.equal(toText(compose([trip({last_assessment: assessed('unverified', [SWELL, BAR])})])), `2026-11-07\n${prefix}check incomplete Hazard note: ${SWELL} Hazard note: ${BAR}`);
});

test('a hazards value that is not a list of non-empty strings adds nothing; no hazards leaves the status-only line', () => {
  for (const [status, words] of STATUS_WORDS) {
    const only = `${prefix}${words}`;
    assert.equal(lineOf(assessed(status)), only);
    for (const hazards of [[], null, 'Long-period swell.', {note: SWELL}, 5, true, [SWELL, 5], [SWELL, null], [SWELL, ''], [SWELL, '   '], [BAR, ['nested']], [{}], ['']]) {
      assert.equal(lineOf(assessed(status, hazards)), only, JSON.stringify(hazards));
    }
  }
  assert.equal(lineOf('{"status":"within limits","hazards":'), `${prefix}not assessed yet`);
});

test('a malformed or unusable assessment stays not assessed yet and leaks no note or error text', () => {
  for (const assessment of ['{', '{"status":"within limits","hazards":["x"]', 'null', '5', '"within limits"', 'true', '[]', '["within limits"]', '[{"status":"within limits","hazards":["x"]}]',
    '{}', '{"status":""}', '{"status":5}', '{"status":null}', '{"hazards":["Long-period swell."]}', '{"status":"","hazards":["Long-period swell."]}', '{"status":7,"hazards":["Long-period swell."]}', undefined, null]) {
    assert.equal(lineOf(assessment), `${prefix}not assessed yet`, String(assessment));
  }
});

test('legacy unrecognized statuses keep their existing words and carry stored notes', () => {
  assert.equal(lineOf(assessed('constructor')), `${prefix}constructor`);
  assert.equal(lineOf(assessed('review-required', [BAR])), `${prefix}review-required Hazard note: ${BAR}`);
});

test('disabled records are omitted; unknown point ids never enter the preview', () => {
  assert.equal(compose([trip({enabled: 0})]).empty, true);
  const line = compose([trip({point: 'private-spot-id'})]).days[0].lines[0];
  assert.match(line, /^a saved spot · Rockfish/);
  assert.doesNotMatch(line, /private-spot-id/);
});

test('reusable plain text is stable, named, and contains no URL, address or record token', () => {
  const result = compose([trip({id: 'private-record-token', last_assessment: '{"status":"in-app"}'}), trip({date: '2026-11-08', point: 'z'})]);
  assert.equal(toText(result), '2026-11-07\nAlpha · Rockfish · 7:00–13:00 — shown here\n\n2026-11-08\nZulu · Rockfish · 7:00–13:00 — not assessed yet');
  assert.doesNotMatch(toText(result), /https?:|www\.|@|private-record-token|<[^>]*>/);
  for (const trips of [[], [trip({enabled: 0})], [trip({date: '2026-11-06'})]]) {
    const digest = compose(trips);
    assert.equal(digest.empty, true);
    assert.equal(toText(digest), EMPTY_WEEKEND);
  }
});

// Exercise the real signed-in preview with a loaded API answer, not a second renderer.
const dir = await mkdtemp(join(tmpdir(), 'weekend-digest-'));
const out = join(dir, 'preview.mjs');
await build({stdin: {resolveDir: new URL('..', import.meta.url).pathname, loader: 'ts', contents: `
  export {SignedIn} from './web/app/TripAlerts.tsx';
  export {h} from 'preact';
  export {render} from 'preact-render-to-string';`},
  bundle: true, format: 'esm', platform: 'node', outfile: out, logLevel: 'silent',
  jsx: 'automatic', jsxImportSource: 'preact', plugins: [{name: 'loaded-trips', setup(b) {
    b.onLoad({filter: /\/TripAlerts\.tsx$/}, async ({path}) => ({
      contents: (await readFile(path, 'utf8')).replace(
        'useState<{trips: SavedTrip[]; events: AlertEvent[]} | null>(null)',
        'useState<{trips: SavedTrip[]; events: AlertEvent[]} | null>(globalThis.digestAnswer ?? null)',
      ) + '\nexport {SignedIn};', loader: 'tsx',
    }));
  }}],
});
const ui = await import(pathToFileURL(out).href);
test.after(() => rm(dir, {recursive: true, force: true}));
test('signed-in loaded preview is above saved trips, escapes text, and never claims email delivery', () => {
  const region = {id: 'fixture', timezone: 'UTC', species: ['reef'], forecast_points: [{id: 'a', name: '<Alpha>'}]};
  const props = {session: {}, region, boat: {factors: {wind: 1, sea: 1}, saved: null}, target: null};
  const RealDate = Date;
  globalThis.Date = class extends RealDate { static now() { return RealDate.parse('2026-11-04T12:00:00Z'); } };
  try {
    for (const trips of [[], [trip()]]) {
      globalThis.digestAnswer = {trips, events: []};
      const html = ui.render(ui.h(ui.SignedIn, props));
      assert.ok(html.indexOf('This weekend') < html.indexOf('id="saved-trips"'));
      assert.match(html, /Shown here only; SkipperCast does not email this yet\./);
      assert.ok(html.includes(trips.length ? '&lt;Alpha> · reef · 7:00–13:00 — not assessed yet' : EMPTY_WEEKEND), html.slice(html.indexOf('<section'), html.indexOf('id="saved-trips"')));
    }
    globalThis.digestAnswer = {trips: [trip({last_assessment: assessed('within limits', ['<script>alert(1)</script> first', 'second & <b>note</b>'])})], events: []};
    const noted = ui.render(ui.h(ui.SignedIn, props));
    assert.ok(noted.includes('&lt;Alpha> · reef · 7:00–13:00 — within your saved limits Hazard note: &lt;script>alert(1)&lt;/script> first Hazard note: second &amp; &lt;b>note&lt;/b>'));
    assert.doesNotMatch(noted, /<script>|<b>note/);
    assert.match(noted, /Shown here only; SkipperCast does not email this yet\./);
    assert.equal(toText(weekendDigest(globalThis.digestAnswer.trips, {point: new Map([['a', '<Alpha>']]), species: new Map()}, '2026-11-04')),
      '2026-11-07\n<Alpha> · reef · 7:00–13:00 — within your saved limits Hazard note: <script>alert(1)</script> first Hazard note: second & <b>note</b>');
    delete globalThis.digestAnswer;
    assert.doesNotMatch(ui.render(ui.h(ui.SignedIn, props)), /This weekend|No saved trips this weekend/);
  } finally { globalThis.Date = RealDate; delete globalThis.digestAnswer; }
});
