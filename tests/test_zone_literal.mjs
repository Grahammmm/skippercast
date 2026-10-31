// RF0935-2: web/ spells its fallback zone once (web/zone.ts) and the defaults read the same zone as before.
import assert from 'node:assert/strict';
import test from 'node:test';
import {mkdtemp, readdir, readFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {rendererPlugins} from './helpers/esbuild-url.mjs';
import {terrainHour} from '../web/map/stage.ts';

const ROOT = new URL('..', import.meta.url).pathname;
const LA = 'America/Los_Angeles', HOME = 'web/zone.ts';
// RF0850-7 owns NightMap.tsx and removes its literal there; then remove it from this list.
const ALLOWED = ['web/landing/NightMap.tsx'];

/** Line numbers where a quoted ('…', "…" or `…`) string names the zone, outside comments. */
export function zoneLiterals(text) {
  return text.split('\n').flatMap((line, i) => {
    const code = line.replace(/\/\*.*?\*\//g, '').replace(/(^|[^:])\/\/.*$/, '$1');
    return /^\s*\*/.test(code) || !/(['"`])[^'"`\n]*Los_Angeles[^'"`\n]*\1/.test(code) ? [] : [i + 1];
  });
}

/** Problems with a {path: text} tree: a stray literal, a missing home, or a stale allowlist entry. */
export function treeProblems(files) {
  const problems = [];
  for (const [path, text] of Object.entries(files)) {
    const hits = zoneLiterals(text);
    if (hits.length && path !== HOME && !ALLOWED.includes(path)) problems.push(`${path}:${hits.join(',')} spells the zone; import DEFAULT_ZONE from ${HOME}`);
  }
  if (zoneLiterals(files[HOME] ?? '').length !== 1) problems.push(`${HOME} must define the zone exactly once`);
  for (const path of ALLOWED) if (!zoneLiterals(files[path] ?? '').length) problems.push(`remove ${path.split('/').pop()} from the allowlist`);
  return problems;
}

async function webTree() {
  const names = (await readdir(join(ROOT, 'web'), {recursive: true})).filter(name => /\.tsx?$/.test(name));
  return Object.fromEntries(await Promise.all(names.map(async name => [`web/${name}`, await readFile(join(ROOT, 'web', name), 'utf8')])));
}

test('the web tree spells the zone only in web/zone.ts and the allowlist', async () => {
  const files = await webTree();
  assert.ok(Object.keys(files).length > 100 && files['web/app/App.tsx'], 'the scan reads the whole web tree');
  assert.deepEqual(treeProblems(files), []);
});

test('the scanner flags every quoted spelling and skips comments', () => {
  for (const q of ["'", '"', '`']) assert.deepEqual(zoneLiterals(`const a = 1;\nconst z = x ?? ${q}${LA}${q};`), [2], `quote ${q}`);
  assert.deepEqual(zoneLiterals(`f({timeZone: 'UTC', url: 'https://x.test'}); g(\`${LA}\`) // see web/zone.ts`), [1], 'a URL is not a comment');
  for (const line of [`// the zone ${LA} lives in web/zone.ts`, `x(); // '${LA}': web/zone.ts`, `/** '${LA}' */`, ` * '${LA}'`, 'const z = DEFAULT_ZONE;']) {
    assert.deepEqual(zoneLiterals(line), [], line);
  }
});

test('a stray literal, a lost home or a stale allowlist entry fails the scan', async () => {
  const files = await webTree();
  assert.match(treeProblems({...files, 'web/brief/Run.tsx': `tz = info?.timezone ?? "${LA}";`}).join('\n'), /^web\/brief\/Run\.tsx:1 spells the zone/);
  assert.match(treeProblems({...files, [HOME]: 'export const DEFAULT_ZONE = ZONE;'}).join('\n'), /web\/zone\.ts must define the zone exactly once/);
  const night = files[ALLOWED[0]].replaceAll(`'${LA}'`, 'DEFAULT_ZONE');
  assert.deepEqual(treeProblems({...files, [ALLOWED[0]]: night}), ['remove NightMap.tsx from the allowlist']);
});

test('the defaults read the same zone as before', async () => {
  const now = new Date('2026-10-05T20:00:00Z');
  assert.deepEqual(terrainHour(null, now), terrainHour(null, now, null, LA));
  assert.deepEqual(terrainHour(null, now, '2026-10-07'), terrainHour(null, now, '2026-10-07', LA), 'a ?day= reads in Pacific');
  assert.notDeepEqual(terrainHour(null, now, '2026-10-07', 'Asia/Tokyo'), terrainHour(null, now, '2026-10-07'), 'the zone matters for a day');
  const out = join(await mkdtemp(join(tmpdir(), 'zone-')), 'zone.mjs');
  await build({stdin: {resolveDir: ROOT, loader: 'ts', contents: `export {DEFAULT_ZONE as viaApp} from './web/app/App.tsx';\nexport {DEFAULT_ZONE as viaZone} from './web/zone.ts';`},
    bundle: true, format: 'esm', platform: 'node', outfile: out, write: true, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact', plugins: rendererPlugins});
  const {viaApp, viaZone} = await import(pathToFileURL(out).href);
  assert.equal(viaApp, LA);
  assert.equal(viaZone, viaApp);
});
