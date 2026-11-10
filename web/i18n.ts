// Shared catalogue reader; page-sized readers reuse the same runtime.
// SC1407-09: English ships with the app (generated from catalog/app/strings.json); Spanish loads only for a
// Spanish page (web/i18n-catalogue.ts), and each entry's `es` reads that table once it is installed.
import english from './strings.en.generated.json' with {type: 'json'};
import {lookup, type Language, type Table} from './i18n-core.ts';
import {bilingual} from './i18n-catalogue.ts';
export * from './i18n-core.ts';
export {catalogueFailed, catalogueLoading, chooseReadyLanguage, initReadyLanguage, prepareCatalogue, spanishHref} from './i18n-catalogue.ts';
export type StringId = keyof typeof english;
export const STRINGS: Table = bilingual(english);
export const t = (id: StringId, lang: Language | string | null | undefined = 'en', vars: Readonly<Record<string, string | number>> = {}): string => lookup(STRINGS, id, lang, vars);
