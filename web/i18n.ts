// Shared catalogue reader; page-sized readers reuse the same runtime.
import catalog from '../catalog/app/strings.json' with {type: 'json'};
import {lookup, type Language, type Table} from './i18n-core.ts';
export * from './i18n-core.ts';
export type StringId = keyof typeof catalog.strings;
export const STRINGS: Table = catalog.strings;
export const t = (id: StringId, lang: Language | string | null | undefined = 'en', vars: Readonly<Record<string, string | number>> = {}): string => lookup(STRINGS, id, lang, vars);
