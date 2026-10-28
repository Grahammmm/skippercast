// FE79 / COVER-05: offline compile-only contract, discovered by package test glob.
import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {readFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
import test from 'node:test';

const root = fileURLToPath(new URL('../', import.meta.url));

test('terrain source types assign both ways and reject missing required fields', () => {
  const manifest = JSON.parse(readFileSync(new URL('../package.json', import.meta.url), 'utf8'));
  const installed = JSON.parse(readFileSync(new URL('../node_modules/typescript/package.json', import.meta.url), 'utf8'));
  assert.equal(installed.version, manifest.devDependencies.typescript, 'use the repository-pinned TypeScript');

  const run = spawnSync(process.execPath, [
    fileURLToPath(new URL('../node_modules/typescript/bin/tsc', import.meta.url)),
    '--ignoreConfig', '--noEmit', '--strict', '--skipLibCheck',
    '--target', 'ES2022', '--module', 'ESNext', '--moduleResolution', 'Bundler',
    '--lib', 'ES2023,DOM', '--allowImportingTsExtensions',
    'tests/fixtures/coast-types/terrain-source-assignability.ts',
  ], {cwd: root, encoding: 'utf8', timeout: 60_000});
  assert.ifError(run.error);
  assert.equal(run.status, 0, `type contract (including consumed negative controls):\n${run.stdout}\n${run.stderr}`);
});
