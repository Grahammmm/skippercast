import {habitatFamily} from '../map/habitat.ts';
import {t, type Language, type StringId} from '../i18n.ts';
import {LINES_OFF, menuList, SPOTS_OFF} from '../map/layers.ts';
import {current, DEFAULT_CURRENT, layers, layersParam, setParams} from '../state.ts';

// Preset ids are stable (state and tests use them); only the label is language-dependent.
const LABELS = {'reef-drift': 'preset.reefDrift', halibut: 'preset.halibut', crab: 'preset.crab', offshore: 'preset.offshore', transit: 'preset.transit'} as const satisfies Record<string, StringId>;
/** The label of preset `id` in `lang`; an unknown id (including an inherited object key) is returned as given. */
export const presetLabel = (id: string, lang: Language = 'en'): string => Object.hasOwn(LABELS, id) ? t(LABELS[id as keyof typeof LABELS], lang) : id;

// MB-13 (MAP-DESIGN-LOCK § 2.5): the menu shows one field (water temp or chlorophyll) and one flow (swell or currents)
// at a time, so no preset may name two of a kind. Reef drift reads the drift (currents) without swell; Offshore reads the
// temperature breaks (water temp and its contrast) without chlorophyll.
export const PRESETS = Object.freeze([
  {id: 'reef-drift', label: presetLabel('reef-drift'), layers: Object.freeze(['seafloor', 'currents']), current: DEFAULT_CURRENT},
  {id: 'halibut', label: presetLabel('halibut'), layers: Object.freeze(['seafloor', 'water-temp', 'currents']), current: DEFAULT_CURRENT},
  {id: 'crab', label: presetLabel('crab'), layers: Object.freeze(['seafloor', 'swell']), current: 'off'},
  {id: 'offshore', label: presetLabel('offshore'), layers: Object.freeze(['water-temp', 'sst-contrast', 'swell']), current: 'off'},
  {id: 'transit', label: presetLabel('transit'), layers: Object.freeze(['swell', 'stations']), current: 'off'},
].map(p => Object.freeze(p)));

/**
 * The menu's own switches, which no preset sets: Depth lines (off while the list has `lines-off`) and Spots & charter
 * activity (the `spots-off` marker and the published charter areas, `fleet`). Applying a preset keeps them as they are,
 * and matching ignores them.
 */
const SWITCHES: readonly string[] = [LINES_OFF, SPOTS_OFF, 'fleet'];
const conditionRows = (ids: readonly string[]): string[] => ids.filter(id => !SWITCHES.includes(id));

export function activePreset(ids: readonly string[], source: string): string | null {
  const rows = conditionRows(ids);
  return PRESETS.find(p => p.current === source && p.layers.length === rows.length &&
    new Set(rows).size === rows.length && p.layers.every(id => rows.includes(id)))?.id ?? null;
}

/** The rail list preset `layers` makes of `list`: its rows replace every condition row, through the menu's one-field/one-flow rule, and the switches stay. */
export function presetList(list: readonly string[], layers: readonly string[]): string[] {
  return layers.reduce<string[]>((next, id) => menuList(next, id, true), list.filter(id => SWITCHES.includes(id)));
}

export function presetsFor(target: string) {
  const family = habitatFamily(target);
  const id = family === 'reef' ? 'reef-drift' : family === 'dungeness' ? 'crab' : family === 'halibut' ? 'halibut' : null;
  const first = PRESETS.find(p => p.id === id);
  return first ? [first, ...PRESETS.filter(p => p !== first)] : PRESETS;
}

export function applyPreset(id: string): void {
  const preset = PRESETS.find(p => p.id === id);
  if (!preset || activePreset(layers.value, current.value) === id) return;
  // setParams replaces the current entry: preserve the old state for Back first.
  history.pushState(history.state, '', location.href);
  setParams({layers: layersParam(presetList(layers.value, preset.layers)), current: preset.current});
}
