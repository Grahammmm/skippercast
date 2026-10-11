// v2 head parity with v1: the landing (/) and the app (/map) carry v1's web
// manifest link, theme colour, favicon and Apple touch icon. FE-61 deleted
// dist/index.html, so v1's favicon and theme colour are its values on main
// before the deletion.
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
const V1_ICON = `<link rel="icon" type="image/svg+xml" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 40 40'%3E%3Crect width='40' height='40' rx='9' fill='%23082e3b'/%3E%3Cpath d='m20 5 7 24-7-4-7 4z' fill='%2354dacb'/%3E%3Cpath d='M8 33h24' stroke='white' stroke-width='3'/%3E%3C/svg%3E"`;
const V1_THEME = '#082e3b';

test('the v2 pages carry v1\'s manifest link, theme colour, favicon and touch icon', () => {
  const manifest = JSON.parse(read('manifest.webmanifest'));
  for (const page of Object.keys(V2)) {
    const html = read(page);
    assert.equal(tags(html, MANIFEST).length, 1, `${page}: one manifest link`);
    assert.equal(tags(html, TOUCH).length, 1, `${page}: one apple-touch-icon`);
    const themes = [...head(html).matchAll(THEME)].map(m => m[1]);
    assert.deepEqual(themes, [manifest.theme_color], `${page}: one theme-color, the manifest's`);
    assert.deepEqual(tags(html, ICON).map(t => t.replace(/ ?\/>$/, '')), [V1_ICON], `${page}: v1's favicon`);
  }
  // design.md names no browser theme colour, so v1's stays; the manifest and icons are site-wide, not v1-only paths.
  assert.equal(manifest.theme_color, V1_THEME);
  assert.equal(manifest.start_url, '/');
  for (const icon of manifest.icons) assert.ok(existsSync(new URL(icon.src.slice(1), dist)), icon.src);
});

