// SC0707-05: the landing's Spanish. The hero and footer are static HTML (dist/landing.html) so the largest paint waits for
// nothing; after the entry module has resolved the language (web/i18n.ts initLanguage, the map app's own choice) this file
// rewrites those hosts' text from the catalogue (catalog/app/strings.json) and gives the port chooser its catalogue-backed
// copy. English is the page as served: applyLandingCopy makes no DOM write for it, and portCopy('en') is web/ports.ts COPY
// word for word (tests/test_landing_i18n.mjs). Erasable syntax only: Node tests import this file by type stripping.
import {STRINGS, t, type Language, type StringId} from '../i18n.ts';
import type {Port} from '../ports.ts';

/** The hosts the static page marks: `data-i18n` (the element's text), `data-i18n-lead` (only its first text node: the planning line keeps its Terms link) and `data-i18n-aria` (its aria-label). */
type Host = {getAttribute(name: string): string | null; setAttribute(name: string, value: string): void; textContent: string | null; firstChild?: {nodeType: number; nodeValue: string | null} | null};
type Page = {querySelectorAll(selector: string): ArrayLike<Host>};

const TEXT_NODE = 3;

/**
 * Put the page's static hosts into `lang`. Only text and aria-label of the marked hosts are written (never markup, links,
 * metadata or structured data); an unknown id leaves the host as it is. English writes nothing.
 */
export function applyLandingCopy(doc: Page, lang: Language): void {
  if (lang === 'en') return;
  const safe = (id: string | null): string | null => id && Object.hasOwn(STRINGS, id) ? t(id as StringId, lang) : null;
  for (const host of Array.from(doc.querySelectorAll('[data-i18n]'))) {
    const next = safe(host.getAttribute('data-i18n'));
    if (next !== null) host.textContent = next;
  }
  for (const host of Array.from(doc.querySelectorAll('[data-i18n-lead]'))) {
    const next = safe(host.getAttribute('data-i18n-lead')), lead = host.firstChild;
    if (next !== null && lead && lead.nodeType === TEXT_NODE) lead.nodeValue = `${next} `;
  }
  for (const host of Array.from(doc.querySelectorAll('[data-i18n-aria]'))) {
    const next = safe(host.getAttribute('data-i18n-aria'));
    if (next !== null) host.setAttribute('aria-label', next);
  }
}

/** web/ports.ts COPY's shape, its messages from the catalogue in `lang`. The port's name and forecast name are published and stay as they are. */
export function portCopy(lang: Language) {
  return {
    question: t('landing.port.question', lang),
    placeholder: t('landing.port.placeholder', lang),
    finding: t('landing.port.finding', lang),
    unsupported: t('landing.port.unsupported', lang),
    unavailable: t('landing.port.unavailable', lang),
    none: t('landing.port.none', lang),
    empty: t('landing.port.empty', lang),
    privacy: t('landing.port.privacy', lang),
    forget: t('landing.port.forget', lang),
    forgotten: t('landing.port.forgotten', lang),
    found: (port: Port): string => t('landing.port.found', lang, {name: port.name}),
    detail: (port: Port): string => t('landing.port.detail', lang, {kind: t(port.status === 'active' ? 'landing.port.active' : 'landing.port.preview', lang), name: port.forecast_name}),
  } as const;
}
