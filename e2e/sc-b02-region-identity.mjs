// SC-B02 only. Real main/App, URL store, chooser, responsive shell and stage camera;
// synthetic deferred static responses and GPU-free renderer handles. No Worker,
// providers, shared test configuration or browser/dependency installation.
import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync, mkdirSync, writeFileSync} from 'node:fs';
import {resolve} from 'node:path';
import {build} from 'esbuild';
import {chromium, expect} from '@playwright/test';
import {rendererPlugins} from '../tests/helpers/esbuild-url.mjs';

const ROOT = resolve(import.meta.dirname, '..');
const EVIDENCE = resolve(ROOT, '../sc-b02-evidence');
const A = 'morro-bay', B = 'southern-california';
const META = {
  [A]: {name: 'Morro Bay synthetic', timezone: 'America/Los_Angeles', map: {center: [35.34, -120.97], local_areas: [{id: 'estero-bay', bounds: [-122, 34, -120, 36]}]}},
  [B]: {name: 'Southern California synthetic', timezone: 'Pacific/Honolulu', map: {center: [32.7, -117.2], local_areas: [{id: 'synthetic-south', bounds: [-119, 31, -116, 34]}]}},
};
const plan = (id, suffix = '') => ({region_id: id, profiles: {[`synthetic-${id}${suffix}`]: {name: `Plan ${id}${suffix}`, methods: ['boat']}}});
const CSS = ['web/tokens.css', 'web/ui/ui.css', 'web/app/app.css', 'web/landing/port-input.css', 'web/app/account.css', 'web/app/trip.css']
  .map(p => readFileSync(resolve(ROOT, p), 'utf8')).join('\n');

async function bundle() {
  const result = await build({
    stdin: {resolveDir: ROOT, loader: 'ts', contents: `
      import './web/app/main.tsx';
      import * as app from './web/app/App.tsx';
      import * as state from './web/state.ts';
      import * as plans from './web/species.ts';
      import {camera, terrainActions} from './web/map/stage.ts';
      import {effect} from '@preact/signals';
      import {aerialOffer} from './web/map/aerial.ts';
      const moves = [];
      effect(() => { const c = camera.value; if(c) moves.push({...c}); });
      globalThis.__b02 = {app, state, plans, camera, terrainActions, moves,
        place: () => globalThis.__b02Chart?.place?.() ?? null, aerial: () => aerialOffer.value};
    `},
    bundle: true, write: false, format: 'iife', platform: 'browser', logLevel: 'silent',
    jsx: 'automatic', jsxImportSource: 'preact', plugins: [{name: 'sc-b02-renderer-handles', setup(b) {
      // Trip's lazy GPU import is not reached by these identity scenarios.
      b.onResolve({filter: /^\.\/map\/maplibre\.js$/}, args =>
        args.importer === resolve(ROOT, 'web/trip.ts') ? {path: args.path, external: true} : undefined);
      // Preserve the real chart's exports; replace only its hardware factory.
      b.onLoad({filter: /web\/map\/chart\.ts$/}, args => ({loader: 'ts', contents:
        readFileSync(args.path, 'utf8').replace('export function createChart(options:', 'function unusedCreateChart(options:') +
        '\nexport function createChart(options) { globalThis.__b02Chart = options; const aerial = options.layers[3](signal(null)); return {destroy() { aerial.destroy(); }}; }'}));
      b.onResolve({filter: /^\.\/terrain\.js$/}, () => ({path: 'sc-b02-terrain', namespace: 'sc-b02'}));
      b.onLoad({filter: /.*/, namespace: 'sc-b02'}, () => ({loader: 'js', contents: `
        export const styles = [];
        export function mountCoast(host, options) {
          globalThis.__b02Terrain = options;
          return new Proxy({load: async () => true, destroy() {}}, {get(target, name) {
            return target[name] ?? (() => true);
          }});
        }
      `}));
    }}, ...rendererPlugins],
  });
  return result.outputFiles[0].text;
}

// Ignores abort intentionally: a shared request and JSON body can outlive a caller.
function installDeferredFetch() {
  const reads = [];
  globalThis.__reads = reads;
  globalThis.fetch = async (input, init = {}) => {
    const url = new URL(String(input), location.href);
    const match = url.pathname.match(/\/regions\/([^/]+)\/(region|search-plan-index|search-plans)\.json$/);
    if (match) return new Promise(resolve => reads.push({id: match[1], kind: match[2], init, resolve, done: false}));
    if (url.pathname.endsWith('/home-ports.json')) return new Response(JSON.stringify({schema_version: 1, ports: [
      {id: 'morro-bay', name: 'Morro Bay', region: 'morro-bay', status: 'active', forecast_point: 'a', forecast_name: 'A synthetic', match: [35.34, -120.97]},
      {id: 'san-diego', name: 'San Diego', region: 'southern-california', status: 'preview', forecast_point: 'b', forecast_name: 'B synthetic', match: [32.7, -117.2]},
    ]}), {status: 200});
    return new Response('{}', {status: 404});
  };
  globalThis.__answer = (kind, id, index, body, status = 200, stallBody = false) => {
    const r = reads.filter(r => r.kind === kind && r.id === id)[index];
    if (!r || r.done) throw new Error(`Missing/answered ${kind} ${id} ${index}`);
    r.done = true;
    if (stallBody) {
      r.resolve({ok: true, json: () => new Promise(resolve => { r.bodyResolve = resolve; }), clone() { return this; }});
    } else r.resolve(new Response(JSON.stringify(body), {status}));
  };
}

const count = (page, kind, id) => page.evaluate(({kind, id}) => __reads.filter(r => r.kind === kind && r.id === id).length, {kind, id});
async function waitRead(page, kind, id, n = 1) { await expect.poll(() => count(page, kind, id)).toBe(n); }
async function answer(page, kind, id, n = 0, body = META[id], status = 200, stallBody = false) {
  await page.evaluate(args => __answer(...args), [kind, id, n, body, status, stallBody]);
}
async function snapshot(page) {
  return page.evaluate(() => ({region: __b02.state.region.value, info: __b02.app.currentRegionInfo(), raw: __b02.app.regionInfo.value,
    zone: __b02.app.zone(), load: __b02.app.regionLoad.value, plans: __b02.plans.regionPlans.value,
    camera: __b02.camera.value, moves: __b02.moves.length, place: __b02.place(), aerial: __b02.aerial()}));
}
async function current(page, id, suffix = '') {
  await expect.poll(async () => (await snapshot(page)).info?.id).toBe(id);
  await expect(page.locator('.app-location')).toContainText(META[id].name);
  await expect.poll(async () => (await snapshot(page)).plans?.region).toBe(id);
  const s = await snapshot(page);
  assert.equal(new URL(page.url()).searchParams.get('region'), id);
  assert.equal(s.region, id);
  assert.equal(s.zone, META[id].timezone);
  assert.equal(s.camera.latitude, META[id].map.center[0]);
  assert.equal(s.camera.longitude, META[id].map.center[1]);
  assert.equal(s.place.regionId, id);
  assert.deepEqual(s.place.point, {latitude: META[id].map.center[0], longitude: META[id].map.center[1]});
  assert.deepEqual(s.place.localAreas, META[id].map.local_areas);
  if (s.plans) {
    assert.equal(s.plans.region, id);
    await expect(page.getByRole('option', {name: `Plan ${id}${suffix}`, exact: true})).toHaveCount(1);
  }
}
async function unavailable(page, id, state = 'loading') {
  await expect.poll(async () => (await snapshot(page)).load?.state).toBe(state);
  const s = await snapshot(page);
  assert.equal(s.region, id);
  assert.equal(s.info, null);
  assert.equal(s.raw, null);
  assert.equal(s.place, null);
  assert.equal(s.zone, __DEFAULT_ZONE);
  await expect(page.locator('.app-location')).not.toContainText('synthetic');
  await expect(page.getByRole('status').filter({hasText: state === 'error' ? 'Region details unavailable.' : 'Loading region…'})).toHaveCount(1);
}
const __DEFAULT_ZONE = 'America/Los_Angeles';
async function choose(page, id) {
  // The actual chooser: keyboard opens it; its selected option writes the URL.
  const control = page.getByRole('button', {name: /^(Choose port|Change port \()/});
  await control.focus();
  await page.keyboard.press('Enter');
  const dialog = page.getByRole('dialog', {name: 'Change port'});
  await expect(dialog).toBeVisible();
  await dialog.locator(`[data-port="${id === A ? 'morro-bay' : 'san-diego'}"]`).click();
  await expect(dialog).not.toBeVisible();
  await expect.poll(() => new URL(page.url()).searchParams.get('region')).toBe(id);
}

// Retain layout geometry beside (not among) the eighteen identity snapshots.
async function controlEvidence(page, viewportName, phase) {
  const bounds = await page.evaluate(() => {
    const rect = element => {
      if (!element) return null;
      const {x, y, width, height, top, right, bottom, left} = element.getBoundingClientRect();
      return {x, y, width, height, top, right, bottom, left};
    };
    const stage = document.querySelector('.app-stage');
    const rail = stage.querySelector(':scope > .app-rail');
    const controls = stage.querySelector('.app-terrain-controls');
    return {stage: rect(stage), rail: rect(rail), controls: rect(controls),
      gap: parseFloat(getComputedStyle(stage).getPropertyValue('--space-3')),
      scroll: rail ? {top: rail.scrollTop, height: rail.scrollHeight, clientHeight: rail.clientHeight} : null,
      note: rect(rail?.querySelector('#app-rail-base-note')),
      buttons: [...controls.querySelectorAll('button')].map(button => {
        const box = rect(button), hit = document.elementFromPoint(box.x + box.width / 2, box.y + box.height / 2);
        return {label: button.getAttribute('aria-label'), ...box, receivesPointer: hit === button || button.contains(hit)};
      })};
  });
  const directory = resolve(EVIDENCE, 'control-bounds');
  mkdirSync(directory, {recursive: true});
  writeFileSync(resolve(directory, `${viewportName}-${phase}.json`), JSON.stringify(bounds, null, 2));
  await page.screenshot({path: resolve(directory, `${viewportName}-${phase}.png`)});
  if (viewportName === 'laptop') {
    assert.ok(bounds.rail.bottom + bounds.gap <= bounds.controls.top + 1, 'rail leaves a gap above the complete terrain control stack');
    assert.deepEqual(bounds.buttons.map(button => button.label), ['Zoom in', 'Zoom out', 'Reset map view', 'View from above']);
    for (const button of bounds.buttons) assert.equal(button.receivesPointer, true, `${button.label} receives an ordinary pointer click`);
  }
  return bounds;
}

// Exercise every real basis disclosure without changing its native open state
// programmatically. Long bodies may scroll vertically; every line must fit
// horizontally and be reachable within the rail's actual scroll range.
async function disclosureEvidence(page) {
  const rail = page.locator('.app-stage > .app-rail');
  const directory = resolve(EVIDENCE, 'disclosure-bounds');
  mkdirSync(directory, {recursive: true});
  const labels = ['Seafloor basis', 'Currents basis', 'Water temp basis', 'Swell basis', 'Charter fleet basis', 'Clouds basis', 'Base basis'];
  await expect(rail.locator('.ui-popover')).toHaveCount(7);
  for (const [index, label] of labels.entries()) {
    // aria-label is on summary itself, including Base's icon-only trigger.
    const trigger = rail.locator(`summary[aria-label="${label}"]`);
    const details = rail.locator(`.ui-popover:has(> summary[aria-label="${label}"])`);
    await trigger.focus();
    await expect(trigger).toBeFocused();
    await page.keyboard.press('Enter');
    await expect(details).toHaveAttribute('open', '');
    const body = details.locator('.ui-popover-body');
    await expect(body).toBeVisible();
    const bounds = await body.evaluate(element => {
      const rail = element.closest('.app-rail'), box = rail.getBoundingClientRect();
      const left = box.left + rail.clientLeft, top = box.top + rail.clientTop;
      const walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT);
      const lines = [];
      while (walker.nextNode()) {
        if (!walker.currentNode.textContent.trim()) continue;
        const range = document.createRange(); range.selectNodeContents(walker.currentNode);
        for (const r of range.getClientRects()) lines.push({left: r.left, right: r.right,
          start: r.top - top + rail.scrollTop, end: r.bottom - top + rail.scrollTop});
      }
      return {text: element.textContent, left, right: left + rail.clientWidth,
        clientHeight: rail.clientHeight, scrollHeight: rail.scrollHeight,
        scrollWidth: rail.scrollWidth, clientWidth: rail.clientWidth, lines};
    });
    assert.ok(bounds.text.trim().length > 30, `${label}: explanation retained`);
    assert.ok(bounds.lines.length > 0, `${label}: rendered text lines`);
    assert.ok(bounds.scrollWidth <= bounds.clientWidth + 1, `${label}: no horizontal clipping or scrolling`);
    for (const line of bounds.lines) {
      assert.ok(line.left >= bounds.left - 1 && line.right <= bounds.right + 1, `${label}: complete line fits horizontally`);
      assert.ok(line.start >= 0 && line.end <= bounds.scrollHeight + 1, `${label}: complete line reachable vertically`);
    }
    // Scroll the beginning into view, then let native Tab reveal the source link.
    await rail.evaluate((element, start) => { element.scrollTop = start; }, Math.max(0, bounds.lines[0].start - 4));
    await page.screenshot({path: resolve(directory, `laptop-${index}-start.png`)});
    await page.keyboard.press('Tab');
    const source = body.getByRole('link', {name: 'How it’s built'});
    await expect(source).toBeFocused();
    await expect(source).toBeInViewport({ratio: 1});
    await controlEvidence(page, 'laptop', `disclosure-${index}-open`);
    await page.screenshot({path: resolve(directory, `laptop-${index}-end.png`)});
    writeFileSync(resolve(directory, `laptop-${index}.json`), JSON.stringify({label, ...bounds}, null, 2));
    await trigger.focus();
    await page.keyboard.press('Space');
    await expect(details).not.toHaveAttribute('open');
  }
}

// One invocation, serial subcases. Stop creating subcases at the first failure.
test('SC-B02 focused region identity acceptance', {timeout: 180_000}, async t => {
  mkdirSync(EVIDENCE, {recursive: true});
  const script = await bundle();
  const browser = await chromium.launch({headless: true});
  t.after(() => browser.close());
  let failed = false;
  for (const [name, viewport] of [['phone', {width: 390, height: 844}], ['laptop', {width: 1280, height: 800}]]) {
    for (const scenario of ['B then A', 'A then B', 'A B A', 'failed B', 'stalled B headers', 'stalled B body', 'plan fallback', 'same-id generation', 'consumer identity and reset']) {
      if (failed) return;
      await t.test(`${name}: ${scenario}`, async () => {
        const context = await browser.newContext({viewport, serviceWorkers: 'block'});
        const page = await context.newPage();
        const errors = [];
        page.on('pageerror', error => errors.push(String(error)));
        try {
          await context.route('**/*', route => {
            if (route.request().resourceType() === 'document') return route.fulfill({contentType: 'text/html', body:
              `<!doctype html><html lang="en"><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>SC-B02</title><style>${CSS}</style></head><body><div id="app"></div><script>${script.replaceAll('</script', '<\\/script')}</script></body></html>`});
            return route.abort('blockedbyclient');
          });
          await page.addInitScript(installDeferredFetch);
          await page.addInitScript(() => localStorage.setItem('skippercast-first-run-v1', 'done'));
          await page.goto(`http://sc-b02.test/map?ui=v2&region=${A}&profile=boat&layers=none&base=night`);
          await waitRead(page, 'region', A);
          await waitRead(page, 'search-plan-index', A);
          // Preact's MapStage effect has installed the real stage and captured report-place callback.
          await expect.poll(() => page.evaluate(() => !!globalThis.__b02Chart)).toBe(true);
          if (scenario === 'same-id generation') {
            // Inject a new uncached read while the first same-id request is still pending.
            await page.evaluate(() => { void __b02.app.loadRegion('morro-bay', fetch); void __b02.plans.loadPlans('morro-bay'); });
            await waitRead(page, 'region', A, 2);
            await waitRead(page, 'search-plan-index', A, 2);
            await answer(page, 'region', A, 1);
            await answer(page, 'search-plan-index', A, 1, plan(A, '-new'));
            await current(page, A, '-new');
            const before = await snapshot(page);
            await answer(page, 'region', A, 0, {...META[A], name: 'OBSOLETE', map: {center: [1, 2]}});
            await answer(page, 'search-plan-index', A, 0, plan(A, '-old'));
            await page.evaluate(() => new Promise(resolve => setTimeout(resolve, 0)));
            await current(page, A, '-new');
            assert.equal((await snapshot(page)).moves, before.moves);
          } else if (scenario === 'consumer identity and reset') {
            await answer(page, 'region', A);
            await answer(page, 'search-plan-index', A, 0, plan(A));
            await current(page, A);
            const before = await snapshot(page);
            // Invoke the real aerial factory through MapStage's registered callback; its engine is null, so no tiles/GPU run.
            const aerial = {source: 'usgs-naip', first: '2022-05-13', last: '2022-05-29', checkedAt: '2026-10-01', note: 'Synthetic dated imagery', byDefault: false};
            await page.evaluate(({info, aerial}) => { __b02.app.regionInfo.value = {...info, aerial}; }, {info: before.info, aerial});
            await expect.poll(async () => (await snapshot(page)).aerial).toEqual(aerial);
            await page.evaluate(aerial => { __b02.app.regionInfo.value = {id: 'southern-california', name: 'OBSOLETE', center: [1, 2], timezone: 'Pacific/Honolulu', aerial}; }, aerial);
            await expect(page.locator('.app-location')).not.toContainText('OBSOLETE');
            const guarded = await snapshot(page);
            assert.equal(guarded.info, null); assert.equal(guarded.place, null); assert.equal(guarded.zone, __DEFAULT_ZONE);
            assert.equal(guarded.aerial, null, 'real aerial callback withdraws another region’s offer');
            assert.equal(guarded.moves, before.moves);
            await page.evaluate(info => { __b02.app.regionInfo.value = info; }, before.info);
            await expect.poll(async () => (await snapshot(page)).aerial).toBe(null);
            await page.getByRole('button', {name: '2D', exact: true}).click();
            await expect(page.getByRole('button', {name: 'Reset map view', exact: true})).toBeVisible();
            await controlEvidence(page, name, 'before-reset');
            if (name === 'laptop') {
              const note = page.locator('.app-stage > .app-rail #app-rail-base-note');
              await expect(note).toHaveText('Chart only');
              await note.scrollIntoViewIfNeeded();
              await expect(note).toBeInViewport();
              const scrolled = await controlEvidence(page, name, 'rail-scrolled');
              assert.ok(scrolled.scroll.top > 0, 'the complete rail remains reachable by scrolling');
              assert.ok(scrolled.note.top >= scrolled.rail.top && scrolled.note.bottom <= scrolled.rail.bottom, 'the base note stays readable inside the scrolled rail');
            }
            await page.evaluate(() => __b02.state.setParams({view: '34,-119,11'}));
            await expect.poll(async () => (await snapshot(page)).camera.latitude).toBe(34);
            await page.getByRole('button', {name: 'Reset map view', exact: true}).click();
            await current(page, A);
            assert.match(new URL(page.url()).searchParams.get('view'), /^35\.34000,-120\.97000,/);
            await controlEvidence(page, name, 'after-reset');
            if (name === 'laptop') await disclosureEvidence(page);
          } else {
            if (scenario === 'failed B' || scenario.startsWith('stalled B')) {
              await answer(page, 'region', A); await answer(page, 'search-plan-index', A, 0, plan(A)); await current(page, A);
            }
            await choose(page, B);
            await waitRead(page, 'region', B);
            await waitRead(page, 'search-plan-index', B);
            await unavailable(page, B);
            if (scenario === 'B then A' || scenario === 'A then B') {
              if (scenario === 'A then B') {
                const before = await snapshot(page);
                await answer(page, 'region', A); await answer(page, 'search-plan-index', A, 0, plan(A));
                await page.evaluate(() => new Promise(resolve => setTimeout(resolve, 0)));
                await unavailable(page, B);
                assert.equal((await snapshot(page)).moves, before.moves);
              }
              await answer(page, 'region', B); await answer(page, 'search-plan-index', B, 0, plan(B)); await current(page, B);
              if (scenario === 'B then A') {
                const before = await snapshot(page);
                await answer(page, 'region', A); await answer(page, 'search-plan-index', A, 0, plan(A));
                await page.evaluate(() => new Promise(resolve => setTimeout(resolve, 0)));
                await current(page, B); assert.equal((await snapshot(page)).moves, before.moves);
              }
              // Actual popstate: Back awaits A metadata; Forward reuses B's static metadata.
              await page.goBack();
              await expect.poll(() => new URL(page.url()).searchParams.get('region')).toBe(A);
              await waitRead(page, 'search-plan-index', A, 2);
              await answer(page, 'search-plan-index', A, 1, plan(A)); await current(page, A);
              await page.goForward();
              await waitRead(page, 'search-plan-index', B, 2);
              await answer(page, 'search-plan-index', B, 1, plan(B)); await current(page, B);
            } else if (scenario === 'A B A') {
              await choose(page, A);
              await waitRead(page, 'search-plan-index', A, 2);
              await answer(page, 'region', A); await answer(page, 'search-plan-index', A, 1, plan(A, '-new')); await current(page, A, '-new');
              const before = await snapshot(page);
              await answer(page, 'region', B); await answer(page, 'search-plan-index', B, 0, plan(B)); await answer(page, 'search-plan-index', A, 0, plan(A, '-old'));
              await page.evaluate(() => new Promise(resolve => setTimeout(resolve, 0)));
              await current(page, A, '-new'); assert.equal((await snapshot(page)).moves, before.moves);
            } else if (scenario === 'plan fallback') {
              await answer(page, 'region', B);
              await answer(page, 'search-plan-index', B, 0, {}, 404);
              await waitRead(page, 'search-plans', B);
              await answer(page, 'search-plans', B, 0, plan(B));
              await current(page, B);
              // Preserve loadPlans' explicit-ID API without exposing another region's targets.
              const direct = await page.evaluate(async data => {
                await __b02.plans.loadPlans(data.region_id, async () => new Response(JSON.stringify(data)));
                return __b02.plans.regionPlans.value;
              }, plan(A, '-direct'));
              assert.equal(direct.region, A);
              await expect(page.getByRole('option', {name: `Plan ${A}-direct`, exact: true})).toHaveCount(0);
              await page.evaluate(() => { void __b02.plans.loadPlans('southern-california'); });
              await waitRead(page, 'search-plan-index', B, 2);
              await answer(page, 'search-plan-index', B, 1, plan(B));
              await current(page, B);
            } else {
              if (scenario === 'failed B') {
                await answer(page, 'region', B, 0, {}, 503);
                await answer(page, 'search-plan-index', B, 0, {}, 503);
                await waitRead(page, 'search-plans', B);
                await answer(page, 'search-plans', B, 0, {}, 503);
              } else {
                // Deterministic fake time after actual metadata headers have arrived;
                // both body and plan stalls must terminate without a real 10 s sleep.
                await page.clock.install();
                // Existing timers predate install, so restart B's uncached read under this clock.
                await page.evaluate(() => { void __b02.app.loadRegion('southern-california', fetch); void __b02.plans.loadPlans('southern-california'); });
                await waitRead(page, 'region', B, 2);
                if (scenario === 'stalled B body') await answer(page, 'region', B, 1, {}, 200, true);
                await page.clock.runFor(10_001);
              }
              await unavailable(page, B, 'error');
              assert.equal((await snapshot(page)).plans, null);
              await expect(page.getByRole('option', {name: `Plan ${A}`, exact: true})).toHaveCount(0);
              const before = await snapshot(page);
              if (scenario === 'stalled B body') {
                await page.evaluate(() => { __reads.filter(r => r.kind === 'region' && r.id === 'southern-california')[1].bodyResolve({name:'LATE BODY', map:{center:[1,2]}}); });
                await page.clock.runFor(1);
                await unavailable(page, B, 'error'); assert.equal((await snapshot(page)).moves, before.moves);
              }
              if (scenario.startsWith('stalled B')) {
                if (scenario === 'stalled B headers') await answer(page, 'region', B, 1, {...META[B], name: 'LATE HEADERS'});
                await answer(page, 'search-plan-index', B, 1, plan(B, '-late'));
                await page.clock.runFor(1);
                await unavailable(page, B, 'error');
                assert.equal((await snapshot(page)).plans, null);
                assert.equal((await snapshot(page)).moves, before.moves);
              }
              await page.getByRole('button', {name: 'Retry region details', exact: true}).click();
              const n = scenario === 'failed B' ? 1 : 2;
              await waitRead(page, 'region', B, n + 1);
              assert.equal(await page.evaluate(n => __reads.filter(r => r.kind === 'region' && r.id === 'southern-california')[n].init.cache, n), 'reload');
              await answer(page, 'region', B, n); await answer(page, 'search-plan-index', B, n, plan(B));
              if (scenario.startsWith('stalled B')) await page.clock.runFor(32);
              await current(page, B);
              // Revisit the recovered region after retry; the poisoned original shared read must not return.
              await choose(page, A);
              await waitRead(page, 'search-plan-index', A, 2);
              await answer(page, 'search-plan-index', A, 1, plan(A));
              await current(page, A);
              await page.goBack();
              await expect.poll(() => new URL(page.url()).searchParams.get('region')).toBe(B);
              await waitRead(page, 'search-plan-index', B, n + 2);
              await answer(page, 'search-plan-index', B, n + 1, plan(B));
              if (scenario.startsWith('stalled B')) await page.clock.runFor(32);
              await current(page, B);
              assert.equal(await count(page, 'region', B), n + 1, 'revisit reuses successful retry metadata instead of the stalled original');
            }
          }
          assert.deepEqual(errors, [], 'no uncaught browser errors');
          writeFileSync(resolve(EVIDENCE, `${name}-${scenario.replaceAll(' ', '-')}.json`), JSON.stringify(await snapshot(page), null, 2));
          if (scenario === 'failed B') await page.screenshot({path: resolve(EVIDENCE, `${name}-retry-success.png`)});
        } catch (error) {
          failed = true;
          writeFileSync(resolve(EVIDENCE, `${name}-${scenario.replaceAll(' ', '-')}-failure.txt`), String(error.stack ?? error));
          await page.screenshot({path: resolve(EVIDENCE, `${name}-failure.png`)}).catch(() => {});
          throw error;
        } finally { await context.close(); }
      });
    }
  }
});
