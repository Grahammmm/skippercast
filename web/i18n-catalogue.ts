// SC1407-09: the Spanish table, loaded only when the page language is Spanish. The readers (web/i18n.ts, the
// landing's web/landing/i18n.ts) ship English only and register it here; their entries read Spanish through
// a getter, so t() stays synchronous and renders English until the table is installed, never a blank or an id.
// The table loads once per page (one shared request, kept on success, retried only on a new request after a
// failure) and is installed whole, only once it covers every id a registered reader has. The ready-language
// helpers wrap web/i18n-core.ts's synchronous initLanguage/setLanguage: Spanish is applied only once its table
// is ready, and a failed load keeps English and raises `catalogueFailed` (one local notice, beside the choice).
//
// Erasable syntax only: Node tests import this file by type stripping.
import {signal} from '@preact/signals';
import {initLanguage, language, setLanguage, withLanguageParam, type Entry, type Language, type LanguageEnv, type Table} from './i18n-core.ts';

type Spanish = Readonly<Record<string, string>>;
let table: Spanish | null = null;
let pending: Promise<void> | null = null;
let choice = 0;
const readers: Readonly<Record<string, {en: string}>>[] = [];

/** True once the Spanish table could not be loaded for a Spanish request (cleared by a later success). */
export const catalogueFailed = signal(false);
/** True while a chosen Spanish waits for its table. */
export const catalogueLoading = signal(false);

/** The Spanish module. Literal, so the bundler emits the table as its own chunk that English pages never request. */
const importSpanish = (): Promise<{default: unknown}> => import('./strings.es.generated.json', {with: {type: 'json'}});

/** The ids of the registered readers `es` has no non-empty Spanish string for. */
function missing(es: Readonly<Record<string, unknown>>): string[] {
  const gaps: string[] = [];
  for (const english of readers) for (const id of Object.keys(english)) {
    const text = Object.hasOwn(es, id) ? es[id] : undefined;
    if (typeof text !== 'string' || text === '') gaps.push(id);
  }
  return gaps;
}

/** A reader's table: its English entries, each with an `es` getter that reads the Spanish table once installed. */
export function bilingual(english: Readonly<Record<string, {en: string}>>): Table {
  readers.push(english);
  const entries: Record<string, Entry> = {};
  for (const [id, {en}] of Object.entries(english)) {
    entries[id] = Object.freeze({en, get es(): string | undefined { return table !== null && Object.hasOwn(table, id) ? table[id] : undefined; }});
  }
  return Object.freeze(entries);
}

/** The Spanish text of `id`, or undefined before the table is installed. */
export const spanish = (id: string): string | undefined => table !== null && Object.hasOwn(table, id) ? table[id] : undefined;

/** True once the Spanish table is installed. */
export const spanishReady = (): boolean => table !== null;

/** Resolve once `lang`'s table is ready: English at once; Spanish after its one shared load. Rejects on a failed or incomplete table. */
export function prepareCatalogue(lang: Language | string): Promise<void> {
  if (lang !== 'es') return Promise.resolve();
  if (table !== null) {
    const gaps = missing(table);
    return gaps.length ? Promise.reject(Error(`Spanish table lacks ${gaps.length} id(s), first ${gaps[0]}`)) : Promise.resolve();
  }
  pending ??= importSpanish().then(module => {
    const es = module?.default;
    if (!es || typeof es !== 'object' || Array.isArray(es)) throw Error('Spanish table is not an object');
    const gaps = missing(es as Record<string, unknown>);
    if (gaps.length) throw Error(`Spanish table lacks ${gaps.length} id(s), first ${gaps[0]}`);
    table = Object.freeze({...(es as Spanish)});
  }).finally(() => { pending = null; });
  return pending;
}

/** env.doc, else the page's document (as web/i18n-core.ts's default environment). */
function documentOf(env: LanguageEnv | undefined): LanguageEnv['doc'] {
  if (env) return env.doc ?? null;
  try { return globalThis.document ?? null; } catch { return null; }
}

/** English in effect, for a Spanish request whose table failed: the stored preference and the link are kept, so a reload or retry asks again. */
function keepEnglish(env: LanguageEnv | undefined): Language {
  language.value = 'en';
  const doc = documentOf(env);
  if (doc) doc.documentElement.lang = 'en';
  catalogueLoading.value = false;
  catalogueFailed.value = true;
  return 'en';
}

/**
 * initLanguage (the link, the stored preference, then the browser's list), then wait for that language's table:
 * the page's first translated render follows this. Never rejects: a failed Spanish load resolves English.
 */
export async function initReadyLanguage(env?: LanguageEnv): Promise<Language> {
  const lang = initLanguage(env);
  if (lang !== 'es') return lang;
  const mine = ++choice;
  try {
    await prepareCatalogue('es');
    catalogueFailed.value = false;
    return lang;
  } catch {
    return mine === choice ? keepEnglish(env) : language.peek();
  }
}

/**
 * A deliberate choice (the app menu). English applies at once. Spanish keeps the current language until its
 * table is ready, then applies through setLanguage; a newer choice made meanwhile wins, and a failed load keeps
 * the current language and raises `catalogueFailed`. Never rejects; resolves the language in effect.
 */
export async function chooseReadyLanguage(lang: Language, env?: LanguageEnv): Promise<Language> {
  const mine = ++choice;
  if (lang !== 'es') { catalogueLoading.value = false; return setLanguage(lang, env); }
  if (table === null) catalogueLoading.value = true;
  try {
    await prepareCatalogue('es');
  } catch {
    if (mine === choice) { catalogueLoading.value = false; catalogueFailed.value = true; }
    return language.peek();
  }
  if (mine !== choice) return language.peek();
  catalogueLoading.value = false;
  catalogueFailed.value = false;
  return setLanguage('es', env);
}

/** `href` asking for Spanish: its `lang` parameter set to es, or `lang=es` added; other parameters and the hash kept. */
export function spanishHref(href: string): string {
  const replaced = withLanguageParam(href, 'es');
  if (replaced !== null) return replaced;
  const url = new URL(href, 'https://x.invalid/');
  return `${url.pathname}${url.search ? `${url.search}&` : '?'}lang=es${url.hash}`;
}
