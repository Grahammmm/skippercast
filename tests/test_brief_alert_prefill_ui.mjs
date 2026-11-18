import assert from 'node:assert/strict';
import {existsSync} from 'node:fs';
import test from 'node:test';
import {chromium, expect} from '@playwright/test';
import {build} from 'esbuild';
import {styledRendererPlugin} from './helpers/esbuild-url.mjs';

const options = {skip: !existsSync(chromium.executablePath()) && 'chromium not installed', timeout: 25000};
const base = 'https://brief-alerts.test';
const region = {id: 'test-coast', name: 'Test Coast', timezone: 'America/Los_Angeles', center: [35, -121],
  species: ['halibut', 'reef', 'surfperch'], forecast_points: [
    {id: 'far', name: 'Far', latitude: 35, longitude: -121},
    {id: 'near', name: 'Near', latitude: 36, longitude: -122},
  ]};
const today = '2026-11-21', tomorrow = '2026-11-22';
const own = {wind: 9, gust: 13, seas: 2.5};
const saved = {id: 'fixture', region: region.id, date: '2026-11-20', point: 'far', species: 'reef', start_hour: 8, end_hour: 14};
let bundled;
function bundle() {
  return bundled ??= build({stdin: {resolveDir: new URL('..', import.meta.url).pathname, contents: `
    import {h, render} from 'preact';
    import {signal} from '@preact/signals';
    import {LowerExposure} from './web/brief/Brief.tsx';
    import {AccountMenu} from './web/app/AccountMenu.tsx';
    import {session} from './web/account.ts';
    import {region, profile, species, day} from './web/state.ts';
    import {regionInfo} from './web/app/region-info.ts';
    import {savedLimits} from './web/limits.ts';
    import {regionPorts, plannerPort} from './web/ports.ts';
    import {language, prepareCatalogue} from './web/i18n.ts';
    const brief = signal(null);
    const Layout = ({mobile}) => h('main', null, h(AccountMenu, {top: mobile}), h(LowerExposure, {brief: brief.value}), mobile && h(AccountMenu, {inline: true}));
    const show = mobile => render(h(Layout, {mobile, key: mobile ? 'phone' : 'desk'}), document.getElementById('root'));
    function update({date = '${today}', p = 'boat', target = 'surfperch', limits = null, window = true, badHours = false, port = true, signedIn = true} = {}) {
      profile.value = p;
      species.value = target;
      savedLimits.value = limits ? {[p]: limits} : {};
      session.value = signedIn ? {state: 'signed-in', name: null} : {state: 'signed-out'};
      plannerPort.value = {region: region.peek(), id: 'used'};
      regionPorts.value = port ? {region: region.peek(), state: 'ready', list: [{id: 'first', match: [35, -121]}, {id: 'used', match: [36, -122]}]} : null;
      brief.value = {profile: p, date, windows: window ? [{start: date + (badHours ? 'T15:30:00Z' : 'T15:00:00Z'),
        end: date + 'T19:00:00Z', label: 'Lower offshore exposure on ' + date, reasons: ['Not a safety clearance']}] : []};
    }
    window.fixture = {show, update, profile, changeRegion: id => { region.value = id; }, clearBrief: () => { brief.value = null; }, spanish: async () => { await prepareCatalogue('es'); language.value = 'es'; }};
    window.boot = ({info, mobile, ...values}) => {
      // Neither the raw dock day nor the first listed port matches what the alert should use.
      day.value = '2026-11-23';
      region.value = info.id; regionInfo.value = info;
      localStorage.setItem('skippercast-boat-v1', JSON.stringify({schema_version: 1, boat: {name: 'Fixture skiff', loa_ft: 12, hull: 'flat', layout: 'skiff'}}));
      update(values); show(mobile);
      window.effects = [];
      for (const [obj, methods] of [[Storage.prototype, ['setItem', 'removeItem', 'clear']], [History.prototype, ['pushState', 'replaceState']]]) {
        for (const name of methods) {
          const original = obj[name]; obj[name] = function (...args) { window.effects.push(name); return original.apply(this, args); };
        }
      }
      Notification.requestPermission = async () => { window.effects.push('permission'); return 'denied'; };
    };`}, bundle: true, write: false, outfile: 'brief-alert-fixture.js', platform: 'browser', format: 'iife',
    jsx: 'automatic', jsxImportSource: 'preact', plugins: [styledRendererPlugin]});
}

async function fixture(t, setup = {}) {
  const browser = await chromium.launch({args: ['--no-sandbox']});
  t.after(() => browser.close());
  const page = await browser.newPage({timezoneId: 'Asia/Tokyo', serviceWorkers: 'block'});
  const writes = [];
  const auth = {signedIn: true, signIn: '/#account'};
  let hold, seen, holdSave;
  await page.route('**/*', async route => {
    const request = route.request(), url = new URL(request.url());
    if (request.method() !== 'GET') {
      writes.push({method: request.method(), path: url.pathname, body: request.postData()});
      await holdSave;
      return route.fulfill({status: 201, json: {id: 'synthetic-trip'}});
    }
    if (url.origin !== base) return route.abort();
    switch (url.pathname) {
      case '/': return route.fulfill({contentType: 'text/html', body: '<main id="root"></main>'});
      case '/api/session':
        if (hold) { const wait = hold; hold = null; seen(); await wait; }
        return route.fulfill({json: auth});
      case '/regions/test-coast/region.json': return route.fulfill({json: {...region, ...(setup.region ?? {})}});
      case '/api/trips': return route.fulfill({json: {trips: [saved], events: []}});
      case '/api/comfort': return route.fulfill({json: {feedback: []}});
      case '/api/catch-log': return route.fulfill({headers: {'X-SC-Catch-Log-Has-More': 'false'}, json: {entries: []}});
      default: return route.abort();
    }
  });
  await page.clock.setFixedTime(new Date('2026-11-22T02:00:00Z')); // still Nov 21 in the forecast region
  await page.goto(base);
  const {outputFiles} = await bundle();
  await page.addStyleTag({content: outputFiles.find(f => f.path.endsWith('.css')).text});
  await page.addScriptTag({content: outputFiles.find(f => f.path.endsWith('.js')).text});
  await page.evaluate(values => window.boot(values), {...setup, info: region});
  const dialog = page.getByRole('dialog', {name: 'Trip alerts', exact: true});
  const cta = page.getByRole('button', {name: 'Alert me if this changes'});
  return {page, dialog, cta, writes, auth, field: name => page.locator(`#save-alert [name=${name}]`),
    save: page.locator('#save-alert button[type=submit]'), menu: page.locator(setup.mobile ? '.app-account-top-trigger' : '.app-account-trigger'),
    delaySave() {
      const {promise, resolve} = Promise.withResolvers();
      holdSave = promise;
      return resolve;
    },
    delaySession() {
      const {promise, resolve} = Promise.withResolvers();
      hold = promise;
      const arrived = new Promise(resolve => { seen = resolve; });
      return {arrived, release: resolve};
    },
  };
}

async function noWrites({page, writes}) {
  assert.equal(writes.length, 0);
  assert.equal(await page.evaluate(() => window.effects.join(',')), '');
}
const limits = async ({field}, values) => {
  for (const [index, key] of ['wind_limit', 'gust_limit', 'sea_limit'].entries()) await expect(field(key)).toHaveValue(String(values[index]));
};

test('the displayed window opens one editable alert; only Save sends the normal trip', options, async t => {
  const app = await fixture(t, {mobile: true, limits: own});
  const {page, cta, dialog, field, save, writes} = app;
  await expect(page.locator('.app-window')).toContainText(/7 am–11 am.*Not a safety clearance/);
  await page.emulateMedia({media: 'print'});
  await expect(cta).toBeHidden();
  await page.emulateMedia({media: 'screen'});
  await cta.press('Enter');
  await expect(dialog).toHaveCount(1);
  for (const [name, value] of Object.entries({date: today, point: 'near', start_hour: '7', end_hour: '11'})) await expect(field(name)).toHaveValue(value);
  await expect(page.locator('#species-select')).toHaveValue('surfperch');
  await limits(app, [9, 13, 2.5]);
  await expect(page.locator('#trip-boat-note')).toContainText('without boat-factor scaling');
  await noWrites(app);
  await field('end_hour').fill('12');
  await field('wind_limit').fill('10');
  await page.locator('#species-select').selectOption('reef');
  await page.evaluate(() => window.fixture.spanish());
  await expect(page.getByRole('dialog', {name: 'Alertas de viaje', exact: true})).toBeVisible();
  await expect(field('end_hour')).toHaveValue('12');
  await expect(page.locator('#species-select')).toHaveValue('reef');
  await noWrites(app);
  const release = app.delaySave();
  try {
    await save.click();
    await expect(save).toBeDisabled();
    await page.locator('#save-alert').evaluate(form => form.requestSubmit());
  } finally { release(); }
  await expect(page.locator('#alert-status')).not.toBeEmpty();
  assert.equal(writes.length, 1);
  const [request] = writes;
  const body = JSON.parse(request.body);
  assert.equal(request.method, 'POST');
  assert.equal(request.path, '/api/trips');
  for (const [name, value] of Object.entries({date: today, point: 'near', region: region.id, start_hour: 7, end_hour: 12,
    species: 'reef', wind_limit: 10, gust_limit: 13, sea_limit: 2.5})) assert.equal(body[name], value, name);
  assert.equal(body.boat.name, 'Fixture skiff');
  assert.ok(!('plan' in body));
});

test('invalid date, area and hours stay blank, explain why and cannot Save; later ordinary entry and Use again work', options, async t => {
  const app = await fixture(t, {date: '2026-11-29', port: false, badHours: true, target: 'lingcod'});
  const {page, cta, dialog, field, menu, save} = app;
  await cta.click();
  await expect(dialog.getByText('Choose a date from today to seven days ahead.', {exact: false})).toBeVisible();
  await expect(dialog.getByText('Choose a forecast area for this window.', {exact: false})).toBeVisible();
  await expect(dialog.getByText('Choose whole local hours for this window.', {exact: false})).toBeVisible();
  for (const name of ['date', 'point', 'start_hour', 'end_hour']) await expect(field(name)).toHaveValue('');
  await expect(field('date')).toBeFocused();
  await expect(page.locator('#species-select')).toHaveValue('halibut'); // not the planner's lingcod -> reef mapping
  await limits(app, [5, 7, 1.5]);
  for (const [fieldName, fill] of [['date', () => field('date').fill(today)], ['point', () => field('point').selectOption('near')]]) {
    await save.click();
    await expect(field(fieldName)).toBeFocused();
    await noWrites(app);
    await fill();
  }
  await save.click();
  await expect(field('start_hour')).toBeFocused();
  await noWrites(app);
  await page.keyboard.press('Escape');
  await expect(dialog).toBeHidden();
  await expect(cta).toBeFocused();
  await menu.click();
  await page.getByRole('button', {name: 'Saved-trip alerts', exact: true}).click();
  await expect(field('date')).toHaveValue(tomorrow);
  await expect(field('point')).toHaveValue('far');
  await expect(field('end_hour')).toHaveValue('13');
  await dialog.getByRole('button', {name: /Use again/}).click();
  await expect(field('date')).toHaveValue('');
  await expect(field('date')).toBeFocused();
  await expect(field('end_hour')).toHaveValue('14');
  await expect(page.locator('#species-select')).toHaveValue('reef');
  await noWrites(app);
});

test('no lower window or known signed-out session omits the action; a fresh sign-out shows the existing sign-in path', options, async t => {
  const app = await fixture(t, {window: false});
  const {page, cta, dialog, auth, menu} = app;
  await expect(page.locator('.app-window')).toContainText('No lower-exposure window');
  await expect(cta).toHaveCount(0);
  await page.evaluate(() => window.fixture.clearBrief());
  await expect(page.locator('.app-window')).toHaveCount(0);
  await expect(cta).toHaveCount(0);
  await page.evaluate(() => window.fixture.update({signedIn: false}));
  await expect(cta).toHaveCount(0);
  auth.signedIn = false;
  await menu.click();
  await page.getByRole('button', {name: 'Saved-trip alerts', exact: true}).click();
  await expect(dialog.locator('a[href="#account"]').first()).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(dialog).toBeHidden();
  await page.evaluate(() => window.fixture.update()); // menu's cached session has since expired
  await cta.click();
  await expect(dialog.locator('a[href="#account"]').first()).toBeVisible();
  await expect(dialog.locator('#save-alert')).toHaveCount(0);
  await noWrites(app);
});

test('closing, replacing or switching context discards delayed drafts, but changing layouts keeps the current one', options, async t => {
  const app = await fixture(t);
  const {page, cta, dialog, field, delaySession} = app;
  for (const action of [
    () => dialog.getByRole('button', {name: 'Close', exact: true}).click(),
    () => page.evaluate(() => { window.fixture.profile.value = 'shore'; }),
    () => page.evaluate(() => window.fixture.changeRegion('other-coast')),
  ]) {
    const old = delaySession();
    await cta.click();
    await old.arrived;
    await action();
    await expect(dialog).toBeHidden();
    old.release();
    await page.evaluate(() => { window.fixture.changeRegion('test-coast'); window.fixture.update(); });
    await expect(cta).toBeVisible();
    await expect(dialog).toBeHidden();
  }
  const old = delaySession();
  await cta.click();
  await old.arrived;
  await page.evaluate(() => window.fixture.show(true));
  await expect(dialog).toHaveCount(1);
  await expect(field('date')).toHaveValue(today);
  old.release();
  await page.evaluate(() => window.fixture.update({date: '2026-11-23', limits: {wind: 7, gust: 11, seas: 2}}));
  await expect(page.locator('.app-window')).toContainText('Lower offshore exposure on 2026-11-23');
  // A synthetic replacement can arrive while a modal makes the brief inert to pointer input.
  await page.locator('.app-window-alert').evaluate(button => button.click());
  await expect(dialog).toHaveCount(1);
  await expect(field('date')).toHaveValue('2026-11-23');
  await limits(app, [7, 11, 2]);
  await noWrites(app);
});

test('the other profiles keep their defaults and can start from their own limits', options, async t => {
  const app = await fixture(t, {region: {species: ['halibut', 'reef', 'surfperch', 'cabezon-shallow-reef', 'lingcod']}});
  const {page, cta, dialog} = app;
  for (const [p, expectedTarget] of [['shore', 'surfperch'], ['spear', 'cabezon-shallow-reef'], ['kayak', 'lingcod']]) {
    for (const saved of [null, {wind: 6, gust: 10, seas: 2}]) {
      await page.evaluate(values => window.fixture.update(values), {p, target: null, limits: saved});
      await cta.click();
      await expect(page.locator('#species-select')).toHaveValue(expectedTarget);
      await limits(app, saved ? [6, 10, 2] : [8, 12, 3]);
      await page.keyboard.press('Escape');
      await expect(dialog).toBeHidden();
    }
  }
  await noWrites(app);
});