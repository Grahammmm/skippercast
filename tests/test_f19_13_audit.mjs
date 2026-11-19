import assert from 'node:assert/strict';
import {execFile} from 'node:child_process';
import {appendFile, mkdir, mkdtemp, readFile, rm, writeFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import test from 'node:test';
import {fileURLToPath} from 'node:url';
import {promisify} from 'node:util';
import {runInNewContext} from 'node:vm';

const checkClient = fileURLToPath(new URL('../scripts/check_client.mjs', import.meta.url));
const worker = await readFile(new URL('../dist/sw.js', import.meta.url), 'utf8');
const run = promisify(execFile);

test('F19-13: the install budget charges raw HTML once per fetched URL and rejects shell-only growth', async t => {
  const dir = await mkdtemp(join(tmpdir(), 'f19-13-'));
  t.after(() => rm(dir, {recursive: true, force: true}));
  const build = '0123456789', landing = `landing.${build}.html`;
  const asset = 'assets/landing.0123456789.js', icon = 'app-icon.svg';
  const files = {
    [landing]: '<!doctype html><title>Landing</title>',
    [`app.${build}.html`]: '<!doctype html><title>Not installed</title>',
    [asset]: '/* ready */',
    [icon]: '<svg/>',
    '.vite/manifest.json': JSON.stringify({'landing.html': {file: asset, isEntry: true}}),
    '.assetsignore': '.vite\n',
    'sw.js': worker.replace("const BUILD = 'dev';", `const BUILD = '${build}';`),
  };
  await mkdir(join(dir, '.vite'));
  await mkdir(join(dir, 'assets'));
  for (const [file, contents] of Object.entries(files)) await writeFile(join(dir, file), contents);
  // The same asset is listed twice across groups, but the actual worker requests it once.
  const precache = {build, shells: ['/'], assets: [`/${asset}`], static: [`/${icon}`, `/${asset}`], v2: {assets: [`/${asset}`]}};
  const manifestFile = join(dir, 'precache.json'), budget = join(dir, 'budget.json');
  await writeFile(manifestFile, JSON.stringify(precache));
  const urls = [];
  await runInNewContext(`${worker}\nprecacheShell()`, {
    self: {addEventListener() {}},
    fetch: async path => { assert.equal(path, '/precache.json'); return {ok: true, json: async () => precache}; },
    Request: class { constructor(url) { this.url = url; } },
    caches: {open: async () => ({addAll: async requests => { for (const request of requests) urls.push(request.url); }})},
  });
  assert.deepEqual(urls, ['/', `/${asset}`, `/${icon}`]);
  const total = urls.reduce((bytes, url) => bytes + Buffer.byteLength(files[url === '/' ? landing : url.slice(1)]), 0);
  const pack = Buffer.byteLength(files[asset]);
  const check = () => run(process.execPath, [checkClient, dir, dir, budget]);
  await writeFile(budget, JSON.stringify({precache: {install_raw_max: total, pack_shell_raw_max: pack}}));
  const {stdout} = await check();
  const padding = '<!-- café -->'; // Use bytes, not JavaScript string length.
  const grown = total + Buffer.byteLength(padding);
  await appendFile(join(dir, landing), padding);
  // Old checker passes this over-budget build because growth of the shell never reaches its total.
  await assert.rejects(check(), {code: 1, stderr: new RegExp(`precache install is ${grown} B raw, over its budget of ${total} B`)});
  assert.match(stdout, new RegExp(`precache install ${total} B, pack shell ${pack} B raw`));

  // Distinct routes that serve the same file are distinct requests, not one file to charge once.
  await writeFile(join(dir, landing), files[landing]);
  await writeFile(manifestFile, JSON.stringify({...precache, static: [...precache.static, '/index.html']}));
  const aliasTotal = total + Buffer.byteLength(files[landing]);
  await assert.rejects(check(), {code: 1, stderr: new RegExp(`precache install is ${aliasTotal} B raw, over its budget of ${total} B`)});
});
