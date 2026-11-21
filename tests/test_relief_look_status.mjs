import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
import {mkdtempSync, readFileSync, rmSync, writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import test from 'node:test';
import {fileURLToPath} from 'node:url';

const cli = fileURLToPath(new URL('../scripts/coast_diagnostics/relief_look_status.mjs', import.meta.url));
const fixture = name => fileURLToPath(new URL(`fixtures/relief/pointer-style/${name}.json`, import.meta.url));
const read = path => JSON.parse(readFileSync(path, 'utf8'));
const run = (...args) => execFileSync(process.execPath, [cli, ...args], {encoding: 'utf8'});

test('JSON reports every pointer in order, using only the current look and the shipped Chart lookup', t => {
  const dir = mkdtempSync(join(tmpdir(), 'relief-look-status-'));
  t.after(() => rmSync(dir, {recursive: true, force: true}));
  const known = fixture('v1');
  const rolling = fixture('v1_1-prev-v1');
  const legacy = fixture('legacy');
  const knownLook = read(known).style.baked;
  const current = read(rolling);
  const unknownLook = current.style.baked;
  assert.equal(current.previous.style.baked, knownLook);
  const malformed = join(dir, 'malformed.json');
  writeFileSync(malformed, JSON.stringify({...current, style: {...current.style, built_with: null}}));
  const refused = join(dir, 'held.json');
  writeFileSync(refused, JSON.stringify({...read(known), status: 'held'}));
  const invalid = join(dir, 'invalid.json');
  writeFileSync(invalid, '{');
  const missing = join(dir, 'missing.json');

  // Neither a known predecessor nor a known digest on a refused pointer may win.
  // The rolling fixture is in the producer test table, but not in the shipped lookup.
  const row = (path, status, detail) => ({path, region: 'morro-bay', status, ...detail});
  assert.deepEqual(JSON.parse(run(rolling, malformed, refused, invalid, missing, legacy, known, '--json')), [
    row(rolling, 'unknown', {look: unknownLook}),
    row(malformed, 'unknown', {look: null}),
    row(refused, 'refused', {reason: 'unreviewed'}),
    {path: invalid, status: 'refused', reason: 'invalid-json'},
    {path: missing, status: 'refused', reason: 'unreadable-file'},
    row(legacy, 'legacy', {look: 'deep-fixed-v1'}),
    row(known, 'known', {look: knownLook}),
  ]);
});

test('default output identifies each file, with the known digest visible without JSON', () => {
  const known = fixture('v1-no-contours');
  const legacy = fixture('legacy');
  const lines = run(known, legacy).trimEnd().split('\n');
  assert.equal(lines.length, 2);
  assert.ok(lines[0].includes(known));
  assert.ok(lines[0].includes(`known look (${read(known).style.baked})`));
  assert.ok(lines[1].includes(legacy));
  assert.ok(lines[1].includes('legacy look'));
});
