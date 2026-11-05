// First-paint catalogue slice, generated from catalog/app/strings.json.
// Share language state, resolution, interpolation and formatting with the app.
import strings from './strings.generated.json' with {type: 'json'};
import {lookup, type Language, type Table} from '../i18n-core.ts';
export * from '../i18n-core.ts';
export type StringId = keyof typeof strings;
export const STRINGS: Table = strings;
export const t = (id: StringId, lang: Language | string | null | undefined = 'en', vars: Readonly<Record<string, string | number>> = {}): string => lookup(STRINGS, id, lang, vars);
