// SC1722-19 (UX audit S4-10, E14): the desktop app does not scroll itself on load, and the time dock stays in the window on laptop sizes.
// Before the fix the day chip's scrollIntoView({block: 'nearest'}) (web/app/TimeDock.tsx) could scroll the document as well as the day strip,
// and the map stage's 480 px minimum pushed the dock under the window bottom (1180x820: dock bottom at 834).
// The calls are recorded from before the first script runs, so a scroll made by the app itself shows up as a call or a document scroll event.
import {test, expect} from './fixtures.ts';

const SIZES = [{width: 1024, height: 768}, {width: 1180, height: 820}, {width: 1280, height: 800}, {width: 1366, height: 768}, {width: 1440, height: 900}];

interface Trace {calls: string[]; scrolls: number}

async function record(page: import('@playwright/test').Page): Promise<void> {
  await page.addInitScript(() => {
    const w = window as unknown as {__trace: Trace};
    w.__trace = {calls: [], scrolls: 0};
    const original = Element.prototype.scrollIntoView;
    Element.prototype.scrollIntoView = function (this: Element, ...args: Parameters<Element['scrollIntoView']>) {
      w.__trace.calls.push(`scrollIntoView ${this.tagName}.${String(this.className).slice(0, 40)}`);
      return original.apply(this, args);
    };
    for (const name of ['scrollTo', 'scroll', 'scrollBy'] as const) {
      const f = window[name].bind(window);
      (window as unknown as Record<string, unknown>)[name] = (...args: unknown[]) => { w.__trace.calls.push(`window.${name}`); return (f as (...a: unknown[]) => void)(...args); };
    }
    document.addEventListener('scroll', () => { w.__trace.scrolls++; }, {capture: false});
  });
}

for (const size of SIZES) {
  test(`desktop ${size.width}x${size.height}: nothing scrolls the page on load and the whole time dock is in the window`, async ({page, v2}, info) => {
    test.skip(info.project.name !== 'laptop', 'the desktop layout only');
    await page.setViewportSize(size);
    await record(page);
    await v2.open('app', {region: 'morro-bay'});
    await expect(page.locator('.app-dock .ui-dock')).toBeVisible();
    // Two seconds after load, by the clock (no waiting for a convenient ready state).
    await page.waitForTimeout(2000);
    const m = await page.evaluate(() => {
      const d = document.documentElement, r = document.querySelector('.app-dock')!.getBoundingClientRect(), s = document.querySelector('.app-stage')!.getBoundingClientRect();
      const w = window as unknown as {__trace: Trace};
      return {scrollY: window.scrollY, scrollX: window.scrollX, height: d.scrollHeight, width: d.scrollWidth, iw: window.innerWidth, ih: window.innerHeight,
        dock: {top: r.top, bottom: r.bottom, left: r.left, right: r.right}, stage: {top: s.top, bottom: s.bottom, left: s.left, right: s.right},
        position: getComputedStyle(document.querySelector('.app-dock')!).position, trace: w.__trace};
    });
    expect(m.trace.calls, 'calls that scroll from script').toEqual([]);
    expect(m.trace.scrolls, 'document scroll events').toBe(0);
    expect(m.scrollY, 'scrollY').toBe(0);
    expect(m.scrollX, 'scrollX').toBe(0);
    expect(m.height, 'document height').toBeLessThanOrEqual(m.ih + 1);
    expect(m.width, 'document width').toBeLessThanOrEqual(m.iw + 1);
    expect(m.dock.bottom, 'dock bottom inside the window').toBeLessThanOrEqual(m.ih);
    expect(m.dock.top, 'dock top inside the window').toBeGreaterThanOrEqual(0);
    expect(m.dock.left).toBeGreaterThanOrEqual(m.stage.left);
    expect(m.dock.right).toBeLessThanOrEqual(m.stage.right + 0.5);
    // Sticky at the bottom of the map column, not clipped by the stage.
    expect(m.position).toBe('sticky');
    expect(m.dock.bottom, 'dock bottom inside the stage').toBeLessThanOrEqual(m.stage.bottom + 0.5);
    expect(m.dock.top, 'dock top inside the stage').toBeGreaterThanOrEqual(m.stage.top);
  });
}

test('a day chosen below the fold reveals its chip in the strip and moves no ancestor or the page', async ({page, v2}, info) => {
  test.skip(info.project.name !== 'laptop', 'the desktop layout only');
  await page.setViewportSize({width: 1024, height: 768});
  await v2.open('app', {region: 'morro-bay'});
  const strip = page.locator('.app-dock .ui-dock > .ui-segmented');
  await expect(strip.locator('.ui-chip').nth(7)).toBeAttached();
  // Park the dock under the window bottom inside scrollable ancestors, as an old browser or a tall header would leave it.
  await page.evaluate(() => {
    const stage = document.querySelector<HTMLElement>('.app-stage')!, dock = document.querySelector<HTMLElement>('.app-dock')!;
    document.body.style.minHeight = '2400px';
    stage.style.overflow = 'auto';
    dock.style.position = 'relative';
    dock.style.marginTop = '1600px';
    dock.style.width = '640px';
    (document.querySelector<HTMLElement>('.app-dock .ui-dock > .ui-segmented')!).style.maxWidth = '300px';
    window.scrollTo(0, 120);
    stage.scrollTop = 40;
  });
  const before = await page.evaluate(() => ({y: window.scrollY, stage: document.querySelector('.app-stage')!.scrollTop}));
  const last = strip.locator('.ui-chip').nth(7);
  await last.dispatchEvent('click');
  await expect(last).toHaveAttribute('aria-pressed', 'true');
  await page.waitForTimeout(300);
  const after = await page.evaluate(() => {
    const s = document.querySelector<HTMLElement>('.app-dock .ui-dock > .ui-segmented')!, c = s.querySelector<HTMLElement>('[aria-pressed="true"]')!.getBoundingClientRect(), r = s.getBoundingClientRect();
    return {y: window.scrollY, stage: document.querySelector('.app-stage')!.scrollTop, strip: s.scrollLeft, chipInside: c.left >= r.left - 1 && c.right <= r.right + 1};
  });
  expect(after.strip, 'the strip scrolled sideways').toBeGreaterThan(0);
  expect(after.chipInside, 'the chosen chip is inside the strip').toBe(true);
  expect(after.y, 'document scrollY unchanged').toBe(before.y);
  expect(after.stage, 'stage scrollTop unchanged').toBe(before.stage);
});
