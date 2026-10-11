// The v2 pages start the same cookie-less telemetry as v1's dist/boot.js
// (web/telemetry.ts; docs/engineering/telemetry.md), and the funnel events
// they can send are exactly the ones the privacy notice
// (dist/privacy.html#analytics), the telemetry doc and the CHANGELOG name.
// The event set is found by following every relative static and dynamic
// import from each v2 entry (web/ and the v1 modules in dist/ it loads) to
// the track('<event>') calls in the files reached.
import test from 'node:test';
import assert from 'node:assert/strict';
import {existsSync, readFileSync, statSync} from 'node:fs';
import {dirname, relative, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const source = path => readFileSync(resolve(ROOT, path), 'utf8');
const IMPORT = /^import \{initTelemetry\} from '(?:\.\.\/)+web\/telemetry\.ts';$|^import \{initTelemetry\} from '\.\.\/telemetry\.ts';$/m;
const CALL = /^initTelemetry\(\);$/gm;

/** The v2 events, by entry: what the notice and docs must list. */
const V2_EVENTS = {
  'web/landing/main.tsx': [],
  'web/app/main.tsx': ['offline_saved', 'port_selected', 'spot_saved'],
};

const SPECIFIER = /(?:\bfrom\s*|\bimport\s*\(\s*|\bimport\s+)(['"])(\.{1,2}\/[^'"]+)\1/g;
function resolveImport(from, spec) {
  const base = resolve(dirname(from), spec);
  for (const file of [base, `${base}.ts`, `${base}.tsx`, `${base}.js`, `${base}.mjs`]) if (existsSync(file) && statSync(file).isFile()) return file;
  return null;
}
/** Every file reachable from `entry` and the funnel events their track() calls name. */
function reach(entry) {
  const seen = new Set(), stack = [resolve(ROOT, entry)], events = new Set(), dynamic = [];
  while (stack.length) {
    const file = stack.pop();
    if (seen.has(file)) continue;
    seen.add(file);
    const code = readFileSync(file, 'utf8');
    for (const match of code.matchAll(SPECIFIER)) { const next = resolveImport(file, match[2]); if (next) stack.push(next); }
    if (relative(ROOT, file) === 'web/telemetry.ts') continue;
    for (const match of code.matchAll(/\btrack\(\s*([^,)]*)/g)) {
      const literal = /^(['"])([a-z_]+)\1$/.exec(match[1].trim());
      if (literal) events.add(literal[2]); else dynamic.push(`${relative(ROOT, file)}: track(${match[1]}`);
    }
  }
  return {files: seen.size, events: [...events].sort(), dynamic};
}

test('v1 boot.js starts telemetry with a top-level initTelemetry() call (the pattern v2 follows)', () => {
  const boot = source('dist/boot.js');
  assert.match(boot, IMPORT);
  assert.equal(boot.match(CALL)?.length, 1);
});

for (const entry of Object.keys(V2_EVENTS)) {
  test(`${entry} starts telemetry once, before it renders`, () => {
    const code = source(entry);
    assert.match(code, IMPORT, 'imports initTelemetry from web/telemetry.ts');
    const calls = [...code.matchAll(CALL)];
    assert.equal(calls.length, 1, 'one top-level initTelemetry() call');
    // Before the first render, so an error while the page builds is reported too.
    const render = code.search(/^(?:mount\(|if \(host\))/m);
    assert.ok(render > 0, 'finds the first render');
    assert.ok(calls[0].index < render, 'initTelemetry() runs before the first render');
  });

  test(`${entry} can send exactly the funnel events the notice lists for it`, () => {
    const {files, events, dynamic} = reach(entry);
    assert.ok(files > 20, `follows the import graph (${files} files)`);
    assert.deepEqual(dynamic, [], 'every track() call in reach names its event literally');
    assert.deepEqual(events, V2_EVENTS[entry]);
  });
}

test('the privacy notice, telemetry doc and CHANGELOG name every v2 event', () => {
  const all = [...new Set(Object.values(V2_EVENTS).flat())];
  const notice = source('dist/privacy.html'), doc = source('docs/engineering/telemetry.md');
  const v2Notice = /The new\s+map\s+sends ([^.]+)\./.exec(notice)?.[1] ?? '';
  const v2Doc = /The v2 pages[^\n]+/.exec(doc)?.[0] ?? '';
  const changelog = source('CHANGELOG.md').split(/^## /m)[1].split('\n').find(line => line.includes('anonymous usage statistics')) ?? '';
  for (const event of all) {
    assert.match(v2Notice, new RegExp(`<code>${event}</code>`), `notice: ${event}`);
    assert.match(v2Doc, new RegExp(`\`${event}\``), `doc: ${event}`);
    assert.match(changelog, new RegExp(`\`${event}\``), `CHANGELOG: ${event}`);
  }
  assert.match(notice, /new home page\s+sends error reports only/);
});
