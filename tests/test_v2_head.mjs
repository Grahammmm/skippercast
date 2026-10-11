// v2 head parity with v1 (before FE-61 removes dist/index.html): the landing
// (/) and the app (/map) carry v1's web manifest link, theme colour, favicon
// and Apple touch icon. Telemetry stays off on v2 until the owner decides (#562).
import assert from 'node:assert/strict';
import test from 'node:test';
import {existsSync, readFileSync} from 'node:fs';

const dist = new URL('../dist/', import.meta.url);
const read = (name, base = dist) => readFileSync(new URL(name, base), 'utf8');
const V2 = {'landing.html': '../web/landing/main.tsx', 'app.html': '../web/app/main.tsx'};

/** The <head> of a page, whitespace collapsed. */
const head = html => html.split('</head>')[0].replace(/\s+/g, ' ');
const tags = (html, pattern) => [...head(html).matchAll(pattern)].map(m => m[0]);

const MANIFEST = /<link rel="manifest" href="manifest\.webmanifest" ?\/>/g;
const TOUCH = /<link rel="apple-touch-icon" href="apple-touch-icon\.png" ?\/>/g;
const THEME = /<meta name="theme-color" content="([^"]+)" ?\/>/g;
const ICON = /<link rel="icon" type="image\/svg\+xml" href="data:image\/svg\+xml,[^"]+" ?\/>/g;

test('the v2 pages carry v1\'s manifest link, theme colour, favicon and touch icon', () => {
  const v1 = read('index.html');
  const manifest = JSON.parse(read('manifest.webmanifest'));
  const [v1Icon] = tags(v1, ICON);
  assert.ok(v1Icon, 'v1 still has its favicon');
  for (const page of Object.keys(V2)) {
    const html = read(page);
    assert.equal(tags(html, MANIFEST).length, 1, `${page}: one manifest link`);
    assert.equal(tags(html, TOUCH).length, 1, `${page}: one apple-touch-icon`);
    const themes = [...head(html).matchAll(THEME)].map(m => m[1]);
    assert.deepEqual(themes, [manifest.theme_color], `${page}: one theme-color, the manifest's`);
    assert.deepEqual(tags(html, ICON).map(t => t.replace(/ ?\/>$/, '')), [v1Icon.replace(/ ?\/>$/, '')], `${page}: v1's favicon`);
  }
  // design.md names no browser theme colour, so v1's stays; the manifest and icons are site-wide, not v1-only paths.
  assert.equal(manifest.theme_color, [...head(v1).matchAll(THEME)][0][1]);
  assert.equal(manifest.start_url, '/');
  for (const icon of manifest.icons) assert.ok(existsSync(new URL(icon.src.slice(1), dist)), icon.src);
});

