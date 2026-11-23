// SCB2222-11 (docs/plans/live-region-announcements.md R4): saving an offline chart pack must not read every count aloud.
// The real PackStatus (the save display web/app/Trip.tsx's ChartPack renders) is server-rendered for a fake progress sequence; the real catalogue,
// statusText and sizeText run, and only the planner store boundary is a test-owned stub (same bundle boundary as test_trip_loading_status.mjs).
// Observed: markup and the accessible status text, not native speech output.
// Contract: the one role=status text is the phase label while saving (identical for every tick of a phase), the bar and the visible counts
// (outside any live region) follow every tick, and a terminal result replaces progress. Bug caught: counts inside the live status again.
import './helpers/spanish-ready.mjs';   // the Spanish table, before the Spanish renders
import assert from 'node:assert/strict';
import test from 'node:test';
import {mkdtemp} from 'node:fs/promises';
import {resolve} from 'node:path';
import {tmpdir} from 'node:os';
import {fileURLToPath, pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {preparedCatalogue} from './helpers/esbuild-url.mjs';

const root = fileURLToPath(new URL('../', import.meta.url));
const BOUNDARY = 'trip-announce-boundary';
const boundarySource = `
import {h} from 'preact';
export const region = {value: 'fixture-harbor'}, regionInfo = {value: {name: 'Fixture Harbor'}}, zone = () => 'UTC';
export const oceanLines = () => null, forecastEndLine = () => '';
export const tripOpen = {value: false}, tripError = {value: ''}, plannerView = {value: null}, tripReady = {value: false}, offlineOpen = {value: false};
export const Button = ({children}) => h('button', {type: 'button'}, children);
export const IconButton = () => null, useScrollCue = () => {}, PortDialog = ({children}) => h('div', {}, children), PositionCheck = () => null;
export const closeTrip = () => {}, loadPlanner = () => {};
export const listPacks = () => new Promise(() => {}), canSaveCoastal = async () => false, readCoastal = async () => null, deleteCoastal = async () => {}, saveCoastal = async () => {}, savePack = async () => ({});
export const KEEP_WORDS = {agreed: '', already: '', refused: '', unavailable: ''}, storageLine = async () => null, estimateWords = () => '', savePackKept = async save => ({meta: await save(), keep: 'unavailable'});
`;

async function load() {
  const dir = await mkdtemp(resolve(tmpdir(), 'trip-announce-'));
  const trip = resolve(root, 'web/app/Trip.tsx');
  await build({
    stdin: {resolveDir: root, loader: 'js', contents: `export {Trip, PackStatus} from './web/app/Trip.tsx'; export {language, t} from './web/i18n.ts'; export {sizeText} from './web/size-text.ts'; export {h} from 'preact'; export {render} from 'preact-render-to-string'; export * from '${BOUNDARY}';`},
    outfile: resolve(dir, 'trip.mjs'), bundle: true, format: 'esm', platform: 'node', jsx: 'automatic', jsxImportSource: 'preact', logLevel: 'silent',
    plugins: [preparedCatalogue, {name: 'trip-announce-boundary', setup(b) {
      const stubbed = ['../ui/Button.tsx', '../ui/scroll-cue.ts', '../landing/PortInput.tsx', '../state.ts', '../trip.ts', '../trip-ocean-lines.ts', '../trip-forecast-end.ts', './App.tsx', './PositionCheck.tsx'];
      b.onResolve({filter: /.*/}, args => {
        if (args.path === BOUNDARY || (args.importer === trip && stubbed.includes(args.path))) return {path: BOUNDARY, namespace: BOUNDARY};
      });
      b.onLoad({filter: /.*/, namespace: BOUNDARY}, () => ({contents: boundarySource, loader: 'js', resolveDir: root}));
    }}],
  });
  return import(pathToFileURL(resolve(dir, 'trip.mjs')).href);
}

const m = await load();
const view = (progress, status, lang) => m.render(m.h(m.PackStatus, {progress, status, lang}));
/** What a screen reader is told: the text of every role=status paragraph. */
const live = html => [...html.matchAll(/<p role="status" aria-live="polite">([^<]*)<\/p>/g)].map(x => x[1]);
/** What is only seen: the bar and the plain (non-live) paragraphs. */
const bar = html => { const x = /<progress[^>]*>/.exec(html)?.[0]; return x ? {max: /max="(\d+)"/.exec(x)?.[1], value: /value="(\d+)"/.exec(x)?.[1]} : null; };
const plain = html => [...html.matchAll(/<p>([^<]*)<\/p>/g)].map(x => x[1]);

for (const lang of ['en', 'es']) {
  const tiles = m.t('trip.phase.tiles', lang), shell = m.t('trip.phase.shell', lang);
  const count = (phase, p) => m.t('trip.progress', lang, {phase, done: p.done, total: p.total, bytes: m.sizeText(p.bytes, lang)});

  test(`pack_progress_same_phase_does_not_change_live_text_${lang}: two counts in one phase move the bar and visible counts, not the spoken text; the next phase changes it`, () => {
    const a = {phase: 'tiles', done: 10, total: 400, bytes: 51200}, b = {phase: 'tiles', done: 11, total: 400, bytes: 98304}, c = {phase: 'shell', done: 1, total: 6, bytes: 120000};
    const [ha, hb, hc] = [a, b, c].map(p => view(p, null, lang));
    assert.deepEqual(live(ha), [tiles], 'the live status is the phase label alone');
    assert.deepEqual(live(hb), live(ha), 'a second count in the same phase leaves the live text identical');
    assert.notEqual(ha, hb, 'the markup did change');
    assert.deepEqual(bar(ha), {max: '400', value: '10'});
    assert.deepEqual(bar(hb), {max: '400', value: '11'}, 'the bar follows the tick');
    assert.deepEqual(plain(ha), [count(tiles, a)], 'visible counts, outside the live region');
    assert.deepEqual(plain(hb), [count(tiles, b)], 'visible counts follow the tick');
    assert.ok(!live(ha)[0].includes('400') && !live(hb)[0].includes('98'), 'no count or byte figure is spoken');
    assert.deepEqual(live(hc), [shell], 'the next phase changes the live text');
    assert.notDeepEqual(live(hc), live(hb));
    assert.deepEqual(bar(hc), {max: '6', value: '1'});
  });

  test(`pack_progress_terminal_replaces_phase_${lang}: saved, failed, cancelled and deleted replace progress; an unknown phase is spoken as its own name`, () => {
    const p = {phase: 'basemap', done: 3, total: 9, bytes: 4096};
    const results = {
      saved: {id: 'trip.status.saved', vars: {name: 'Fixture Harbor'}, bytes: 2500000, missing: 0, keep: 'unavailable'},
      failed: {id: 'trip.status.failed', vars: {detail: 'disk full'}},
      cancelled: {id: 'trip.status.cancelled'},
      deleted: {id: 'trip.status.deleted'},
    };
    for (const [name, status] of Object.entries(results)) {
      const during = view(p, status, lang), after = view(null, status, lang);
      assert.deepEqual(live(during), [m.t('trip.phase.basemap', lang)], `${name}: while progress is present, only the phase is spoken`);
      const text = live(after);
      assert.equal(text.length, 1, `${name}: exactly one live status`);
      assert.ok(text[0].length > 0 && text[0] !== m.t('trip.phase.basemap', lang), `${name}: the result replaced the phase`);
      assert.ok(bar(after) === null && plain(after).length === 0, `${name}: no bar or counts linger after the result`);
    }
    assert.equal(live(view(null, results.saved, lang))[0], m.t('trip.status.saved', lang, {name: 'Fixture Harbor', bytes: m.sizeText(2500000, lang), missing: ''}));
    assert.ok(live(view(null, results.failed, lang))[0].includes('disk full'), 'the failure carries its reason');
    assert.equal(live(view(null, results.cancelled, lang))[0], m.t('trip.status.cancelled', lang));
    assert.equal(live(view(null, results.deleted, lang))[0], m.t('trip.status.deleted', lang));
    assert.deepEqual(live(view({phase: 'other-phase', done: 1, total: 2, bytes: 1}, null, lang)), ['other-phase']);
    assert.deepEqual(live(view(null, null, lang)), [''], 'idle: the status stays mounted and empty');
  });
}

test('pack_inventory_status_is_separate: the real ChartPack keeps its inventory checking status beside the save status', () => {
  m.offlineOpen.value = true;
  m.language.value = 'en';
  const spoken = live(m.render(m.h(m.Trip)));
  m.offlineOpen.value = false;
  assert.ok(spoken.includes(m.t('trip.checking', 'en')), 'the inventory status is still its own live status');
  assert.ok(spoken.includes(''), 'the save status is still mounted, empty when idle');
});
