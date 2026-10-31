// RF1120-6: --out is checked against the repo by real path, links are refused, and a dangling receipt link is refused up front.
import test from 'node:test';
import assert from 'node:assert/strict';
import {existsSync, mkdirSync, mkdtempSync, readdirSync, symlinkSync, writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {basename, dirname, join, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {capture, outsideRepo, parseArgs} from '../skills/skippercast-region-review/scripts/phone_capture.mjs';

const REPO = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const scratch = () => mkdtempSync(join(tmpdir(), 'phone-capture-paths-'));
const held = out => ['--mode', 'held', '--run', '/run', '--out', out];
// Candidate mode with an empty run throws before mkdir and before the browser import, so a
// refusal message other than this one proves the check ran first and nothing was launched.
const NO_BROWSER = /candidate mode needs/;
const candidate = out => ({mode: 'candidate', run: scratch(), out});

test('plain outside folder is accepted, existing or not', () => {
  const out = scratch();
  assert.equal(outsideRepo(out), true);
  assert.equal(outsideRepo(join(out, 'new', 'sub')), true);
  assert.equal(parseArgs(held(out)).out, out);
});

test('folders inside the repo are refused', () => {
  for (const out of [join(REPO, 'var', 'x'), REPO, join(REPO, 'tests')]) {
    assert.equal(outsideRepo(out), false, out);
    assert.throws(() => parseArgs(held(out)), /outside the repo/);
  }
});

test('a link outside the repo pointing into it is refused and nothing is created in the repo', async () => {
  const link = join(scratch(), 'out');
  symlinkSync(join(REPO, 'tests'), link);
  const child = `rf1120-6-${process.pid}-${Date.now()}`;
  for (const out of [link, join(link, child), join(link, child, 'sub')]) {
    assert.equal(outsideRepo(out), false, out);
    assert.throws(() => parseArgs(held(out)), /outside the repo/);
    await assert.rejects(capture(candidate(out)), /outside the repo/);
  }
  assert.equal(existsSync(join(REPO, 'tests', child)), false);
});

test('a link through an ancestor into the repo is refused', () => {
  const alias = join(scratch(), 'alias');
  symlinkSync(REPO, alias);
  assert.equal(outsideRepo(join(alias, 'var', 'new')), false);
  assert.equal(outsideRepo(join(alias, '..phone')), false);
});

test('look-alike siblings of the repo are accepted, directly and through a link', () => {
  assert.equal(outsideRepo(`${REPO}-copy/out`), true);
  assert.equal(outsideRepo(join(dirname(REPO), `${basename(REPO)}x`, 'out')), true);
  const alias = join(scratch(), 'parent');
  symlinkSync(dirname(REPO), alias);
  assert.equal(outsideRepo(join(alias, `${basename(REPO)}-copy`, 'out')), true);
  assert.equal(outsideRepo(join(alias, basename(REPO), 'out')), false);
});

test('a dangling link on the way to --out is refused', () => {
  const root = scratch(), link = join(root, 'gone');
  symlinkSync(join(root, 'missing'), link);
  assert.equal(outsideRepo(join(link, 'sub')), false);
  assert.throws(() => parseArgs(held(join(link, 'sub'))), /outside the repo/);
});

test('an --out link that stays outside the repo is still refused by capture', async () => {
  const root = scratch(), link = join(root, 'out');
  mkdirSync(join(root, 'real'));
  symlinkSync(join(root, 'real'), link);
  assert.equal(outsideRepo(link), true);
  await assert.rejects(capture(candidate(link)), /--out must not be a symlink/);
  assert.deepEqual(readdirSync(join(root, 'real')), []);
});

test('a dangling capture-receipt.json link is refused before mkdir or the browser', async () => {
  const out = scratch(), target = join(scratch(), 'elsewhere.json');
  symlinkSync(target, join(out, 'capture-receipt.json'));
  await assert.rejects(capture(candidate(out)), /refusing to overwrite .*capture-receipt\.json/);
  await assert.rejects(capture({mode: 'live', origin: 'https://fixture.invalid', region: 'r1', out}), /refusing to overwrite/);
  assert.deepEqual(readdirSync(out), ['capture-receipt.json']);
  assert.equal(existsSync(target), false);
});

test('an existing regular receipt is refused; an empty outside folder reaches the mode checks', async () => {
  const out = scratch();
  writeFileSync(join(out, 'capture-receipt.json'), '{}\n');
  await assert.rejects(capture(candidate(out)), /refusing to overwrite/);
  await assert.rejects(capture(candidate(scratch())), NO_BROWSER);
});
