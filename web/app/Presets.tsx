import {signal} from '@preact/signals';
import {PROFILE_TABLE} from '../profile.ts';
import {current, layers, profile, readStored, species, STORAGE_KEYS, writeStored} from '../state.ts';
import {Chip} from '../ui/Chip.tsx';
import {activePreset, applyPreset, presetsFor} from './presets.ts';

export const helm = signal(readStored(STORAGE_KEYS.helm) === '1');
function syncClass(on: boolean): void {
  if (typeof document !== 'undefined') document.documentElement.classList.toggle('helm', on);
}
syncClass(helm.value);
export function setHelm(on: boolean): void {
  helm.value = on;
  writeStored(STORAGE_KEYS.helm, on ? '1' : '0');
  syncClass(on);
}

export function Presets() {
  const target = species.value ?? PROFILE_TABLE[profile.value].defaultTarget;
  const active = activePreset(layers.value, current.value);
  return <>
    <div role="group" aria-label="Layer presets" class="ui-segmented">
      {presetsFor(target).map(p => <Chip key={p.id} on={active === p.id} onClick={() => applyPreset(p.id)}>{p.label}</Chip>)}
    </div>
    <button type="button" class="ui-button" role="switch" aria-checked={helm.value} onClick={() => setHelm(!helm.value)}>Helm view</button>
  </>;
}
