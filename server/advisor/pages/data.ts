// Shared reads for the public pages (TA-W1; 08 § Public pages): the pages
// version that keys the edge cache (05 § boat page), the public photos of a
// boat or port, the report table and the not-found page.
import {PAGES_VERSION_KEY} from '../intake/reports.ts';
import {derivedKey} from '../media.ts';
import {html, layout, countLines, countsText, shortDate, copyFor} from './render.ts';
import type {Html, SiteSettings} from './render.ts';
import type {PageCopy, PageLanguage} from '../../../web/advisor/copy.ts';
import type {Env} from '../../env.ts';

/** What a page read can be given in tests: the feed reader (answers/feeds.ts) and the clock. */
export interface PageDeps {feeds?: (url: string) => Promise<unknown>; clock?: () => number}

/** job_state advisor.pages.version (bumped on publish, edit, verification and photo approval), '0' before the first bump. One D1 read. */
export async function pagesVersion(db: D1Database): Promise<string> {
  const row = await db.prepare('SELECT value FROM job_state WHERE key=?').bind(PAGES_VERSION_KEY).first<{value: string}>();
  return row?.value && /^\d{1,12}$/.test(row.value) ? row.value : '0';
}

export interface PublicPhoto {id: string; url: string; credit: string | null; width: number | null; height: number | null}

/**
 * Approved or posted images that GET /media/<id>.jpg will serve: a stripped
 * JPEG original, or one whose derived public.jpg exists in ADVISOR_MEDIA (one
 * head per candidate). `where` is a fixed SQL condition on `m` (and `b`, the boat).
 */
export async function publicPhotos(env: Env, where: string, binds: unknown[], limit: number): Promise<PublicPhoto[]> {
  const rows = (await env.DB!.prepare(`SELECT m.id,m.mime,m.exif_stripped,m.credit,m.width,m.height FROM advisor_media m JOIN advisor_boats b ON b.id=m.boat_id
      WHERE ${where} AND m.kind='image' AND m.publish_state IN ('approved','posted') ORDER BY m.created_at DESC, m.id LIMIT ?`)
    .bind(...binds, limit * 2).all<{id: string; mime: string; exif_stripped: number; credit: string | null; width: number | null; height: number | null}>()).results;
  const out: PublicPhoto[] = [];
  for (const row of rows) {
    if (out.length >= limit) break;
    let ok = row.mime === 'image/jpeg' && row.exif_stripped === 1;
    if (!ok && env.ADVISOR_MEDIA) { try { ok = Boolean(await env.ADVISOR_MEDIA.head(derivedKey(row.id))); } catch { ok = false; } }
    if (ok) out.push({id: row.id, url: `/media/${row.id}.jpg`, credit: row.credit, width: row.width, height: row.height});
  }
  return out;
}

export interface ReportRow {
  id: string; report_date: string; trip_type: string | null; anglers: number | null; counts_json: string; verified: number; version: number;
  boat_name?: string; boat_slug?: string; boat_status?: string;
}

/** A trip type in the page language; free-text trips are shown as written. */
const tripWords = (trip: string | null, copy: PageCopy): string => trip ? (copy.trips[trip] ?? trip) : '';

/**
 * The reports table: date, (boat), trip, anglers, catch, newest first. With
 * `boats`, a report frozen as verified whose boat is still verified links to
 * the boat page; any other is "Another boat" (08: unverified boats are not named).
 */
export function reportsTable(rows: readonly ReportRow[], language: PageLanguage, {boats, label}: {boats: boolean; label: string}): Html {
  const copy = copyFor(language);
  // The wrapper scrolls sideways on a phone, so it takes keyboard focus and a name.
  return html`<div class="adv-table-wrap" tabindex="0" role="group" aria-label="${label}"><table class="adv-table">
<thead><tr><th scope="col">${copy.date}</th>${boats ? html`<th scope="col">${copy.boat}</th>` : ''}<th scope="col">${copy.trip}</th><th scope="col">${copy.anglers}</th><th scope="col">${copy.catch}</th></tr></thead>
<tbody>${rows.map(r => {
    const named = r.verified === 1 && r.boat_status === 'verified' && r.boat_slug;
    const boat = boats ? html`<td>${named ? html`<a href="/boats/${r.boat_slug}${language === 'es' ? '?lang=es' : ''}">${r.boat_name}</a>` : html`<span class="adv-muted">${copy.anotherBoat}</span>`}</td>` : '';
    return html`<tr><td>${shortDate(r.report_date, language)}${r.version > 1 ? html` <span class="adv-tag">${copy.edited}</span>` : ''}</td>${boat}<td>${tripWords(r.trip_type, copy)}</td><td>${r.anglers ?? ''}</td><td>${countsText(countLines(r.counts_json), copy)}</td></tr>`;
  })}</tbody>
</table></div>`;
}

/** The HTML not-found page (an unknown port, species or boat). */
export function notFoundPage(language: PageLanguage, settings: SiteSettings, path: string): string {
  const copy = copyFor(language);
  return layout({language, kind: 'missing', path, title: `${copy.notFoundTitle} · SkipperCast`, description: copy.notFoundBody, crumbs: [{name: copy.notFoundTitle, path: null}],
    noindex: true, body: html`<h1>${copy.notFoundTitle}</h1>\n<p>${copy.notFoundBody}</p>\n<p><a class="adv-button" href="/">${copy.openMap}</a></p>`}, settings);
}
