import assert from 'node:assert/strict';
import test from 'node:test';
import {mkdtemp, mkdir, readFile, rm, writeFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {BUILD_PLACEHOLDER, writePrecache} from '../scripts/precache.mjs';

const roots = {
  'app.html': {file: 'assets/app.1111111111.js', isEntry: true},
  'landing.html': {file: 'assets/landing.2222222222.js', isEntry: true},
  '../web/app/early.ts': {file: 'assets/early.3333333333.js', isEntry: true},
};

async function site(t) {
  const dir = await mkdtemp(join(tmpdir(), 'f21-17-'));
  t.after(() => rm(dir, {recursive: true, force: true}));
  await mkdir(join(dir, 'assets'));
  await writeFile(join(dir, 'assets/app.1111111111.js'), 'app');
  await writeFile(join(dir, 'assets/landing.2222222222.js'), 'landing');
  await writeFile(join(dir, 'assets/early.3333333333.js'), 'early');
  await writeFile(join(dir, 'sw.js'), BUILD_PLACEHOLDER);
  await writeFile(join(dir, 'precache.json'), 'old precache');
  return dir;
}

// F21-17: a missing or incomplete graph must never stamp a worker with an empty trip pack.
for (const [label, contents, error] of [
  ['missing', null, {code: 'ENOENT'}],
  ['unreadable', false, {code: 'EISDIR'}],
  ['malformed JSON', '{', SyntaxError],
  ['invalid entry', JSON.stringify({...roots, 'app.html': {}}), /missing required root: app\.html/],
  ...Object.keys(roots).map(key => [
    `missing ${key}`, JSON.stringify(Object.fromEntries(Object.entries(roots).filter(([root]) => root !== key))),
    {message: `Vite manifest is missing required root: ${key}`},
  ]),
]) {
  test(`${label} manifest leaves both outputs untouched`, async t => {
    const dir = await site(t);
    if (contents === false) {
      await mkdir(join(dir, '.vite/manifest.json'), {recursive: true});
    } else if (contents !== null) {
      await mkdir(join(dir, '.vite'));
      await writeFile(join(dir, '.vite/manifest.json'), contents);
    }
    await assert.rejects(writePrecache(dir, 'abc1234567'), error);
    assert.equal(await readFile(join(dir, 'sw.js'), 'utf8'), BUILD_PLACEHOLDER);
    assert.equal(await readFile(join(dir, 'precache.json'), 'utf8'), 'old precache');
  });
}

test('a valid graph keeps app-only chunks out of install and in the trip pack', async t => {
  const dir = await site(t);
  await mkdir(join(dir, '.vite'));
  await writeFile(join(dir, '.vite/manifest.json'), JSON.stringify(roots));
  const result = await writePrecache(dir, 'abc1234567');
  assert.deepEqual(result.assets, ['/assets/landing.2222222222.js']);
  assert.deepEqual(result.v2.assets, ['/assets/app.1111111111.js', '/assets/early.3333333333.js']);
  assert.equal(await readFile(join(dir, 'sw.js'), 'utf8'), "const BUILD = 'abc1234567';");
});
