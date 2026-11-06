// SC0922-14: the words of the account panel, handed to dist/account.js when the panel opens.
// That module is loaded on demand and cannot call t() like the bundled screens, so this builds the
// `account.*` catalogue values for one language: finished, un-interpolated templates (the panel fills
// {name} variables itself, as plain text, and escapes at the page). A missing Spanish value reads English.
//
// Erasable syntax only: Node tests import this file by type stripping.
import {STRINGS, type Language} from './i18n.ts';

export interface AccountOptions { readonly lang: Language; readonly strings: Readonly<Record<string, string>> }

/** The language and the `account.*` templates for it; an unsupported language reads English. */
export function accountOptions(lang: Language | string | null | undefined): AccountOptions {
  const resolved: Language = lang === 'es' ? 'es' : 'en';
  const strings: Record<string, string> = {};
  for (const [id, entry] of Object.entries(STRINGS))
    if (id.startsWith('account.')) strings[id] = (resolved === 'es' && entry.es) || entry.en;
  return {lang: resolved, strings};
}
