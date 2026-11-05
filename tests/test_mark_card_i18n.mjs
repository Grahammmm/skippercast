// SC0922-09: the mark card's own words, its aria labels and the private-save feedback follow the page language.
// English output stays byte-identical; source-produced names, kinds and basis lines are never translated here.
// Synthetic marks only; no network.
import assert from 'node:assert/strict';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import test from 'node:test';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {rendererPlugins} from './helpers/esbuild-url.mjs';
import {WIRE_OK, catalogueProblems, isProse} from '../scripts/check_copy.mjs';

const ROOT = new URL('..', import.meta.url).pathname;
let ui;
async function components() {
  if (ui) return ui;
  const out = join(await mkdtemp(join(tmpdir(), 'mark-card-i18n-')), 'card.mjs');
  await build({
    stdin: {resolveDir: ROOT, loader: 'ts', contents: `
      export {MarkCard, SaveSpotAction, placeholderMark, readingCard} from './web/app/MarkCard.tsx';
      export {SAVE_WORDS, resultMessage, saveMarkSpot, spotCandidate} from './web/saved-spots.ts';
      export {session} from './web/account.ts';
      export {language} from './web/i18n.ts';
      export {render} from 'preact-render-to-string';
      export {h} from 'preact';`},
    bundle: true, format: 'esm', platform: 'node', outfile: out, write: true, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact',
    plugins: rendererPlugins,
  });
  ui = await import(pathToFileURL(out).href);
  return ui;
}

const SIGNED_IN = Object.freeze({state: 'signed-in', name: null});
const mark = (over = {}) => ({id: 'spot:SC26-001', name: 'Synthetic mark', kind: 'Reef mark', reading: 'A reading', source: 'Source line', basis: 'Basis line',
  position: {latitude: 35.3, longitude: -121.0}, ...over});

test('chrome_en_es_en: card words and aria labels follow the language, English is unchanged, and the mark itself is untouched', async () => {
  const {MarkCard, language, session, render, h} = await components();
  const m = mark({regulations: {href: 'https://example.org/regs', label: 'Official regs'}, rules: 'Rules text.',
    terms: [{href: 'https://example.org/terms', label: 'Publisher terms'}]});
  const frozen = JSON.stringify(m);
  session.value = SIGNED_IN;
  try {
    language.value = 'en';
    const en = render(h(MarkCard, {mark: m}));
    for (const s of ['aria-label="Selected mark"', 'Clear selection', 'Add to trip', 'GPX', '>Regulations<', 'aria-label="Official regs (official page, opens in a new tab)"',
      'aria-label="Regulations: Official regs (official page, opens in a new tab)"', "aria-label=\"Publisher terms (publisher's page, opens in a new tab)\"", 'Save this spot',
      'Private to your account. You can keep up to 100 saved spots.']) assert.ok(en.includes(s), `en: ${s}`);
    language.value = 'es';
    const es = render(h(MarkCard, {mark: m}));
    for (const s of ['aria-label="Marca seleccionada"', 'Borrar selección', 'Añadir al viaje', 'Reglamento', 'aria-label="Official regs (página oficial, se abre en una pestaña nueva)"',
      'aria-label="Reglamento: Official regs (página oficial, se abre en una pestaña nueva)"', 'aria-label="Publisher terms (página del editor, se abre en una pestaña nueva)"',
      'Guardar este lugar', 'Privado en tu cuenta. Puedes guardar hasta 100 lugares.']) assert.ok(es.includes(s), `es: ${s}`);
    // Source-produced words stay as the source wrote them.
    for (const s of ['Synthetic mark', 'Reef mark', 'A reading', 'Source line', 'Basis line', 'Rules text.', 'Official regs']) assert.ok(es.includes(s), `es keeps: ${s}`);
    assert.ok(!/Selected mark|Clear selection|Add to trip/.test(es), 'no English card words in Spanish');
    language.value = 'en';
    assert.ok(render(h(MarkCard, {mark: m})) === en, 'es then back to en renders the original English');
    assert.equal(JSON.stringify(m), frozen, 'the mark object is not changed by rendering');
  } finally { language.value = 'en'; session.value = {state: 'loading'}; }
});

test('chrome_branches: the pick, geology, charter and no-position lines and the research button', async () => {
  const {MarkCard, language, render, h} = await components();
  const lines = {
    pick: ['survey:s1', 'Pick this place on the map to export its position', 'Elige este lugar en el mapa para exportar su posición', {position: undefined}],
    geology: ['geology:u1', 'Geology unit: context for reading the map, not a place to fish', 'Unidad geológica: contexto para leer el mapa, no un lugar para pescar', {}],
    charter: ['charter:c1', 'Charter-reported grounds and AIS activity are not exported: they show apparent activity, not a verified place.',
      'Las zonas reportadas por chárteres y la actividad AIS no se exportan: muestran actividad aparente, no un lugar verificado.', {}],
    habitat: ['habitat:h1', 'This place has no saved position yet, so it cannot be added to a trip or exported.',
      'Este lugar aún no tiene una posición guardada, por lo que no se puede añadir a un viaje ni exportar.', {position: undefined}],
  };
  try {
    for (const [name, [id, en, es, over]] of Object.entries(lines)) {
      const m = mark({id, kind: 'Synthetic', ...over});
      language.value = 'en'; assert.ok(render(h(MarkCard, {mark: m})).includes(en), `${name} en`);
      language.value = 'es'; assert.ok(render(h(MarkCard, {mark: m})).includes(es), `${name} es`);
    }
    // A ranked trip spot offers Review & export.
    const trip = mark({trip: 'trip-1'});
    language.value = 'en'; assert.ok(render(h(MarkCard, {mark: trip})).includes('Review &amp; export'));
    language.value = 'es'; assert.ok(render(h(MarkCard, {mark: trip})).includes('Revisar y exportar'));
  } finally { language.value = 'en'; }
});

test('placeholder_and_reading_cards: the card own words translate, the renderer words stay', async () => {
  const {MarkCard, placeholderMark, readingCard, language, render, h} = await components();
  const p = placeholderMark('spot:x'), r = readingCard({latitude: 35.3, longitude: -121.0, label: 'Depth', value: '12 m', detail: 'Detail line', source: {label: 'Src', kind: 'modelled', sourceDate: '2026-01-02'}});
  try {
    language.value = 'en';
    assert.equal(p.kind, 'Mark'); assert.equal(p.source, 'Source —'); assert.equal(p.basis, 'The mark loads with the map engine; its source and age show here.');
    assert.equal(r.basis, 'Src, modelled, dated 2026-01-02. The reading is the original nearest displayed sample; not for navigation.');
    language.value = 'es';
    const html = render(h(MarkCard, {mark: p})) + render(h(MarkCard, {mark: r}));
    for (const s of ['>Marca<', 'Fuente —', 'La marca se carga con el motor del mapa; su fuente y antigüedad aparecen aquí.',
      'Src, modelled, con fecha 2026-01-02. La lectura es la muestra original mostrada más cercana; no sirve para navegar.', '12 m', 'Detail line']) assert.ok(html.includes(s), s);
    assert.equal(p.kind, 'Mark', 'the placeholder keeps its English fields across a language switch');
  } finally { language.value = 'en'; }
});

test('save_feedback_relocalizes: the same result reads in the current language, the English message is unchanged, legacy results stay verbatim', async () => {
  const {spotCandidate, resultMessage, SAVE_WORDS, saveMarkSpot} = await components();
  const ctx = spotCandidate(mark({id: 'geology:u1'}));
  assert.equal(ctx.message, 'This is map context, not a spot to save.');
  assert.equal(resultMessage(ctx, 'en'), ctx.message);
  assert.equal(resultMessage(ctx, 'es'), 'Esto es contexto del mapa, no un lugar para guardar.');
  const withheld = spotCandidate(mark({withheld: true, reading: ' This mark is inside a protected area. '}));
  assert.equal(withheld.message, 'This mark is inside a protected area. Not saved.');
  assert.equal(resultMessage(withheld, 'es'), 'This mark is inside a protected area. No se guardó.', 'the producer reading stays as written');
  const bare = spotCandidate(mark({withheld: true, reading: ''}));
  assert.equal(bare.message, 'Not saved.'); assert.equal(resultMessage(bare, 'es'), 'No se guardó.');
  assert.equal(resultMessage(spotCandidate(mark({position: undefined})), 'es'), 'Esta marca no tiene una posición para guardar.');
  const legacy = {state: 'failed', message: 'Inside a protected area. Not saved.'};
  assert.equal(resultMessage(legacy, 'es'), legacy.message, 'a result with no identity is never parsed as English');
  // Wire-compatible results: the shape callers compare is unchanged (state and message only).
  assert.deepEqual(Object.keys(ctx).sort(), ['message', 'state']);
  assert.equal(SAVE_WORDS.cap, 'You can keep up to 100 saved spots. Remove one in Account before saving another.');
  // A refused save never posts and a thrown-in-place answer is a result with identity too.
  const calls = [];
  const r = await saveMarkSpot(mark(), {session: () => ({state: 'signed-out'}), region: () => 'morro-bay', fetchFn: async () => { calls.push(1); return new Response('{}'); }});
  assert.equal(r.message, SAVE_WORDS.signIn); assert.equal(resultMessage(r, 'es'), 'Vuelve a iniciar sesión para guardar este lugar.'); assert.equal(calls.length, 0);
});

test('save_action_language: pending, saved and the blocked reason follow the language without a state change', async () => {
  const {SaveSpotAction, language, session, render, h} = await components();
  session.value = SIGNED_IN;
  try {
    const blocked = mark({id: 'charter:c1'});
    language.value = 'en';
    const en = render(h(SaveSpotAction, {mark: blocked}));
    assert.ok(en.includes('Save this spot') && en.includes('This is map context, not a spot to save.'));
    language.value = 'es';
    const es = render(h(SaveSpotAction, {mark: blocked}));
    assert.ok(es.includes('Guardar este lugar') && es.includes('Esto es contexto del mapa, no un lugar para guardar.') && /<button[^>]*disabled/.test(es));
  } finally { language.value = 'en'; session.value = {state: 'loading'}; }
});

test('catalogue_and_wire_token: the tree is clean, and the server wire token is allowed in saved-spots.ts only', () => {
  assert.deepEqual(catalogueProblems(), []);
  const token = 'you can keep at most 100 saved spots; remove one first';
  assert.ok(isProse(token), 'the token reads as prose to the lint');
  assert.ok(WIRE_OK.get('web/saved-spots.ts')?.has(token));
  assert.equal(WIRE_OK.get('web/app/MarkCard.tsx'), undefined);
  assert.equal(WIRE_OK.size, 1, 'one path, one token');
});
