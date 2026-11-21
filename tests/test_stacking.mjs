// MSKL-3: the layer kit's stacking engine (web/map/stacking.ts), its z_order draw-order anchors (web/map/layers.ts) and the
// kit registry/legend rows and no-data stubs. CI-ARTICLE-1: each test names the contract it protects and the believable bug
// that fails it. Every expected number comes from the generated tokens (web/map/layers-style.gen.ts), never a literal copy.
import assert from 'node:assert/strict';
import {readFileSync, readdirSync} from 'node:fs';
import test from 'node:test';
import {LAYERS_STYLE} from '../web/map/layers-style.gen.ts';
import {KIT_LAYER_IDS, STACKING, draftStack, mayAutoEnable, presetInput, presetStack, resolveStack, stopsAt} from '../web/map/stacking.ts';
import {KIT_LAYERS, LAYERS, NO_DATA_YET, SKL_SLOT_LAYERS, Z_ORDER_ANCHORS, Z_SLOTS, kitLayer, zBefore} from '../web/map/layers.ts';
import {KIT_LAYER_MODULES} from '../web/map/kit-layers/index.ts';
import {kitRow} from '../web/map/legend-model.ts';

const STYLE = LAYERS_STYLE.layers;
const CHECK = LAYERS_STYLE.stacking.stacking_check;
const LO = STACKING.isolines_from_zoom - 1, HI = STACKING.isolines_from_zoom;
const on = (...ids) => ids.map(id => ({id}));
const row = (stack, id) => stack.layers.find(r => r.id === id);
const repsOf = (stack, id) => [...row(stack, id).reps];

// ── The kit's stacking_check ───────────────────────────────────────────────────

// Contract: the kit's own check of STACK-A as drafted with the new picks (CUR-C, WIND-A) finds 3 colour fields and 2 particle
// layers, the two listed violations. Bug: the draft quietly applies precedence, or a pick's fill/particles go uncounted.
test('STACK-A as drafted with the new picks: 3 fields, 2 particle layers, the two listed violations', () => {
  const draft = draftStack(on('sst-fill', 'currents', 'wind'), STACKING.presets['STACK-A'].zoom);
  const want = CHECK['STACK-A_as_drafted_with_new_picks'];
  assert.equal(draft.counts.color_field, want.color_fields);
  assert.equal(draft.counts.particles, want.particles);
  assert.equal(draft.counts.arrows_barbs, want.arrows_barbs);
  assert.deepEqual(draft.violations, ['color_field', 'particles']);
  assert.equal(draft.violations.length, want.violations.length);
});

// Contract: P1–P6 resolve the presets to the kit's final counts with no violation, each layer drawing what the preset says.
// Bug: the engine leaves wind's particles on beside the currents' streamlines, or drops SST's auto isotherms in NEAR-D.
for (const [name, key] of [['STACK-A', 'STACK-A_final'], ['NEAR-D', 'NEAR-D_final']]) {
  test(`${name} resolved: the kit's final counts pass and every layer draws as the preset lists`, () => {
    const stack = presetStack(name), want = CHECK[key];
    assert.equal(want.pass, true);
    assert.deepEqual(stack.violations, []);
    assert.equal(stack.counts.color_field, want.color_fields);
    assert.equal(stack.counts.particles, want.particles);
    assert.equal(stack.counts.arrows_barbs, want.arrows_barbs);
    assert.equal(stack.counts.isolines, want.isolines);
    for (const {layer, as} of STACKING.presets[name].layers) assert.deepEqual(repsOf(stack, layer), as, layer);
  });
}

// Contract: a preset switches its fill layer on last (P1 latest wins) and passes only optional parts it leaves out.
// Bug: a preset's `as` list is copied into the stack, bypassing the rules (then presetStack proves nothing).
test('presetInput: the fill owner is switched on last and only optional parts are left out', () => {
  assert.deepEqual(presetInput('STACK-A').map(i => i.id), ['currents', 'wind', 'sst-fill']);
  assert.deepEqual(presetInput('NEAR-D').find(i => i.id === 'kelp-habitat').without, ['shore']);
  assert.deepEqual(presetInput('NEAR-D').find(i => i.id === 'spots-marks').without, []);
  assert.throws(() => presetInput('NOPE'), RangeError);
});

// ── P1–P6, each both ways ──────────────────────────────────────────────────────

// Contract P1: the most recently switched-on fill owns the colour field; a fill-only loser is replaced and says by which layer.
// Bug: the first fill wins, or two fills draw together.
test('P1: the latest fill wins either way round; the loser is replaced by it', () => {
  const a = resolveStack(on('sst-fill', 'chlorophyll'), LO), b = resolveStack(on('chlorophyll', 'sst-fill'), LO);
  assert.deepEqual(repsOf(a, 'chlorophyll'), ['fill']);
  assert.equal(row(a, 'sst-fill').status, 'replaced');
  assert.equal(row(a, 'sst-fill').replacedBy, 'chlorophyll');
  assert.deepEqual(row(a, 'sst-fill').reps, []);
  assert.deepEqual(repsOf(b, 'sst-fill').slice(0, 1), ['fill']);
  assert.equal(row(b, 'chlorophyll').replacedBy, 'sst-fill');
  assert.equal(a.counts.color_field, 1);
  assert.equal(b.counts.color_field, 1);
});

// Contract P1: a loser with another representation keeps it (currents → streamlines) and stays drawn.
// Bug: currents are switched off entirely when SST takes the fill.
test('P1: currents losing the fill keep their streamlines; owning it, they draw both', () => {
  const lost = resolveStack(on('currents', 'sst-fill'), LO), kept = resolveStack(on('sst-fill', 'currents'), LO);
  assert.deepEqual(repsOf(lost, 'currents'), ['streamlines']);
  assert.equal(row(lost, 'currents').status, 'drawn');
  assert.ok(repsOf(kept, 'currents').includes('fill') && repsOf(kept, 'currents').includes('streamlines'));
});

// Contract P2: currents' streamlines own the particle slot; wind then draws barbs. Without currents wind keeps its particles.
// Bug: wind particles and current streamlines draw together (the drafted STACK-A violation).
test('P2: with currents on, wind draws barbs, not particles; without currents it keeps particles', () => {
  const both = resolveStack(on('currents', 'wind'), LO), alone = resolveStack(on('wind'), LO);
  assert.ok(repsOf(both, 'wind').includes('barbs'));
  assert.ok(!repsOf(both, 'wind').includes('particles'));
  assert.equal(both.counts.particles, 1);
  assert.ok(repsOf(alone, 'wind').includes('particles'));
  assert.ok(!repsOf(alone, 'wind').includes('barbs'));
});

// Contract P3: wind barbs beat wave arrows; waves then keep only their fill. With no barbs the arrows stay.
// Bug: wave arrows and wind barbs draw together (the draft's second arrow/barb layer).
test('P3: wind barbs take the arrow slot from wave arrows; without barbs the arrows draw', () => {
  const barbs = resolveStack(on('currents', 'wind', 'waves-swell'), LO), noBarbs = resolveStack(on('waves-swell'), LO);
  assert.deepEqual(repsOf(barbs, 'waves-swell'), ['fill']);
  assert.equal(barbs.counts.arrows_barbs, 1);
  assert.ok(repsOf(noBarbs, 'waves-swell').includes('arrows'));
  const lost = resolveStack(on('waves-swell', 'currents', 'wind'), LO);
  assert.equal(row(lost, 'waves-swell').status, 'replaced');
  assert.equal(row(lost, 'waves-swell').replacedBy, 'wind');
});

// Contract P4: one veil, the latest; the cloud veil is capped while a colour field or radar is on; sea ice never auto-enables.
// Bug: cloud and sea-ice veils stack, the cloud veil hides a field at full alpha, or a preset switches sea ice on.
test('P4: one veil (latest wins), the cloud veil cap under a field or radar, sea ice never auto-enabled', () => {
  const a = resolveStack(on('clouds', 'sea-ice'), LO), b = resolveStack(on('sea-ice', 'clouds'), LO);
  assert.equal(row(a, 'clouds').replacedBy, 'sea-ice');
  assert.equal(row(b, 'sea-ice').replacedBy, 'clouds');
  assert.equal(a.counts.veil, 1);
  const z = STACKING.opacity_by_zoom.cloud_veil[0][0];
  assert.equal(row(resolveStack(on('clouds'), z), 'clouds').opacity.veil, stopsAt(STACKING.opacity_by_zoom.cloud_veil, z));
  assert.ok(stopsAt(STACKING.opacity_by_zoom.cloud_veil, z) > STACKING.veil_cap_with_field_or_radar);
  assert.equal(row(resolveStack(on('clouds', 'sst-fill'), z), 'clouds').opacity.veil, STACKING.veil_cap_with_field_or_radar);
  assert.equal(row(resolveStack(on('clouds', 'precip-radar'), z), 'clouds').opacity.veil, STACKING.veil_cap_with_field_or_radar);
  assert.equal(mayAutoEnable('sea-ice', 'ready'), false);
  assert.equal(mayAutoEnable('clouds', 'ready'), true);
});

// Contract P5: at most two isoline sets, the latest two; the second set is dashed; SST's auto isotherms (from
// isolines_from_zoom) reserve one set. Bug: three sets draw, or automatic isotherms disappear behind two explicit sets.
test('P5: two isoline sets at most (latest), the second dashed; SST auto isotherms count as one set', () => {
  const three = resolveStack(on('ssh', 'pressure', 'sst-breaks'), LO);
  assert.equal(row(three, 'ssh').status, 'replaced');
  assert.equal(row(three, 'ssh').replacedBy, 'sst-breaks');
  assert.equal(three.counts.isolines, STACKING.caps.isolines);
  assert.equal(row(three, 'sst-breaks').dashed, true);
  assert.ok(!row(three, 'pressure').dashed);
  const two = resolveStack(on('ssh', 'pressure'), LO);
  assert.deepEqual(two.layers.map(r => r.status), ['drawn', 'drawn']);
  assert.ok(repsOf(resolveStack(on('sst-fill'), HI), 'sst-fill').includes('auto isotherms'));
  assert.ok(!repsOf(resolveStack(on('sst-fill'), LO), 'sst-fill').includes('auto isotherms'));
  assert.ok(!repsOf(resolveStack(on('sst-fill', 'sst-breaks'), HI), 'sst-fill').includes('auto isotherms'));
  const full = resolveStack(on('sst-fill', 'ssh', 'pressure'), HI);
  assert.ok(repsOf(full, 'sst-fill').includes('auto isotherms'));
  assert.equal(row(full, 'ssh').status, 'replaced');
  assert.equal(row(full, 'ssh').replacedBy, 'pressure');
  assert.equal(full.counts.isolines, STACKING.caps.isolines);
  const withOne = resolveStack(on('sst-fill', 'ssh'), HI);
  assert.equal(withOne.counts.isolines, 2);
  assert.equal(row(withOne, 'ssh').dashed, true);
});

// Contract P6: band edges hide while any isoline, particle or arrow layer is on; a colour field hides the unranked dots and
// dims kelp to opacity_with_color_field. Bug: band edges clutter the streamlines, or dots show under a fill.
test('P6: band edges, unranked dots and kelp opacity follow the other layers both ways', () => {
  assert.equal(row(resolveStack(on('sst-fill'), LO), 'sst-fill').bandEdges, true);
  for (const other of ['ssh', 'currents', 'waves-swell']) {
    assert.equal(row(resolveStack(on(other, 'sst-fill'), LO), 'sst-fill').bandEdges, false, other);
  }
  assert.deepEqual(repsOf(resolveStack(on('spots-marks'), LO), 'spots-marks'), ['badges', 'dots']);
  assert.deepEqual(repsOf(resolveStack(on('spots-marks', 'sst-fill'), LO), 'spots-marks'), ['badges']);
  const kelp = STYLE['kelp-habitat'].kelp;
  assert.equal(row(resolveStack(on('kelp-habitat'), HI), 'kelp-habitat').opacity.kelp, kelp.opacity);
  assert.equal(row(resolveStack(on('kelp-habitat', 'sst-fill'), HI), 'kelp-habitat').opacity.kelp, kelp.opacity_with_color_field);
});

// Contract: a colour-field layer that desaturates the base sets the base desaturation; without one it is 0.
// Bug: points-only stacks dim the depth ramp.
test('base desaturation follows desaturates_base', () => {
  assert.equal(resolveStack(on('sst-fill'), LO).baseDesaturation, STACKING.base_desaturation_when_field_on);
  assert.ok(STACKING.base_desaturation_when_field_on > 0);
  assert.equal(resolveStack(on('spots-marks'), LO).baseDesaturation, 0);
});

// ── No data yet and withheld ───────────────────────────────────────────────────

// Contract: a no-data or withheld layer draws nothing and takes part in no rule. Bug: a withheld SST still takes the fill
// from chlorophyll, leaving an empty map with chlorophyll "replaced".
test('no-data and withheld layers draw nothing and replace nothing', () => {
  const stack = resolveStack([{id: 'chlorophyll'}, {id: 'sst-fill', state: 'withheld'}, {id: 'kd490', state: 'no-data'}], LO);
  assert.deepEqual(repsOf(stack, 'chlorophyll'), ['fill']);
  for (const id of ['sst-fill', 'kd490']) {
    assert.deepEqual(row(stack, id).reps, []);
    assert.deepEqual(row(stack, id).opacity, {});
  }
  assert.equal(row(stack, 'sst-fill').status, 'withheld');
  assert.equal(row(stack, 'kd490').status, 'no-data');
  assert.equal(mayAutoEnable('kd490', 'no-data'), false);
});

// Contract: every new kit layer without a live source has a stub module that draws nothing and never auto-enables.
// Bug: a stub returns an overlay, or a no-data layer is missing its module (its legend row would vanish).
test('the no-data stubs: one per NO_DATA_YET layer, no overlay, never auto-enabled', () => {
  assert.deepEqual(Object.keys(KIT_LAYER_MODULES).sort(), [...NO_DATA_YET].sort());
  for (const [id, m] of Object.entries(KIT_LAYER_MODULES)) {
    assert.equal(m.id, id);
    assert.deepEqual(m.state, {kind: 'no-data'});
    assert.equal(m.autoEnable, false);
    assert.equal(m.overlay(), null);
  }
  const files = readdirSync(new URL('../web/map/kit-layers/', import.meta.url)).filter(f => !['index.ts', 'no-data.ts'].includes(f));
  assert.deepEqual(files.map(f => f.replace(/\.ts$/, '')).sort(), [...NO_DATA_YET].sort());
});

// Contract: the legend rows' states: no-data and withheld draw nothing; withheld/stale/dated carry their own time; replaced
// names the replacing layer. Bug: a dated row invents a date, or a withheld row claims to draw.
test('kitRow: the shared states, and no invented time', () => {
  assert.deepEqual(kitRow('kd490', {kind: 'no-data'}), {labelId: 'layer.skl.kd490.label', noteId: 'legend.skl.noData', vars: {}, draws: false});
  const withheld = kitRow('sst-fill', {kind: 'withheld', reason: 'past its age limit', dataTime: '2026-11-19 06:00 PST'});
  assert.equal(withheld.draws, false);
  assert.deepEqual(withheld.vars, {reason: 'past its age limit', time: '2026-11-19 06:00 PST'});
  assert.equal(kitRow('stations', {kind: 'stale', dataTime: '09:10'}).draws, true);
  assert.equal(kitRow('chlorophyll', {kind: 'dated', date: '2026-11-18'}).vars.date, '2026-11-18');
  assert.equal(kitRow('sst-fill', {kind: 'replaced', by: 'chlorophyll'}).byLabelId, 'layer.skl.chlorophyll.label');
  assert.equal(kitRow('sst-fill', {kind: 'drawn'}).noteId, null);
  assert.throws(() => kitRow('chlorophyll', {kind: 'dated', date: ''}), RangeError);
  assert.throws(() => kitRow('sst-fill', {kind: 'withheld', reason: 'old', dataTime: ' '}), RangeError);
});

// ── Registry and copy ──────────────────────────────────────────────────────────

// Contract: one registry row per kit layer in kit order, with the token's app layer ids that exist here. Bug: a kit layer
// is missing, or a row names an app id the registry does not have (its legend would throw).
test('KIT_LAYERS: the 24 kit layers in order, app ids from the tokens', () => {
  assert.equal(KIT_LAYER_IDS.length, 24);
  assert.deepEqual(KIT_LAYERS.map(k => k.id), [...KIT_LAYER_IDS]);
  const appIds = new Set(LAYERS.map(e => e.id));
  for (const k of KIT_LAYERS) {
    assert.deepEqual([...k.appIds], (STYLE[k.id].app_layer_ids ?? []).filter(id => appIds.has(id)), k.id);
    assert.equal(k.noData, NO_DATA_YET.includes(k.id));
    if (k.noData) assert.deepEqual([...k.appIds], [], k.id);
  }
  assert.equal(kitLayer('wind').labelId, 'layer.skl.wind.label');
  assert.equal(kitLayer('water-temp'), null);
});

// Contract: every kit label and state line exists in English and Spanish and no label implies catch.
// Bug: a missing Spanish string, or a label like "Fish finder".
test('copy: layer.skl.<id>.label and legend.skl.* in both languages, no catch wording', () => {
  const strings = JSON.parse(readFileSync(new URL('../catalog/app/strings.json', import.meta.url), 'utf8')).strings;
  const ids = [...KIT_LAYERS.map(k => k.labelId), ...['noData', 'withheld', 'stale', 'dated', 'replaced'].map(s => `legend.skl.${s}`)];
  for (const id of ids) {
    assert.ok(strings[id]?.en && strings[id]?.es, id);
    assert.doesNotMatch(strings[id].en, /\b(catch|bite|fish|hot ?spot)/i, id);
  }
  assert.match(strings['legend.skl.noData'].en, /\{layer\}/);
  assert.match(strings['legend.skl.withheld'].en, /\{reason\}.*\{time\}/);
  assert.match(strings['legend.skl.dated'].en, /\{date\}/);
});

// ── z_order anchors ────────────────────────────────────────────────────────────

// Contract: the anchor slots are the kit's z_order, and the skl-* ids per slot are the generated fragment's, in its order.
// Bug: a regenerated fragment adds a layer the anchors miss, so it draws at the top of the map.
test('Z_SLOTS = stacking.z_order; SKL_SLOT_LAYERS = the generated fragment by skippercast:z', () => {
  assert.deepEqual([...Z_SLOTS], STACKING.z_order.map(z => z.id));
  const fragment = JSON.parse(readFileSync(new URL('../style/generated/maplibre-layers-v1.0.0.json', import.meta.url), 'utf8'));
  const bySlot = Object.fromEntries(Z_SLOTS.map(s => [s, []]));
  for (const layer of fragment.layers) {
    const slot = layer.metadata?.['skippercast:z'];
    if (layer.id.startsWith('skl-')) bySlot[slot].push(layer.id);
  }
  assert.deepEqual(Object.fromEntries(Object.entries(SKL_SLOT_LAYERS).map(([k, v]) => [k, [...v]])), bySlot);
});

// Contract: every anchor id is unique and every web anchor is a layer id one of the web map modules really draws.
// Bug: a renamed overlay leaves a dead anchor, so overlays above it lose their place.
test('anchors: unique ids, the web ids exist in the map modules', () => {
  const ids = Z_ORDER_ANCHORS.flatMap(s => s.layers);
  assert.equal(new Set(ids).size, ids.length);
  const dir = new URL('../web/map/', import.meta.url);
  const sources = readdirSync(dir).filter(f => f.endsWith('.ts') && f !== 'layers.ts').map(f => readFileSync(new URL(f, dir), 'utf8')).join('\n');
  for (const id of ids.filter(i => !i.startsWith('skl-'))) assert.ok(sources.includes(`'${id}'`) || id === 'bottom-relief', id);
});

// Contract (with MSK-2 DRAW-ORDER-1): chlorophyll draws under the depth contours; fronts (isolines) and wind arrows draw
// above them in the kit order; zBefore lists every higher layer nearest first, ending at the static top.
// Bug: an overlay's anchors include a layer below it (MapLibre would put it under that layer).
test('zBefore: higher layers only, nearest first; chlorophyll under contours, fronts and wind above', () => {
  assert.ok(zBefore('chlorophyll').includes('depth-contours-unresolved-fill'));
  assert.ok(!zBefore('sst-fronts-band').includes('depth-contours-unresolved-fill'));
  assert.ok(zBefore('sst-fronts-band').includes('wind-casing'));
  assert.ok(!zBefore('wind-casing').includes('sst-fronts-band'));
  const flat = Z_ORDER_ANCHORS.flatMap(s => s.layers);
  for (const id of flat) {
    const before = zBefore(id);
    assert.deepEqual(before, [...flat.slice(flat.indexOf(id) + 1), 'mpa-fill'], id);
  }
  assert.deepEqual(zBefore('labels'), ['mpa-fill']);
  assert.throws(() => zBefore('no-such-layer'));
});
