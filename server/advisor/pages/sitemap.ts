// GET /sitemap-advisor.xml (08 § Public pages; TA-W1): the port pages of the
// active regions, every species page and the verified boats' pages, each in
// English with its Spanish alternate, generated from D1 on request (the route
// caches it for an hour). robots.txt names it while the advisor is on.
import {SPECIES_PAGE_KEYS} from './species.ts';
import {activePortIds} from './port.ts';
import {escapeHtml} from './render.ts';

export const SITEMAP_MAX_AGE = 3600;      // 08: cached 1 h
export const SITEMAP_PATH = '/sitemap-advisor.xml';

/** The sitemap's page paths: active ports, species, verified boats (newest report date as lastmod). */
export async function sitemapEntries(db: D1Database): Promise<{path: string; lastmod: string | null}[]> {
  const boats = (await db.prepare(`SELECT b.slug, (SELECT MAX(r.report_date) FROM advisor_reports r WHERE r.boat_id=b.id AND r.status='published') AS lastmod
      FROM advisor_boats b WHERE b.status='verified' ORDER BY b.slug LIMIT 5000`).all<{slug: string; lastmod: string | null}>()).results;
  return [
    ...activePortIds().map(id => ({path: `/ports/${id}`, lastmod: null})),
    ...SPECIES_PAGE_KEYS.map(key => ({path: `/species/${key}`, lastmod: null})),
    ...boats.map(b => ({path: `/boats/${b.slug}`, lastmod: b.lastmod})),
  ];
}

/** The sitemap XML (sitemaps.org 0.9 with xhtml:link alternates for ?lang=es). */
export async function sitemapXml(db: D1Database, base: string): Promise<string> {
  const entries = await sitemapEntries(db);
  const url = (path: string, es = false) => escapeHtml(`${base}${path}${es ? '?lang=es' : ''}`);
  const items = entries.map(e => `  <url>\n    <loc>${url(e.path)}</loc>\n${e.lastmod && /^\d{4}-\d{2}-\d{2}$/.test(e.lastmod) ? `    <lastmod>${e.lastmod}</lastmod>\n` : ''}`
    + `    <xhtml:link rel="alternate" hreflang="en" href="${url(e.path)}"/>\n    <xhtml:link rel="alternate" hreflang="es" href="${url(e.path, true)}"/>\n  </url>\n`).join('');
  return `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:xhtml="http://www.w3.org/1999/xhtml">\n${items}</urlset>\n`;
}

/** robots.txt while the advisor is on: everything allowed (as with no file) and the advisor sitemap. */
export const robotsTxt = (base: string): string => `User-agent: *\nAllow: /\n\nSitemap: ${base}${SITEMAP_PATH}\n`;
