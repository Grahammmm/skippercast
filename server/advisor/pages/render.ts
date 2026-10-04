// Server-rendered public pages (docs/plans/text-advisor/08-website.md § Public
// pages; TA-W1): the `html` tagged template, which escapes every interpolated
// value unless it is wrapped in raw() (or is the result of another html``),
// and the layout shell every page family shares: head (title, description,
// canonical, Open Graph image, JSON-LD Organization + BreadcrumbList, the
// hashed stylesheet from ADVISOR_ASSETS), a header, the page body, the "Text
// SkipperCast" call to action with its QR code, the standard disclaimer line
// and the web chat island. Every user-facing string comes from
// web/advisor/copy.ts (PAGES_COPY), which the copy lint covers.
import {PAGES_COPY} from '../../../web/advisor/copy.ts';
import type {PageCopy, PageLanguage} from '../../../web/advisor/copy.ts';
import {build} from '../../config.ts';

/** A trusted HTML fragment: html`` results and raw() values are inserted as they are. */
export class Html {
  readonly value: string;
  constructor(value: string) { this.value = value; }
  toString(): string { return this.value; }
}
/** Mark a string as trusted HTML. Only for fragments built here, never for data. */
export const raw = (value: string): Html => new Html(value);

const ESCAPES: Record<string, string> = {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'};
export const escapeHtml = (value: unknown): string => String(value).replace(/[&<>"']/g, ch => ESCAPES[ch]!);

type Value = Html | string | number | boolean | null | undefined | readonly Value[];
const part = (value: Value): string => {
  if (value === null || value === undefined || value === false || value === true) return '';
  if (value instanceof Html) return value.value;
  if (Array.isArray(value)) return value.map(part).join('');
  return escapeHtml(value);
};
/** Escaping template: `html\`<p>${name}</p>\`` escapes name; arrays are joined; null, undefined and booleans render nothing. */
export function html(strings: TemplateStringsArray, ...values: Value[]): Html {
  let out = strings[0]!;
  for (let i = 0; i < values.length; i++) out += part(values[i]!) + strings[i + 1]!;
  return new Html(out);
}

/** JSON for a <script type="application/ld+json"> block: `<`, `>` and `&` escaped so no value can close the element. */
export const jsonLd = (value: unknown): Html => raw(JSON.stringify(value).replace(/</g, '\\u003c').replace(/>/g, '\\u003e').replace(/&/g, '\\u0026'));

// ---- language -----------------------------------------------------------------------------

/** ?lang=es|en wins; otherwise the first Accept-Language range decides (es-* is Spanish); English by default. */
export function pageLanguage(url: URL, acceptLanguage: string | null | undefined): PageLanguage {
  const asked = url.searchParams.get('lang');
  if (asked === 'es' || asked === 'en') return asked;
  const ranges = String(acceptLanguage ?? '').split(',').map(part => {
    const [tag = '', ...params] = part.trim().toLowerCase().split(';');
    const q = params.map(p => /^\s*q=([0-9.]+)\s*$/.exec(p)?.[1]).find(Boolean);
    return {tag: tag.trim(), q: q === undefined ? 1 : Number(q)};
  }).filter(r => r.tag && r.q > 0).sort((a, b) => b.q - a.q);
  const first = ranges.find(r => r.tag === 'es' || r.tag.startsWith('es-') || r.tag === 'en' || r.tag.startsWith('en-'));
  return first && (first.tag === 'es' || first.tag.startsWith('es-')) ? 'es' : 'en';
}
export const copyFor = (language: PageLanguage): PageCopy => PAGES_COPY[language];

// ---- assets -------------------------------------------------------------------------------

/**
 * The hashed paths the build exposes (scripts/build-worker.mjs, ADVISOR_ASSETS):
 * 'advisor/pages.css' is dist/chat.html's stylesheet set (tokens, the chat
 * island's and the pages' styles) and 'advisor/chat.js' its entry script (the
 * chat island and the pages' telemetry). Empty in a bare dev or test run.
 */
export function advisorAssets(): Readonly<Record<string, string>> {
  return typeof ADVISOR_ASSETS === 'undefined' || !ADVISOR_ASSETS ? {} : ADVISOR_ASSETS;
}
const assetPath = (name: string): string | null => {
  const path = advisorAssets()[name];
  return typeof path === 'string' && /^\/assets\/[\w.-]+\.(?:css|js)$/.test(path) ? path : null;
};

// ---- layout -------------------------------------------------------------------------------

export type PageKind = 'port' | 'species' | 'boat' | 'missing';
export interface Crumb {name: string; path: string | null}
export interface PageOptions {
  language: PageLanguage;
  kind: PageKind;
  /** Site path of this page, without query (the canonical adds ?lang=es for Spanish). */
  path: string;
  title: string;
  description: string;
  /** Absolute or site path of the Open Graph image; the site preview when null. */
  image?: string | null;
  crumbs: Crumb[];
  /** The region id for telemetry ('' when the page has none). */
  region?: string;
  /** noindex: unverified boats and the not-found page. */
  noindex?: boolean;
  /** The prefilled text of the call to action (the default greeting when omitted). */
  ctaMessage?: string;
  body: Html;
}
export interface SiteSettings {publicBase: string; number: string | null}

export const PREVIEW_IMAGE = '/skippercast-parker-preview.jpg';
const absolute = (base: string, path: string): string => /^https:\/\//.test(path) ? path : base + (path.startsWith('/') ? path : `/${path}`);
/** The canonical URL of a page in a language: English has no query, Spanish ?lang=es. */
export const canonicalUrl = (base: string, path: string, language: PageLanguage): string => `${base}${path}${language === 'es' ? '?lang=es' : ''}`;

/** The source marker the call to action's text carries (03 § deep links; the same as the chat's "Text us"). */
export const CTA_SOURCE = 'web';
/** The SMS deep link of the call to action (the same ?&body= form as GET /text), or null while no number is set. */
export function ctaHref(settings: SiteSettings, message: string): string | null {
  if (!settings.number) return null;
  return `sms:${settings.number}?&body=${encodeURIComponent(`${message} [via ${CTA_SOURCE}]`)}`;
}

function cta(copy: PageCopy, settings: SiteSettings, message: string | undefined): Html {
  const href = ctaHref(settings, message || copy.ctaDefaultMessage);
  return html`<section class="adv-cta" aria-labelledby="adv-cta-title">
  <div class="adv-cta-text">
    <h2 id="adv-cta-title">${copy.ctaHeading}</h2>
    <p>${copy.ctaBody}</p>
    ${href
      ? html`<p class="adv-cta-actions"><a class="adv-button" href="${href}" data-advisor-cta>${copy.ctaButton}</a> <a class="adv-link" href="/contact.vcf">${copy.saveContact}</a></p>`
      : html`<p class="adv-cta-actions"><a class="adv-button" href="/chat.html" data-advisor-cta>${copy.ctaChat}</a></p>`}
  </div>
  <img class="adv-cta-qr" src="/qr/text.svg" width="132" height="132" alt="${copy.qrAlt}" loading="lazy">
</section>`;
}

/** The whole page. */
export function layout(page: PageOptions, settings: SiteSettings): string {
  const copy = copyFor(page.language), base = settings.publicBase;
  const canonical = canonicalUrl(base, page.path, page.language);
  const other: PageLanguage = page.language === 'es' ? 'en' : 'es';
  const image = absolute(base, page.image || PREVIEW_IMAGE);
  const css = assetPath('advisor/pages.css'), js = assetPath('advisor/chat.js');
  const crumbs: Crumb[] = [{name: copy.home, path: '/'}, ...page.crumbs];
  const ld = [
    {'@context': 'https://schema.org', '@type': 'Organization', name: 'SkipperCast', url: `${base}/`, logo: `${base}/app-icon-512.png`},
    // Only crumbs with a page of their own (there is no index of ports, species or boats).
    {'@context': 'https://schema.org', '@type': 'BreadcrumbList', itemListElement: crumbs.filter(c => c.path).map((c, i) => ({'@type': 'ListItem', position: i + 1, name: c.name,
      item: c.path === '/' ? `${base}/` : canonicalUrl(base, c.path!, page.language)}))},
  ];
  const doc = html`<!doctype html>
<html lang="${page.language}" prefix="og: https://ogp.me/ns#">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>${page.title}</title>
<meta name="description" content="${page.description}">
${page.noindex ? raw('<meta name="robots" content="noindex">\n') : ''}<link rel="canonical" href="${canonical}">
${page.kind === 'missing' ? '' : html`<link rel="alternate" hreflang="${page.language}" href="${canonical}">
<link rel="alternate" hreflang="${other}" href="${canonicalUrl(base, page.path, other)}">
`}<meta property="og:type" content="website">
<meta property="og:site_name" content="SkipperCast">
<meta property="og:locale" content="${page.language === 'es' ? 'es_US' : 'en_US'}">
<meta property="og:url" content="${canonical}">
<meta property="og:title" content="${page.title}">
<meta property="og:description" content="${page.description}">
<meta property="og:image" content="${image}">
<meta name="twitter:card" content="summary_large_image">
<meta name="skippercast-build" content="${build()}">
<link rel="icon" href="/app-icon.svg" type="image/svg+xml">
${css ? html`<link rel="stylesheet" href="${css}">` : ''}
<script type="application/ld+json">${jsonLd(ld)}</script>
</head>
<body class="adv-page" data-advisor-page="${page.kind}" data-region="${page.region ?? ''}">
<a class="adv-skip" href="#main">${copy.skip}</a>
<header class="adv-header">
  <a class="adv-brand" href="/">⌁ SkipperCast</a>
  ${page.kind === 'missing' ? '' : html`<a class="adv-lang" href="${page.path}${other === 'es' ? '?lang=es' : '?lang=en'}" hreflang="${other}" lang="${other}">${copy.otherLanguage}</a>`}
</header>
<nav class="adv-crumbs" aria-label="${copy.breadcrumbs}"><ol>${crumbs.map((c, i) => i === crumbs.length - 1
    ? html`<li><span aria-current="page">${c.name}</span></li>`
    : html`<li>${c.path ? html`<a href="${c.path}${page.language === 'es' && c.path !== '/' ? '?lang=es' : ''}">${c.name}</a>` : c.name}</li>`)}</ol></nav>
<main id="main" class="adv-main">
${page.body}
${cta(copy, settings, page.ctaMessage)}
</main>
<footer class="adv-footer">
  <p>${copy.disclaimer}</p>
  <p><a href="/">${copy.openMap}</a> · <a href="/terms.html">${copy.terms}</a> · <a href="/privacy.html">${copy.privacy}</a></p>
</footer>
<div id="advisor-chat" class="chat-host"></div>
${js ? html`<script type="module" src="${js}"></script>` : ''}
</body>
</html>
`;
  return doc.value;
}

/** An HTML response for a page; `maxAge` seconds of public caching (0: no-store). */
export function pageResponse(body: string, {status = 200, maxAge = 0, language}: {status?: number; maxAge?: number; language: PageLanguage}): Response {
  return new Response(body, {status, headers: {
    'Content-Type': 'text/html; charset=utf-8',
    'Content-Language': language,
    'Cache-Control': maxAge > 0 && status === 200 ? `public, max-age=${maxAge}` : 'no-store',
    'Vary': 'Accept-Language',
    'X-Content-Type-Options': 'nosniff',
  }});
}

// ---- small formatters shared by the pages -------------------------------------------------

/** "Sat, Oct 3" / "sáb, 3 oct" for a YYYY-MM-DD date. */
export function shortDate(date: string, language: PageLanguage): string {
  const d = new Date(`${date}T12:00:00Z`);
  if (Number.isNaN(d.getTime())) return date;
  return new Intl.DateTimeFormat(language === 'es' ? 'es-MX' : 'en-US', {weekday: 'short', month: 'short', day: 'numeric', timeZone: 'UTC'}).format(d);
}
/** "Oct 3, 2026" / "3 oct 2026". */
export function longDate(date: string, language: PageLanguage): string {
  const d = new Date(`${String(date).slice(0, 10)}T12:00:00Z`);
  if (Number.isNaN(d.getTime())) return String(date);
  return new Intl.DateTimeFormat(language === 'es' ? 'es-MX' : 'en-US', {year: 'numeric', month: 'short', day: 'numeric', timeZone: 'UTC'}).format(d);
}

export interface CountLine {label: string; species_key: string; kept: number | null; released: number | null}
/** Report counts from counts_json (at most 12 lines), [] when it is not a list. */
export function countLines(json: string | null | undefined): CountLine[] {
  try {
    const v = JSON.parse(String(json ?? ''));
    return Array.isArray(v) ? v.filter(c => c && typeof c.label === 'string').slice(0, 12).map(c => ({label: String(c.label).slice(0, 40),
      species_key: typeof c.species_key === 'string' ? c.species_key : 'other',
      kept: Number.isFinite(c.kept) ? c.kept : null, released: Number.isFinite(c.released) ? c.released : null})) : [];
  } catch { return []; }
}
/** "45 vermilion, 12 lingcod (2 released)". */
export function countsText(lines: readonly CountLine[], copy: PageCopy): string {
  return lines.map(c => {
    const kept = c.kept ?? 0, rel = c.released ?? 0;
    if (!kept && rel) return copy.releasedOnly(rel, c.label);
    return rel ? `${kept} ${c.label} (${copy.released(rel)})` : `${kept} ${c.label}`;
  }).join(', ');
}
