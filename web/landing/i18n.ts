// First-paint catalogue slice, generated from catalog/app/strings.json (English only, SC1407-09).
// Share language state, resolution, interpolation, formatting and the deferred Spanish table with the app.
import strings from './strings.generated.json' with {type: 'json'};
import {lookup, type Language, type Table} from '../i18n-core.ts';
import {bilingual} from '../i18n-catalogue.ts';
export * from '../i18n-core.ts';
export {catalogueFailed, initReadyLanguage, prepareCatalogue, spanishHref} from '../i18n-catalogue.ts';
export type StringId = keyof typeof strings;
export const STRINGS: Table = bilingual(strings);
export const t = (id: StringId, lang: Language | string | null | undefined = 'en', vars: Readonly<Record<string, string | number>> = {}): string => lookup(STRINGS, id, lang, vars);
