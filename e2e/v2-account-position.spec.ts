// SC1607-06: real account dialog and serializers, synthetic owner APIs and planning screen only.
// No app bootstrap/product network is needed: every browser request is answered or refused here.
import {test, expect, type Page, type Route} from '@playwright/test';
import {build} from 'esbuild';
import {readFileSync} from 'node:fs';

let script: string;
test.beforeAll(async () => {
  const result = await build({entryPoints: ['dist/account.js'], bundle: true, write: false, format: 'iife', globalName: 'Account', plugins: [{
    name: 'synthetic-account-context', setup(b) {
      b.onResolve({filter: /\/(protected-areas|region)\.js$/}, args => ({path: args.path, namespace: 'account-fixture'}));
      b.onLoad({filter: /.*/, namespace: 'account-fixture'}, args => ({contents: args.path.includes('protected-areas')
        ? 'export const initProtectedAreas = () => globalThis.__screenWait ?? null;'
        : 'export const getRegion = () => null;', loader: 'js'}));
    },
  }]});
  script = result.outputFiles[0]!.text;
});
const spots = [
  {id: 'zero"<&', name: ' \u0000<svg onload="x"> ', lat: 0, lon: 0, note: 'PRIVATE-SPOT-NOTE'},
  {id: 'precise', name: '\u001f', lat: 35.123456789, lon: -120.987654321, note: 'ANOTHER-PRIVATE-NOTE'},
];
const entry = {id: 'e1', started_at: '2026-01-01T00:00:00Z', ended_at: null, outcome: 'blank', count: 0, lat: 12, lon: -34, note: 'entry note', species: null, method: null, trip_id: null};
async function setup(page: Page, options: {rows?: unknown; failure?: number | 'network'; hold?: boolean; screenWait?: boolean; es?: boolean} = {}) {
  const state = {rows: options.rows ?? spots, reads: 0, writes: [] as {method: string; body: Record<string, unknown>}[], held: [] as Route[], holdNext: false, unexpected: [] as string[], failure: options.failure};
  await page.route('**/*', async route => {
    const req = route.request(), path = new URL(req.url()).pathname, method = req.method();
    if (path === '/account-choice-fixture') return route.fulfill({contentType: 'text/html', body: '<!doctype html><html><body><button id="previous">Previous</button></body></html>'});
    if (path === '/api/session') return route.fulfill({json: {signedIn: true, signIn: '/#account', user: {display_name: 'Synthetic skipper'}}});
    if (path === '/api/auth/passkeys') return route.fulfill({json: {passkeys: []}});
    if (path === '/api/auth/sessions') return route.fulfill({json: {sessions: [{current: true, device: 'Fixture', created_at: '2026-01-01T00:00:00Z', expires_at: 2000000000}]}});
    if (path === '/api/trips') return route.fulfill({json: {trips: []}});
    if (path === '/api/spots' && method === 'GET') {
      state.reads++;
      if ((options.hold && state.reads === 1) || state.holdNext) { state.holdNext = false; state.held.push(route); return; }
      if (state.failure === 'network') return route.abort();
      return route.fulfill({status: state.failure ?? 200, json: state.failure ? {error: 'Synthetic read failed'} : {spots: state.rows}});
    }
    if (path === '/api/spots' && method === 'POST') return route.fulfill({json: {id: 'new'}});
    if (path.startsWith('/api/spots/') && method === 'DELETE') return route.fulfill({json: {ok: true}});
    if (path === '/api/catch-log' && method === 'GET') return route.fulfill({json: {entries: [entry]}, headers: {'X-SC-Catch-Log-Has-More': 'false'}});
    if (path.startsWith('/api/catch-log') && (method === 'POST' || method === 'PATCH')) {
      const body = req.postDataJSON(); state.writes.push({method, body});
      return route.fulfill({json: {...entry, ...body}});
    }
    state.unexpected.push(`${method} ${path}`); return route.abort();
  });
  await page.goto('/account-choice-fixture');
  await page.addScriptTag({content: script});
  await page.evaluate(wait => {
    const w = window as any; w.__geo = []; w.__calls = 0;
    Object.defineProperty(navigator, 'geolocation', {value: {getCurrentPosition(ok: unknown, fail: unknown) { w.__geo.push({ok, fail}); w.__calls++; }}});
    if (wait) w.__screenWait = new Promise(resolve => { w.__releaseScreen = () => resolve(null); });
  }, options.screenWait ?? false);
  const strings = options.es ? Object.fromEntries(Object.entries(JSON.parse(readFileSync('catalog/app/strings.json', 'utf8')).strings).map(([id, value]) => [id, (value as {es: string}).es])) : {};
  await page.evaluate(opts => (window as any).Account.openAccount(opts), {lang: options.es ? 'es' : 'en', strings});
  await expect(page.locator('#log-save')).toBeVisible();
  return state;
}
const choose = (page: Page, id: string) => page.locator('#log-spot').selectOption(id);
async function refresh(page: Page) {
  await page.locator('#spot-name').fill('Synthetic new spot'); await page.locator('#spot-lat').fill('1'); await page.locator('#spot-lon').fill('2');
  await page.locator('#spot-save').click();
}

test('saved_spot_choice_fills_only_coordinates; escaped names, none, manual input and exact Save bytes', async ({page}) => {
  const state = await setup(page);
  await expect(page.locator('#log-spot-choice')).toBeVisible();
  await expect(page.locator('#log-spot option').nth(1)).toHaveText('<svg onload="x">');
  await expect(page.locator('#log-spot option').nth(2)).toHaveText('Unnamed spot');
  await expect(page.locator('#log-spot svg')).toHaveCount(0);
  expect(await page.locator('#log-spot-choice').innerHTML()).not.toContain('PRIVATE');
  await page.locator('#log-note').fill('my own note'); await page.locator('#log-species').fill('my species');
  await choose(page, spots[0]!.id); await expect(page.locator('#log-lat')).toHaveValue('0');
  await choose(page, 'precise'); await expect(page.locator('#log-lat')).toHaveValue('35.123456789');
  await expect(page.locator('#log-lon')).toHaveValue('-120.987654321'); await expect(page.locator('#log-lat')).toBeEditable();
  await choose(page, ''); await expect(page.locator('#log-lat')).toHaveValue('35.123456789');
  await choose(page, 'precise'); await page.locator('#log-lat').fill('36'); await expect(page.locator('#log-spot')).toHaveValue('');
  await expect(page.locator('#log-lon')).toHaveValue('-120.987654321'); await expect(page.locator('#log-species')).toHaveValue('my species');
  expect(state.writes).toHaveLength(0); expect(await page.evaluate(() => (window as any).__calls)).toBe(0); expect(state.reads).toBe(1);
  await page.locator('#log-save').click(); await expect.poll(() => state.writes.length).toBe(1);
  expect(state.writes[0]!.body).toEqual({started_at: expect.any(String), outcome: 'blank', method: null, species: 'my species', note: 'my own note', lat: 36, lon: -120.987654321});
  await expect(page.locator('#log-spot')).toHaveValue(''); expect(state.unexpected).toEqual([]);
});

test('saved_spot_failed_empty_or_malformed_read_keeps_form_usable', async ({page}) => {
  for (const input of [{failure: 401}, {failure: 500}, {failure: 'network' as const}, {rows: []}, {rows: [spots[0], spots[0]]}, {rows: [{...spots[0], lat: 90}]}]) {
    const state = await setup(page, input); await expect.poll(() => state.reads).toBe(1);
    await expect(page.locator('#log-spot-choice')).toBeHidden(); await page.locator('#log-note').fill('positionless');
    await page.locator('#log-save').click(); await expect.poll(() => state.writes.length).toBe(1);
    expect(state.writes[0]!.body.lat).toBeNull(); expect(state.writes[0]!.body.lon).toBeNull(); expect(state.writes[0]!.body.note).toBe('positionless');
    expect(await page.evaluate(() => (window as any).__calls)).toBe(0); expect(state.unexpected).toEqual([]);
    await page.unrouteAll({behavior: 'wait'});
  }
});

test('saved_spot_and_device_fix_last_deliberate_source_wins', async ({page}) => {
  await setup(page); await expect(page.locator('#log-spot-choice')).toBeVisible();
  await page.locator('#log-use-position').click(); await expect(page.locator('#log-save')).toBeDisabled();
  await choose(page, 'precise'); await expect(page.locator('#log-save')).toBeEnabled();
  await page.evaluate(() => (window as any).__geo[0].ok({coords: {latitude: 1, longitude: 2, accuracy: 3}}));
  await expect(page.locator('#log-lat')).toHaveValue('35.123456789'); await expect(page.locator('#log-position-status')).toHaveText('');
  await page.locator('#log-use-position').click();
  await page.evaluate(() => (window as any).__geo[1].ok({coords: {latitude: 3, longitude: 4, accuracy: 5}}));
  await expect(page.locator('#log-lat')).toHaveValue('3.000000'); await expect(page.locator('#log-spot')).toHaveValue('');
  await expect(page.locator('#log-position-status')).toContainText('5 m');
});

test('saved_spot_choice_survives_refresh_without_refilling; failed screening is independent', async ({page}) => {
  const state = await setup(page, {screenWait: true});
  await expect(page.locator('#log-spot-choice')).toBeVisible(); await choose(page, 'precise');
  state.rows = [{...spots[1], name: 'Renamed', lat: 10}]; await refresh(page); await expect.poll(() => state.reads).toBe(2);
  await expect(page.locator('#log-spot option:checked')).toHaveText('Renamed'); await expect(page.locator('#log-lat')).toHaveValue('35.123456789');
  await page.evaluate(() => (window as any).__releaseScreen()); await expect(page.locator('#spot-list')).toContainText('Protected areas not checked');
  state.rows = [spots[0]]; await refresh(page); await expect(page.locator('#log-spot option')).toHaveCount(2);
  await expect(page.locator('#log-spot')).toHaveValue(''); await expect(page.locator('#log-lat')).toHaveValue('35.123456789');
  state.failure = 500; await refresh(page); await expect(page.locator('#log-spot-choice')).toBeHidden(); await expect(page.locator('#log-lat')).toHaveValue('35.123456789');
});

test('saved_spot_late_read_cannot_replace_newer_options_or_reopened_dialog', async ({page}) => {
  const state = await setup(page, {hold: true}); await expect.poll(() => state.held.length).toBe(1);
  await page.locator('#log-lat').fill('7'); state.rows = [spots[1]]; await refresh(page);
  await expect(page.locator('#log-spot option')).toHaveCount(2); await state.held[0]!.fulfill({json: {spots: [spots[0]]}});
  await expect(page.locator('#log-spot option').nth(1)).toHaveAttribute('value', 'precise'); await expect(page.locator('#log-lat')).toHaveValue('7');
  state.holdNext = true; await refresh(page); await expect.poll(() => state.held.length).toBe(2);
  await page.locator('.home-port-close').click();
  await page.evaluate(() => (window as any).Account.openAccount());
  await expect(page.locator('#log-spot option').nth(1)).toHaveAttribute('value', 'precise');
  await state.held[1]!.fulfill({json: {spots: [spots[0]]}});
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  await expect(page.locator('#log-spot option').nth(1)).toHaveAttribute('value', 'precise');
  await expect(page.locator('#log-lat')).toHaveValue(''); await expect(page.locator('#log-spot')).toHaveValue('');
});

test('saved_spot_log_edit_and_cancel_keep_drafts; Spanish fallback and save clears choice', async ({page}) => {
  const state = await setup(page, {es: true}); await expect(page.locator('#log-spot-choice')).toContainText('En un sitio guardado');
  await expect(page.locator('#log-spot option').nth(2)).toHaveText('Sitio sin nombre');
  await choose(page, 'precise'); await page.locator('#log-note').fill('draft note');
  await page.locator('[data-edit-log]').click(); await expect(page.locator('#log-spot')).toHaveValue(''); await expect(page.locator('#log-lat')).toHaveValue('12');
  await choose(page, spots[0]!.id); await page.locator('#log-cancel').click();
  await expect(page.locator('#log-spot')).toHaveValue('precise'); await expect(page.locator('#log-lat')).toHaveValue('35.123456789'); await expect(page.locator('#log-note')).toHaveValue('draft note');
  expect(state.writes).toHaveLength(0);
  await page.locator('[data-edit-log]').click(); await choose(page, spots[0]!.id); await page.locator('#log-save').click();
  await expect.poll(() => state.writes.length).toBe(1); expect(state.writes[0]!.method).toBe('PATCH');
  const {id: _id, ...stored} = entry;
  expect(state.writes[0]!.body).toEqual({...stored, lat: 0, lon: 0});
  await expect(page.locator('#log-spot')).toHaveValue(''); await expect(page.locator('#log-lat')).toHaveValue('35.123456789');
});
