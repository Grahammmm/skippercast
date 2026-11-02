import assert from 'node:assert/strict';
import test from 'node:test';
import {mkdtemp, readFile, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {rendererPlugins} from './helpers/esbuild-url.mjs';

const ROOT = new URL('..', import.meta.url).pathname;
const NOW = new Date('2026-10-05T20:00:00Z'); // Existing test_app_shell fixture clock.
const memory = () => { const m = new Map(); return {getItem: k => m.get(k) ?? null, setItem: (k, v) => m.set(k, String(v))}; };

test('healthy App is byte-identical to the existing unguarded shell fixture', async () => {
  const dir = await mkdtemp(join(tmpdir(), 'guard-shell-'));
  try {
    const fixture = await readFile(join(ROOT, 'tests/test_app_shell.mjs'), 'utf8');
    const contents = fixture.match(/contents: `([\s\S]*?)`}/)[1];
    const modules = [];
    for (const unguarded of [false, true]) {
      const outfile = join(dir, `${unguarded}.mjs`);
      await build({stdin: {contents, resolveDir: ROOT, loader: 'ts'}, bundle: true,
        format: 'esm', platform: 'node', outfile, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact',
        plugins: [...rendererPlugins, ...(unguarded ? [{name: 'original-shell', setup(b) {
          b.onLoad({filter: /\/Guard\.tsx$/}, () => ({contents: 'export const Guard = ({children}) => children;', loader: 'tsx'}));
        }}] : [])]});
      modules.push(await import(pathToFileURL(outfile).href));
    }
    for (const narrow of [false, true]) for (const view of ['coast', 'conditions', 'history', 'fleet', 'reports']) {
      const html = modules.map(s => {
        s.state.configureStore({v2: true, storage: memory()});
        s.state.syncFromURL(`https://s.test/map?region=morro-bay&view=${view}&spot=r12`);
        s.narrow.value = narrow;
        return s.render(s.h(s.App, {now: NOW}));
      });
      assert.ok(html[0] === html[1], `unchanged healthy ${narrow ? 'mobile' : 'desktop'} ${view}`);
    }
  } finally { await rm(dir, {recursive: true, force: true}); }
});
