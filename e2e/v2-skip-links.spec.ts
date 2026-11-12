// SC1722-20 (UX audit S4-11, the naming part of S4-21): "Skip to brief" and "Skip to map" are the first two tab stops on /map,
// hidden until focused and 44 px when shown; Enter moves real focus into the brief (the phone sheet opens to half) or onto the map;
// and no two disclosures in the brief share an accessible name. The real /map shell on the local server, with native Tab and Enter.
// A returning visitor (profile saved) has no first-run card, so document focus starts neutral; the fresh-user card keeps its own
// heading focus (e2e/v2-first-run-brief.spec.ts) and is not the case measured here.
import type {Page} from '@playwright/test';
import {test, expect} from './fixtures.ts';

const AREA = {region: 'morro-bay'};
const NAMES = {
  en: {brief: 'Skip to brief', map: 'Skip to map', target: 'Brief', rows: ['Basis for wind', 'Basis for swell', 'Basis for water', 'Basis for tide']},
  es: {brief: 'Saltar al resumen', map: 'Saltar al mapa', target: 'Resumen', rows: ['Base del viento', 'Base del oleaje', 'Base del agua', 'Base de la marea']},
} as const;

test.beforeEach(async ({page}) => {
  await page.addInitScript(() => { try { localStorage.setItem('skippercast-profile-v1', 'boat'); } catch { /* storage blocked */ } });
  await page.route('**/api/session', route => route.fulfill({json: {signIn: '/#account', signedIn: false}}));
});

const active = (page: Page) => page.evaluate(() => {
  const el = document.activeElement as HTMLElement | null;
  return {tag: el?.tagName ?? '', id: el?.id ?? '', label: el?.getAttribute('aria-label') ?? '', text: el?.textContent?.trim() ?? '', inBrief: !!el?.closest('#app-brief-content'), inStage: !!el?.closest('.app-stage'), body: el === document.body};
});
/** Document focus neutral, as for a visitor who has just loaded the page. */
async function neutral(page: Page) {
  // v2.open waits only for the title; the shell (and, in Spanish, its strings) may still be rendering, so wait for both links.
  await expect(page.locator('.app-skip-link')).toHaveCount(2);
  await page.evaluate(() => { (document.activeElement as HTMLElement | null)?.blur(); window.scrollTo(0, 0); });
  expect((await active(page)).body).toBe(true);
}
const SHEET_HANDLE = '.ui-sheet-handle';
async function sheetTo(page: Page, key: 'Home' | 'End', detent: string) {
  await page.locator(SHEET_HANDLE).focus();
  await page.keyboard.press(key);
  await expect(page.locator('.ui-sheet')).toHaveAttribute('data-detent', detent);
}

for (const lang of ['en', 'es'] as const) {
  test(`first_two_real_tabs_${lang}: the skip links are the first two tab stops, clipped at rest, 44 px and ringed when focused`, async ({page, pageErrors, v2}) => {
    if (lang === 'es') await page.addInitScript(() => { try { localStorage.setItem('skippercast-language-v1', 'es'); } catch { /* storage blocked */ } });
    await v2.open('app', AREA);
    const names = NAMES[lang];
    const links = page.locator('.app-skip-link');
    await expect(links).toHaveText([names.brief, names.map]);
    // At rest: still in the page (named, focusable) but clipped to a pixel and not moved by any layout.
    for (const box of await links.evaluateAll(els => els.map(el => { const r = el.getBoundingClientRect(); return [r.width, r.height]; }))) expect(Math.max(...box)).toBeLessThanOrEqual(1);
    await neutral(page);
    const ordinaryBefore = await page.evaluate(() => [...document.querySelectorAll<HTMLElement>('a[href], button, input, select, summary, [tabindex="0"]')].indexOf(document.querySelector('.app-skip-link')!));
    expect(ordinaryBefore, 'the first link is the first ordinary tab stop in the document').toBe(0);

    await page.keyboard.press('Tab');
    expect(await active(page)).toMatchObject({tag: 'A', text: names.brief});
    const first = await links.first().evaluate(el => { const r = el.getBoundingClientRect(), s = getComputedStyle(el); return {w: r.width, h: r.height, x: r.x, y: r.y, ring: parseFloat(s.outlineWidth), style: s.outlineStyle, vw: innerWidth, vh: innerHeight}; });
    expect(first.w, 'at least 44 px wide').toBeGreaterThanOrEqual(44);
    expect(first.h, 'at least 44 px high').toBeGreaterThanOrEqual(44);
    expect(first.ring, 'a visible ring').toBeGreaterThanOrEqual(2);
    expect(first.style).not.toBe('none');
    expect(first.x).toBeGreaterThanOrEqual(0); expect(first.y).toBeGreaterThanOrEqual(0);
    expect(first.x + first.w).toBeLessThanOrEqual(first.vw); expect(first.y + first.h).toBeLessThanOrEqual(first.vh);

    await page.keyboard.press('Tab');
    expect(await active(page)).toMatchObject({tag: 'A', text: names.map});
    await page.keyboard.press('Shift+Tab');
    expect(await active(page)).toMatchObject({tag: 'A', text: names.brief});
    expect(pageErrors).toEqual([]);
  });
}

test('brief_enter: Enter on Skip to brief puts focus on the brief, not just the address; the phone sheet opens to half from peek and from full', async ({page, pageErrors, v2, isMobile}) => {
  await v2.open('app', AREA);
  const url = page.url();
  await neutral(page);
  await page.keyboard.press('Tab');
  await page.keyboard.press('Enter');
  await expect.poll(async () => (await active(page)).id).toBe('app-brief-content');
  expect((await active(page)).label, 'the focused brief is named').toBe(NAMES.en.target);
  expect(page.url(), 'a handled skip does not change the address').toBe(url);
  if (isMobile) await expect(page.locator('.ui-sheet')).toHaveAttribute('data-detent', 'half');
  // The next Tab enters the brief's own content, in its own order.
  await page.keyboard.press('Tab');
  expect((await active(page)).inBrief).toBe(true);
  if (isMobile) {
    // Browsers keep the last focus as the starting point for Tab even after a blur, so reach the link directly this time.
    await sheetTo(page, 'End', 'full');
    await page.locator('.app-skip-link').first().focus();
    await page.keyboard.press('Enter');
    await expect(page.locator('.ui-sheet')).toHaveAttribute('data-detent', 'half');
    await expect.poll(async () => (await active(page)).id).toBe('app-brief-content');
  }
  expect(pageErrors).toEqual([]);
});

test('brief_enter_es: in Spanish, Enter on Saltar al resumen focuses the brief under its localized name, Resumen', async ({page, pageErrors, v2}) => {
  await page.addInitScript(() => { try { localStorage.setItem('skippercast-language-v1', 'es'); } catch { /* storage blocked */ } });
  await v2.open('app', AREA);
  await expect(page.locator('.app-skip-link')).toHaveText([NAMES.es.brief, NAMES.es.map]);
  await neutral(page);
  await page.keyboard.press('Tab');
  expect(await active(page)).toMatchObject({tag: 'A', text: NAMES.es.brief});
  await page.keyboard.press('Enter');
  await expect.poll(async () => (await active(page)).id).toBe('app-brief-content');
  expect((await active(page)).label, 'the focused brief carries shell.brief in Spanish').toBe(NAMES.es.target);
  expect(pageErrors).toEqual([]);
});

test('map_enter: the second link focuses the map (its canvas, or the stage when no canvas can exist), never the body; the phone sheet stays below it', async ({page, pageErrors, v2, isMobile}) => {
  await v2.open('app', AREA);
  await neutral(page);
  await page.keyboard.press('Tab');
  await page.keyboard.press('Tab');
  await page.keyboard.press('Enter');
  await expect.poll(async () => (await active(page)).inStage).toBe(true);
  const now = await active(page);
  expect(now.body).toBe(false);
  expect(now.tag === 'CANVAS' || now.id === 'app-map-content' || now.text === '', 'a canvas, its host or the stage').toBe(true);
  if (isMobile) await expect(page.locator('.ui-sheet')).toHaveAttribute('data-detent', 'peek');
  expect(pageErrors).toEqual([]);
});

test('view_handoff: from the Fleet view Skip to brief exposes the Coast view, keeps the region and moves focus, also when pressed twice', async ({page, pageErrors, v2}) => {
  await v2.open('app', {...AREA, view: 'fleet'});
  await neutral(page);
  await page.keyboard.press('Tab');
  await page.keyboard.press('Enter');
  await expect.poll(async () => (await active(page)).id).toBe('app-brief-content');
  const url = new URL(page.url());
  expect(url.searchParams.get('view')).toBeNull();
  expect(url.searchParams.get('region')).toBe('morro-bay');
  // Activating twice in a row leaves one focus, on the brief.
  await page.locator('.app-skip-link').first().focus();
  await page.keyboard.press('Enter');
  await page.keyboard.press('Enter');
  await expect.poll(async () => (await active(page)).id).toBe('app-brief-content');
  expect(pageErrors).toEqual([]);
});

for (const lang of ['en', 'es'] as const) {
  test(`basis_names_${lang}: every disclosure in the brief has its own accessible name and keeps its visible word`, async ({page, pageErrors, v2, isMobile}) => {
    if (lang === 'es') await page.addInitScript(() => { try { localStorage.setItem('skippercast-language-v1', 'es'); } catch { /* storage blocked */ } });
    await v2.open('app', AREA);
    if (isMobile) await sheetTo(page, 'End', 'full');
    const root = isMobile ? '.app-sheet-brief' : 'aside.app-brief';
    await expect(page.locator(`${root} .ui-tile`)).toHaveCount(4);
    // A <summary>'s accessible name: its aria-label when it has one, else its own text.
    const read = () => page.locator(`${root} summary`).evaluateAll(els => els.map(el => ({name: el.getAttribute('aria-label') ?? el.textContent?.trim() ?? '', visible: el.textContent?.trim() ?? ''})));
    const summaries = await read();
    const names = summaries.map(s => s.name);
    for (const row of NAMES[lang].rows) expect(names).toContain(row);
    expect(names.every(Boolean), 'no empty names').toBe(true);
    expect(new Set(names).size, `no two disclosures share a name: ${names.join(' | ')}`).toBe(names.length);
    const tiles = await page.locator(`${root} .ui-tile .ui-popover-summary`).evaluateAll(els => els.map(el => el.textContent?.trim()));
    expect(new Set(tiles).size, 'the tiles still show their one visible word').toBe(1);
    expect(pageErrors).toEqual([]);
  });
}
