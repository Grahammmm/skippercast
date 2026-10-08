// FE-75 (docs/plans/front-end/design.md § 3A.2): a packages/coast chart()
// mounted through web/app/CoastMarkup.tsx reads web/tokens.css colours. No v2
// view mounts the host yet (FE-32 is the first), so this page is built here:
// esbuild bundles the component, and routes on the local origin serve it with
// web/tokens.css, panel.css and the token bridge. Nothing reaches the Worker.
import {readFileSync} from 'node:fs';
import {basename, join} from 'node:path';
import {build, type Plugin} from 'esbuild';
import {expect, test} from './fixtures.ts';

const ROOT = join(import.meta.dirname, '..');
const BASE = '/__coast-markup/';
const STYLES: Record<string, string> = {'tokens.css': 'web/tokens.css', 'panel.css': 'packages/coast/panel.css', 'coast-markup.css': 'web/app/coast-markup.css',
  'tokens-bridge.css': 'packages/coast/tokens-bridge.css'};
const css = (file: string) => readFileSync(join(ROOT, file), 'utf8').replace(/@font-face\s*\{[^}]*\}/g, '');

/** `?url` stylesheet imports resolve to this page's routes, as Vite's hashed URLs would. */
const urlImports: Plugin = {
  name: 'url-imports',
  setup(b) {
    b.onResolve({filter: /\?url$/}, args => ({path: join(args.resolveDir, args.path.replace(/\?url$/, '')), namespace: 'url'}));
    b.onLoad({filter: /.*/, namespace: 'url'}, args => ({contents: `export default ${JSON.stringify(BASE + basename(args.path))};`, loader: 'js'}));
  },
};

async function bundle(): Promise<string> {
  const result = await build({
    stdin: {resolveDir: ROOT, loader: 'tsx', contents: `
      import {h, render} from 'preact';
      import {CoastMarkup} from './web/app/CoastMarkup.tsx';
      const w = window;
      w.cursorHours = [];
      w.mountChart = args => render(h(CoastMarkup, {renderer: 'chart', args, onCursor: hour => w.cursorHours.push(hour)}), document.getElementById('host'));`},
    bundle: true, format: 'iife', write: false, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact', plugins: [urlImports],
  });
  return result.outputFiles[0]!.text;
}

const START = '2026-10-05T00:00:00Z', END = '2026-10-06T00:00:00Z';
const ROWS = [{label: 'Wind', unit: 'kt', color: 'var(--coast-blue)', points: [{at: '2026-10-05T06:00:00Z', value: 8}, {at: '2026-10-05T07:00:00Z', value: 11}, {at: '2026-10-05T08:00:00Z', value: 9}]}];
const args = (selected: string) => [ROWS, START, END, selected, 'UTC', {sunrise: '2026-10-05T14:00:00Z', sunset: '2026-10-06T01:30:00Z'}];

test.beforeEach(async ({page}) => {
  const script = await bundle();
  await page.route(`**${BASE}**`, route => {
    const name = new URL(route.request().url()).pathname.slice(BASE.length);
    if (name === '') return route.fulfill({contentType: 'text/html', body: `<!doctype html><html lang="en"><head><meta charset="utf-8"><title>CoastMarkup</title><link rel="stylesheet" href="${BASE}tokens.css"></head><body><main id="host"></main><script src="${BASE}host.js"></script></body></html>`});
    if (name === 'host.js') return route.fulfill({contentType: 'text/javascript', body: script});
    const file = STYLES[name];
    return file ? route.fulfill({contentType: 'text/css', body: css(file)}) : route.fulfill({status: 404, body: ''});
  });
  await page.goto(BASE);
});

/** Mount the chart and wait until the three shadow-root stylesheets have loaded. */
async function mount(page: import('@playwright/test').Page, selected: string) {
  await page.evaluate(a => (window as unknown as {mountChart(args: unknown): void}).mountChart(a), args(selected));
  await expect.poll(() => page.evaluate(() => {
    const root = document.querySelector('[data-coast-theme="tokens"]')?.shadowRoot;
    const links = [...(root?.querySelectorAll('link') ?? [])] as HTMLLinkElement[];
    return links.length === 3 && links.every(link => !!link.sheet) && !!root?.querySelector('svg.series-chart');
  })).toBe(true);
}

/** [element, computed colour inside the host, the web/tokens.css colour it must equal]. */
const colours = (page: import('@playwright/test').Page) => page.evaluate(() => {
  const root = document.querySelector('[data-coast-theme="tokens"]')!.shadowRoot!;
  const want = (token: string) => { const probe = document.createElement('i'); probe.style.color = `var(${token})`; document.body.append(probe); const c = getComputedStyle(probe).color; probe.remove(); return c; };
  const got = (selector: string, prop: string) => getComputedStyle(root.querySelector(selector)!).getPropertyValue(prop);
  return [
    ['cursor', got('line[stroke-dasharray]', 'stroke'), want('--text')],
    ['night', got('rect', 'fill'), want('--bg-deep')],
    ['series', got('path', 'stroke'), want('--blue')],
    ['baseline', got('line[stroke-opacity=".12"]', 'stroke'), want('--muted')],
  ];
});

test('a chart() inside CoastMarkup reads web/tokens.css colours, dark and light', async ({page, pageErrors: _}) => {
  await mount(page, '2026-10-05T12:00:00Z');
  const dark = await colours(page);
  for (const [what, got, want] of dark) expect(got, `dark ${what}`).toBe(want);
  // The fallbacks (v1's literals) differ from the tokens, so equality above is the bridge at work.
  expect(dark.map(([, got]) => got)).not.toContain('rgb(227, 247, 255)');
  // Light tokens differ from panel.css's own :host values, so this also proves coast-markup.css un-shadows them.
  await page.evaluate(() => { document.documentElement.dataset.theme = 'light'; });
  const light = await colours(page);
  for (const [what, got, want] of light) expect(got, `light ${what}`).toBe(want);
  expect(light.map(([, got]) => got)).not.toEqual(dark.map(([, got]) => got));
});

test('CoastMarkup re-renders on new arguments and reports the dragged hour', async ({page, pageErrors: _}) => {
  await mount(page, '2026-10-05T12:00:00Z');
  const cursorX = () => page.evaluate(() => document.querySelector('[data-coast-theme="tokens"]')!.shadowRoot!.querySelector('line[stroke-dasharray]')!.getAttribute('x1'));
  const before = await cursorX();
  await mount(page, '2026-10-05T18:00:00Z');
  expect(await cursorX()).not.toBe(before);
  expect(await page.evaluate(() => document.querySelector('[data-coast-theme="tokens"]')!.shadowRoot!.querySelectorAll('svg').length)).toBe(1);
  // Client coordinates of viewBox x at 6 h and 9 h into the 24 h span (plot area 69…808).
  const at = (hours: number) => page.evaluate(h => {
    const svg = document.querySelector('[data-coast-theme="tokens"]')!.shadowRoot!.querySelector('svg')!;
    const point = new DOMPoint(69 + (h / 24) * (840 - 69 - 32), 40).matrixTransform(svg.getScreenCTM()!);
    return {x: point.x, y: point.y};
  }, hours);
  const from = await at(6), to = await at(9);
  await page.mouse.move(from.x, from.y);
  await page.mouse.down();
  await page.mouse.move(to.x, to.y, {steps: 3});
  await page.mouse.up();
  const hours = await page.evaluate(() => (window as unknown as {cursorHours: string[]}).cursorHours);
  expect(hours[0]).toBe('2026-10-05T06:00Z');
  expect(hours.at(-1)).toBe('2026-10-05T09:00Z');
});
