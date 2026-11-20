import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import test from 'node:test';
import {fileURLToPath} from 'node:url';
import {build} from 'esbuild';
import {coverageReport} from '../server/fleet/admin/coverage.ts';

// Render the actual report body without mounting the fetch-driven admin shell.
const {outputFiles: [bundle]} = await build({
  stdin: {resolveDir: fileURLToPath(new URL('..', import.meta.url)), contents: `
    export {CoverageBody} from './web/admin/fleet-coverage.tsx';
    export {h} from 'preact';
    export {render} from 'preact-render-to-string';`},
  bundle: true, write: false, format: 'esm', platform: 'node', jsx: 'automatic', jsxImportSource: 'preact',
  plugins: [{name: 'expose-report-body', setup(b) {
    b.onLoad({filter: /\/fleet-coverage\.tsx$/}, async ({path}) => ({loader: 'tsx',
      contents: `${await readFile(path, 'utf8')}\nexport {CoverageBody};`}));
  }}],
});
const {CoverageBody, h, render} = await import(`data:text/javascript;base64,${Buffer.from(bundle.contents).toString('base64')}`);

async function report(counts) {
  // Stub only the database projection; the real report builds buckets and the exact-one list.
  const rows = counts.map((sources, i) => ({id: `fixture-${i}`, slug: `fixture-${i}`, name: `Fixture boat ${i}`,
    region: 'fixture', port_id: null, vessel_class: null, completeness: 0, seen: 0, sources,
    source_id: sources ? 'fixture-source' : null}));
  const db = {prepare: sql => ({bind: () => ({all: async () => ({results: sql.includes('FROM fleet_vessels') ? rows : []})})})};
  return coverageReport(db, 'fixture', new Date('2026-01-01T00:00:00Z'));
}
const htmlFor = r => render(h(CoverageBody, {r}));
const empty = 'No single-source boats in this result.';

test('[0,2]: a zero-source boat remains in its own bucket, not an all-boats coverage claim', async () => {
  const html = htmlFor(await report([0, 2]));
  assert.match(html, /<dt>0 sources<\/dt><dd>1<\/dd>/);
  assert.ok(!html.includes('Every boat has two or more sources.'), 'an empty single-source list does not mean every boat has two sources');
  assert.ok(html.includes(empty));
});

test('an empty region without runs still says there are no single-source boats in the result', async () => {
  const html = htmlFor(await report([]));
  assert.ok(html.includes(empty), html);
});

test('a one-source boat appears in the list; a capped result keeps its truncation notice', async () => {
  const html = htmlFor(await report([0, 1, 2]));
  const single = html.split('<h2 id="fc-single">')[1];
  assert.match(single, /Fixture boat 1<\/a>.*<td>fixture-source<\/td>/);
  assert.doesNotMatch(single, /Fixture boat [02]|No single-source boats/);

  const capped = htmlFor(await report([0, ...Array(5000).fill(2)]));
  assert.match(capped, /Only the first 5,000 boats are counted here\./);
  assert.match(capped, /<dt>0 sources<\/dt><dd>1<\/dd>/);
});
