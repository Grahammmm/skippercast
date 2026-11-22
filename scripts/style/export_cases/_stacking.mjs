// MSKL-3 (`--stacking-only`, plan § 4.2 step 9): a case's `layers`, `base_desaturation` and `opacity` from the stacking
// engine and the generated tokens alone. A preset case (25-STACK-A, 26-NEAR-D) resolves the preset's layers; a layer case
// (01–24) resolves that one layer switched on, at its kit view and zoom. No fixture is read: the harness passes only the case name.
import {LAYERS_STYLE} from '../../../web/map/layers-style.gen.ts';
import {KIT_LAYER_IDS, STACKING, fieldOpacity, presetStack, resolveStack, stackLabel} from '../../../web/map/stacking.ts';

export async function render(input) {
  const match = /^\d{2}-(.+)$/.exec(input.case ?? '');
  if (!match) throw new Error(`not a kit case name: ${input.case}`);
  const name = match[1];
  let view, zoom, stack;
  if (Object.hasOwn(STACKING.presets, name)) {
    ({view, zoom} = STACKING.presets[name]);
    stack = presetStack(name);
  } else if (KIT_LAYER_IDS.includes(name)) {
    ({view, zoom} = LAYERS_STYLE.layers[name]);
    stack = resolveStack([{id: name}], zoom);
  } else {
    throw new Error(`no kit layer or preset named ${name}`);
  }
  const opacity = fieldOpacity(stack);
  const metrics = {case: name, view, zoom, layers: stack.layers.map(stackLabel), base_desaturation: stack.baseDesaturation,
    ...(opacity === undefined ? {} : {opacity})};
  return {metrics};
}
