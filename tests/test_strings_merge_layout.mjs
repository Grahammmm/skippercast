import assert from 'node:assert/strict';
import {mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {test} from 'node:test';
import {pathToFileURL} from 'node:url';
import {generate} from '../scripts/build_landing_strings.mjs';

function fixture(t) {
  const root = mkdtempSync(join(tmpdir(), 'strings-layout-'));
  t.after(() => rmSync(root, {recursive: true, force: true}));
  for (const dir of ['catalog/app', 'web/landing', 'dist']) mkdirSync(join(root, dir), {recursive: true});
  const catalogue = {strings: {
    'status.z': {en: 'Ready', es: 'Listo'},
    'landing.hero.z': {en: '"Wind"\nfrom the north', es: 'Viento del norte'},
    'landing.reading.defer': {en: 'Deferred', es: 'Después'},
    'coverage.a': {en: 'Coverage', es: 'Cobertura'},
    'landing.hero.a': {en: 'Swell', es: 'Oleaje'},
  }};
  writeFileSync(join(root, 'catalog/app/strings.json'), JSON.stringify(catalogue));
  generate({root: pathToFileURL(root + '/')});
  return root;
}

// The same catalogue's output from the old compact generator, not a second call to the new projector.
const LEGACY = {
  'web/strings.en.generated.json': String.raw`{"status.z":{"en":"Ready"},"landing.hero.z":{"en":"\"Wind\"\nfrom the north"},"landing.reading.defer":{"en":"Deferred"},"coverage.a":{"en":"Coverage"},"landing.hero.a":{"en":"Swell"}}`,
  'web/strings.es.generated.json': '{"status.z":"Listo","landing.hero.z":"Viento del norte","landing.reading.defer":"Después","coverage.a":"Cobertura","landing.hero.a":"Oleaje"}',
  'web/landing/strings.generated.json': String.raw`{"landing.hero.z":{"en":"\"Wind\"\nfrom the north"},"landing.hero.a":{"en":"Swell"}}`,
  'dist/status-strings.generated.json': '{"status.z":{"en":"Ready"},"coverage.a":{"en":"Coverage"}}',
};

test('all four written tables match legacy values and catalogue order, detecting dropped or sorted ids', t => {
  const root = fixture(t);
  for (const [path, compact] of Object.entries(LEGACY)) {
    const actual = JSON.parse(readFileSync(join(root, path), 'utf8'));
    const expected = JSON.parse(compact);
    assert.deepEqual(actual, expected, path);
    assert.deepEqual(Object.keys(actual), Object.keys(expected), `${path}: catalogue order`);
  }
});

test('all four written tables put exactly one id on each line, detecting a return to compact JSON', t => {
  const root = fixture(t);
  for (const path of Object.keys(LEGACY)) {
    const text = readFileSync(join(root, path), 'utf8');
    const [open, ...lines] = text.split('\n');
    assert.equal(open, '{', `${path}: opening brace occupies its own line`);
    assert.equal(lines.pop(), '', `${path}: final newline`);
    assert.equal(lines.pop(), '}', `${path}: closing brace occupies its own line`);
    const ids = lines.map(line => {
      assert.match(line, /^"/, `${path}: unindented member line`);
      const keys = Object.keys(JSON.parse(`{${line.replace(/,$/, '')}}`));
      assert.equal(keys.length, 1, `${path}: only one id on a line`);
      return keys[0];
    });
    assert.deepEqual(ids, Object.keys(JSON.parse(LEGACY[path])), path);
  }
});
