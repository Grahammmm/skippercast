// SC1737-08: the persistent footer line of docs/legal/disclaimers.md item 3. The /map brief
// footer and the landing footer both carry the C1 short form "Planning aid · not a navigation
// chart." with a link to the terms page, and the doc no longer calls item 3 "not yet built".
import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {rendererPlugins} from './helpers/esbuild-url.mjs';

const ROOT = new URL('..', import.meta.url).pathname;
const LINE = 'Planning aid · not a navigation chart.';
const read = path => readFileSync(join(ROOT, path), 'utf8');
const count = (text, needle) => text.split(needle).length - 1;

let mod;
async function load() {
  if (mod) return mod;
  const out = join(await mkdtemp(join(tmpdir(), 'footer-')), 'footer.mjs');
  await build({
    stdin: {resolveDir: ROOT, loader: 'ts', contents: `
      export {BriefFooter, DISCLAIMER, PLANNING_AID} from './web/brief/Brief.tsx';
      export {render} from 'preact-render-to-string';
      export {h} from 'preact';`},
    bundle: true, format: 'esm', platform: 'node', outfile: out, write: true, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact',
    plugins: rendererPlugins,
  });
  mod = await import(pathToFileURL(out).href);
  return mod;
}

/** The C1 row's "Short form (UI)" cell of the disclaimers table. */
function c1ShortForm() {
  const row = read('docs/legal/disclaimers.md').split('\n').find(line => line.startsWith('| C1 |'));
  assert.ok(row, 'disclaimers.md has a C1 row');
  return row.split('|').map(cell => cell.trim())[3];
}

test('the desktop brief footer (no children) carries the C1 line once, then Terms and Sources links', async () => {
  const {BriefFooter, DISCLAIMER, PLANNING_AID, render, h} = await load();
  assert.equal(PLANNING_AID, LINE);
  const html = render(h(BriefFooter, {}));
  assert.equal(count(html, LINE), 1, html);
  assert.equal(count(html, '<footer'), 1);
  assert.equal(count(html, 'separate clocks'), 1, 'the clocks disclaimer is unchanged and still once');
  assert.ok(html.includes(DISCLAIMER));
  const at = html.indexOf(LINE), terms = html.indexOf('<a href="/terms.html">Terms</a>'), sources = html.indexOf('<a href="/sources">Sources</a>');
  assert.ok(html.indexOf(DISCLAIMER) < at && at < terms && terms < sources, `order: clocks, C1 line, Terms, Sources in ${html}`);
});

test('the mobile brief footer (with children) keeps the line and both links, children after them', async () => {
  const {BriefFooter, render, h} = await load();
  const html = render(h(BriefFooter, {}, h('a', {href: '/reports', class: 'child'}, 'Reports')));
  assert.equal(count(html, LINE), 1, html);
  const terms = html.indexOf('href="/terms.html"'), sources = html.indexOf('href="/sources"'), child = html.indexOf('class="child"');
  assert.ok(terms > html.indexOf(LINE) && sources > terms && child > sources, `children come last in ${html}`);
  assert.ok(html.endsWith('</footer>'));
});

test('the landing has the line exactly once, inside its one footer, followed by a /terms.html link', () => {
  const page = read('dist/landing.html');
  assert.equal(count(page, '<footer'), 1);
  assert.equal(count(page, LINE), 1);
  const footer = page.slice(page.indexOf('<footer'), page.indexOf('</footer>'));
  assert.match(footer, /<p class="landing-planning">Planning aid · not a navigation chart\. <a href="\/terms\.html">Terms<\/a><\/p>/);
  assert.match(footer, /<li><a href="\/terms\.html">Terms<\/a><\/li>/, 'the nav keeps its own Terms item');
  assert.ok(footer.indexOf('separate clocks') < footer.indexOf(LINE), 'after the clocks line');
});

test('the C1 short form in disclaimers.md is the brief constant and the landing text', async () => {
  const {PLANNING_AID} = await load();
  const short = c1ShortForm();
  assert.equal(short, PLANNING_AID);
  assert.ok(read('dist/landing.html').includes(`>${short} <a href="/terms.html">`));
});

test('disclaimers.md item 3 is built; item 2 still is not', () => {
  const items = Object.fromEntries(read('docs/legal/disclaimers.md').split('\n').filter(line => /^\d\. /.test(line)).map(line => [line[0], line]));
  assert.ok(items['3']?.includes('Planning aid'), 'item 3 is the footer line');
  assert.doesNotMatch(items['3'], /not yet built/);
  assert.match(items['3'], /BriefFooter/);
  assert.match(items['2'], /not yet built/, 'the first-launch acknowledgement is still out of scope');
});
