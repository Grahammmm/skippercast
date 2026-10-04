// Every user-facing string the engine sends without the model
// (docs/plans/text-advisor/04-advisor-engine.md), keyed, in English and
// Spanish, from catalog/advisor/strings.json. `{name}` is a variable;
// `{{link:...}}` placeholders are left for links.ts to resolve.
// tests/test_advisor_strings.mjs checks that every key has both languages
// with the same variables.
import catalog from '../../catalog/advisor/strings.json' with {type: 'json'};
import type {Language} from './types.ts';

export type StringKey = keyof typeof catalog.strings;
export const STRINGS: Readonly<Record<StringKey, Record<Language, string>>> = catalog.strings;
export const LANGUAGES: readonly Language[] = ['en', 'es'];

/** The string for `key` in `language` (English when the language is unknown), with `{name}` variables filled in. */
export function t(language: string | null | undefined, key: StringKey, vars: Record<string, string | number> = {}): string {
  const entry = STRINGS[key];
  if (!entry) throw Error(`unknown string ${String(key)}`);
  const text = entry[language === 'es' ? 'es' : 'en'];
  return text.replace(/\{(\w+)\}/g, (whole, name: string) => Object.hasOwn(vars, name) ? String(vars[name]) : whole);
}

/** Both languages' text of `key` (no variables filled): for recognising a fixed reply. */
export const both = (key: StringKey): string[] => LANGUAGES.map(l => STRINGS[key][l]);

/** The `{name}` variables a string uses, sorted (the strings test compares en and es). */
export const variablesOf = (text: string): string[] => [...new Set([...text.matchAll(/\{(\w+)\}/g)].map(m => m[1]!))].sort();
