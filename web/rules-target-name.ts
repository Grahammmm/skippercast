import type {Language} from './i18n-core.ts';
import {pickerLabel} from './species.ts';

// Like the Target picker, keep the name itself the same in both languages.
export function rulesTargetName(target: string, profileName: string | null | undefined, _lang: Language): string {
  if (target === 'reef') return 'Lingcod & rockfish';
  if (typeof profileName === 'string' && profileName.length > 0) return profileName;
  return pickerLabel(target);
}