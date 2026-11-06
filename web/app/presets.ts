import {habitatFamily} from '../map/habitat.ts';
import {t, type Language, type StringId} from '../i18n.ts';
import {current, DEFAULT_CURRENT, layers, layersParam, setParams} from '../state.ts';

// Preset ids are stable (state and tests use them); only the label is language-dependent.
const LABELS = {'reef-drift': 'preset.reefDrift', halibut: 'preset.halibut', crab: 'preset.crab', offshore: 'preset.offshore', transit: 'preset.transit'} as const satisfies Record<string, StringId>;
/** The label of preset `id` in `lang`; an unknown id (including an inherited object key) is returned as given. */
export const presetLabel = (id: string, lang: Language = 'en'): string => Object.hasOwn(LABELS, id) ? t(LABELS[id as keyof typeof LABELS], lang) : id;

export const PRESETS = Object.freeze([
  {id: 'reef-drift', label: presetLabel('reef-drift'), layers: Object.freeze(['seafloor', 'currents', 'swell']), current: DEFAULT_CURRENT},
  {id: 'halibut', label: presetLabel('halibut'), layers: Object.freeze(['seafloor', 'water-temp', 'currents']), current: DEFAULT_CURRENT},
  {id: 'crab', label: presetLabel('crab'), layers: Object.freeze(['seafloor', 'swell']), current: 'off'},
  {id: 'offshore', label: presetLabel('offshore'), layers: Object.freeze(['water-temp', 'sst-contrast', 'chlorophyll', 'swell']), current: 'off'},
  {id: 'transit', label: presetLabel('transit'), layers: Object.freeze(['swell', 'stations']), current: 'off'},
].map(p => Object.freeze(p)));

export function activePreset(ids: readonly string[], source: string): string | null {
  return PRESETS.find(p => p.current === source && p.layers.length === ids.length &&
    new Set(ids).size === ids.length && p.layers.every(id => ids.includes(id)))?.id ?? null;
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
  setParams({layers: layersParam(preset.layers), current: preset.current});
}
