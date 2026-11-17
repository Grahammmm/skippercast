// RF1911-6: malformed translation catalogues are refused before any generated table is touched.
import assert from 'node:assert/strict';
import {mkdtemp, mkdir, readFile, writeFile, readdir, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {test} from 'node:test';
import {generate, projections, OUTPUTS} from '../scripts/build_landing_strings.mjs';

const SHAPE = /catalogue strings map/;
const BAD = {
  'null root': null, 'scalar root': 5, 'array root': [],
  'missing strings': {}, 'null strings': {strings: null}, 'scalar strings': {strings: 7},
  'string strings': {strings: 'x'}, 'array strings': {strings: [{en: 'a', es: 'b'}]}, 'empty strings': {strings: {}},
};
const SENTINEL = {en: 'EN-KEEP\n', es: 'ES-KEEP\n', landing: 'LANDING-KEEP\n'};

async function fixture(catalogueText, present = true) {
  const root = await mkdtemp(join(tmpdir(), 'catalogue-shape-'));
  await mkdir(join(root, 'catalog/app'), {recursive: true});
  await mkdir(join(root, 'web/landing'), {recursive: true});
  await writeFile(join(root, 'catalog/app/strings.json'), catalogueText);
  if (present) for (const key of Object.keys(OUTPUTS)) await writeFile(join(root, OUTPUTS[key]), SENTINEL[key]);
  return {root, base: pathToFileURL(root + '/')};
}

test('malformed_catalogue_maps_refuse: every malformed shape throws the map-shape diagnostic', () => {
  for (const [name, catalogue] of Object.entries(BAD)) assert.throws(() => projections(catalogue), SHAPE, name);
});

test('invalid_maps_never_replace_outputs: write and check modes keep sentinels and create nothing', async () => {
  for (const [name, catalogue] of Object.entries(BAD)) {
    const text = JSON.stringify(catalogue);
    for (const present of [true, false]) {
      const {root, base} = await fixture(text, present);
      try {
        for (const check of [false, true]) assert.throws(() => generate({check, root: base}), SHAPE, `${name} check=${check}`);
        for (const key of Object.keys(OUTPUTS)) {
          const read = readFile(join(root, OUTPUTS[key]), 'utf8');
          if (present) assert.equal(await read, SENTINEL[key], `${name}: ${key} kept`);
          else await assert.rejects(read, {code: 'ENOENT'}, `${name}: ${key} not created`);
        }
        assert.equal(await readFile(join(root, 'catalog/app/strings.json'), 'utf8'), text, `${name}: input unchanged`);
        assert.deepEqual(await readdir(join(root, 'web/landing')), present ? ['strings.generated.json'] : [], `${name}: landing dir`);
      } finally { await rm(root, {recursive: true, force: true}); }
    }
  }
});

test('nonempty_small_catalogues_preserve_projection_bytes: exact JSON, order, Unicode, newline', () => {
  const ordinary = projections({strings: {'x.one': {en: 'One', es: 'Uno ñ'}}});
  assert.equal(ordinary[OUTPUTS.en], '{"x.one":{"en":"One"}}\n');
  assert.equal(ordinary[OUTPUTS.es], '{"x.one":"Uno ñ"}\n');
  assert.equal(ordinary[OUTPUTS.landing], '{}\n');
  const both = projections({strings: {'x.one': {en: 'One', es: 'Uno'}, 'landing.hero.title': {en: 'Hi', es: 'Hola ¡'}}});
  assert.equal(both[OUTPUTS.es], '{"x.one":"Uno","landing.hero.title":"Hola ¡"}\n');
  assert.equal(both[OUTPUTS.landing], '{"landing.hero.title":{"en":"Hi"}}\n');
});

test('invalid_entry_errors_remain_specific: id-specific diagnostics and stale check survive', async () => {
  for (const entry of [{en: 'Two'}, {en: 'Two', es: ''}, {es: 'Dos'}, {en: '', es: 'Dos'}]) {
    assert.throws(() => projections({strings: {'x.two': entry}}), /x\.two: no (?:English|Spanish) string/);
  }
  const {root, base} = await fixture(JSON.stringify({strings: {'x.one': {en: 'One', es: 'Uno'}}}));
  try {
    assert.throws(() => generate({check: true, root: base}), /Stale web\/strings\.en\.generated\.json.*run node scripts\/build_landing_strings\.mjs/);
    assert.equal(await readFile(join(root, OUTPUTS.en), 'utf8'), SENTINEL.en, 'check mode writes nothing');
  } finally { await rm(root, {recursive: true, force: true}); }
});
