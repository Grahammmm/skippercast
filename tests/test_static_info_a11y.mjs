// SC1722-17: the sources, coverage, status and licences documents carry one description each, wrap
// their static tables in keyboard-reachable scrollers, and scope the touch-height rule to their lists.
// Geometry and axe are proved in e2e/wcag-static.spec.ts; this file checks the authored source only.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';

const read = name => readFileSync(new URL(`../dist/${name}`, import.meta.url), 'utf8');
const DESCRIPTIONS = {
  'sources.html': 'Read the data sources, methods and limitations behind SkipperCast’s habitat maps and marine forecasts.',
  'coverage.html': 'Explore the fishing bounds and review status of SkipperCast’s published regions.',
  'status.html': 'Check when SkipperCast’s published data sources last updated and which sources are outside their expected intervals.',
  'licenses.html': 'Read the software licences and data attributions used by SkipperCast.',
};

test('each page has exactly one nonempty one-sentence description, beside its title and canonical', () => {
  for (const [name, expected] of Object.entries(DESCRIPTIONS)) {
    const html = read(name);
    const tags = html.match(/<meta\s+name="description"[^>]*>/g) || [];
    assert.equal(tags.length, 1, name);
    assert.equal(tags[0], `<meta name="description" content="${expected}" />`, name);
    assert.equal((expected.match(/[.!?]/g) || []).length, 1, `${name}: one sentence`);
    assert.equal((html.match(/<title>/g) || []).length, 1, name);
    assert.equal((html.match(/<link rel="canonical"/g) || []).length, 1, name);
  }
});

test('the static tables each sit alone in a named, focusable scroller', () => {
  for (const [name, count] of [['sources.html', 2], ['licenses.html', 1]]) {
    const html = read(name);
    assert.equal((html.match(/<table[\s>]/g) || []).length, count, name);
    const wrapped = [...html.matchAll(/<div class="forecast-table-wrap" role="region" tabindex="0" (aria-label="[^"]+"|aria-labelledby="data")>\s*<table class="evidence-table">[\s\S]*?<\/table>\s*<\/div>/g)];
    assert.equal(wrapped.length, count, name);
  }
  const labels = [...read('sources.html').matchAll(/class="forecast-table-wrap"[^>]*aria-label="([^"]+)"/g)].map(m => m[1]);
  assert.equal(new Set(labels).size, 2, 'the two sources tables have distinct names');
  assert.match(read('licenses.html'), /<h2 id="data">Data attributions<\/h2>/);
});

test('the readable sheet scopes touch height to the sources and coverage lists and shrinks the coverage drawing', () => {
  const css = read('coast-readable.css');
  const rule = css.match(/\.coast-readable #sources-content li > a, \.coast-readable #coverage-list li > a \{([^}]*)\}/);
  assert.ok(rule, 'a rule scoped to the two lists');
  assert.match(rule[1], /min-height: var\(--touch-min\)/);
  assert.doesNotMatch(css, /\.coast-readable (a|li > a|li) \{[^}]*min-height: var\(--touch-min\)/);
  assert.match(css, /\.coast-readable #coverage-map svg \{[^}]*max-width: 100%;[^}]*height: auto/);
  assert.match(css, /\.coast-readable \.forecast-table-wrap \{[^}]*overflow-x: auto/);
  const page = read('coverage.html');
  assert.match(page, /id="coverage-list"/);
  assert.match(read('sources.html'), /<main id="sources-content">/);
});
