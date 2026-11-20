import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {chmodSync, copyFileSync, mkdirSync, mkdtempSync, rmSync, writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {dirname, join} from 'node:path';
import {test} from 'node:test';

const source = new URL('../scripts/coast_diagnostics/relief_shots_preflight.mjs', import.meta.url);
const names = ['@playwright/test', 'esbuild', 'maplibre-gl/dist/maplibre-gl-worker.mjs', 'Chromium (chromium-headless-shell)'];
const kinds = ['module', 'module', 'worker', 'executable'];

function fixture(t, missing) {
  const root = mkdtempSync(join(tmpdir(), 'relief-shots-preflight-'));
  t.after(() => rmSync(root, {recursive: true, force: true}));
  const script = join(root, 'scripts/coast_diagnostics/relief_shots_preflight.mjs');
  const browser = join(root, 'browser', 'headless_shell');
  const put = (name, contents) => {
    const path = join(root, name);
    mkdirSync(dirname(path), {recursive: true});
    writeFileSync(path, contents);
  };
  mkdirSync(dirname(script), {recursive: true});
  copyFileSync(source, script);
  const mustNotLoad = 'throw new Error("presence must not evaluate this module");';
  if (missing !== 'all') {
    if (missing !== 0) put('node_modules/@playwright/test/index.js', mustNotLoad);
    if (missing !== 1) put('node_modules/esbuild/index.js', mustNotLoad);
    if (missing !== 2) put(`node_modules/${names[2]}`, mustNotLoad);
    // Neither Playwright dependency is at the checkout root, as with pnpm.
    const playwright = 'node_modules/@playwright/test/node_modules/playwright';
    put(`${playwright}/index.js`, mustNotLoad);
    put(`${playwright}/node_modules/playwright-core/lib/coreBundle.js`, `
      exports.registry = {registry: {findExecutable(name) {
        if (name !== 'chromium-headless-shell') throw new Error('expected headless shell');
        return {executablePath: () => ${JSON.stringify(browser)}};
      }}};
    `);
    if (missing !== 3) {
      // Not even a valid executable format: a presence check must not run it.
      put('browser/headless_shell', 'inert fixture');
      chmodSync(browser, missing === 'no execute bit' ? 0o644 : 0o755);
    }
  }
  return (...args) => {
    const result = spawnSync(process.execPath, [script, ...args], {cwd: dirname(root), encoding: 'utf8'});
    assert.ifError(result.error);
    assert.equal(result.stderr, '');
    return result;
  };
}

// An empty checkout must name every missing prerequisite, not abort at the first import.
test('text mode lists all missing prerequisites', t => {
  const {status, stdout} = fixture(t, 'all')();
  assert.equal(status, 1);
  for (const [i, name] of names.entries()) assert.ok(stdout.includes(`missing ${kinds[i]}: ${name}`), stdout);
  assert.match(stdout, /not that Chromium launches/);
});

// Removing any prerequisite must affect exit status; unrelated probes must still run.
for (const [i, name] of names.entries()) {
  test(`JSON mode names missing ${name}`, t => {
    const {status, stdout} = fixture(t, i)('--json');
    assert.equal(status, 1);
    const {ok, checks} = JSON.parse(stdout);
    assert.equal(ok, false);
    assert.deepEqual(checks.map(check => [check.kind, check.name]), kinds.map((kind, j) => [kind, names[j]]));
    assert.deepEqual(checks.filter(check => !check.present).map(check => check.name),
      i === 0 ? [name, names[3]] : [name]);
  });
}

// A shell file without execute permission is not enough (POSIX mode bits).
test('rejects a non-executable shell file', {skip: process.platform === 'win32'}, t => {
  const {status, stdout} = fixture(t, 'no execute bit')('--json');
  assert.equal(status, 1);
  assert.deepEqual(JSON.parse(stdout).checks.filter(check => !check.present).map(check => check.name), [names[3]]);
});

// A complete install passes without executing the fake browser or evaluating module entries.
test('complete fixture passes with no browser launch', t => {
  const {status, stdout} = fixture(t)('--json');
  assert.equal(status, 0);
  const {ok, checks, note} = JSON.parse(stdout);
  assert.equal(ok, true);
  assert.deepEqual(checks.map(check => [check.name, check.present]), names.map(name => [name, true]));
  assert.match(note, /not that Chromium launches/);
});
