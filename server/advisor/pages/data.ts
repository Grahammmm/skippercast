// Shared reads for the public pages (TA-W1; 08 § Public pages): the pages
// version that keys the edge cache (05 § boat page), the public photos of a
// boat or port, the report table and the not-found page.
import {PAGES_VERSION_KEY} from '../intake/reports.ts';
import {derivedKey} from '../media.ts';
import {html, layout, countLines, countsText, shortDate, copyFor} from './render.ts';
import type {Html, SiteSettings} from './render.ts';
import type {PageCopy, PageLanguage} from '../../../web/advisor/copy.ts';
import type {Env} from '../../env.ts';
import {publicVesselSql, displayableFact, displayableLink, factValue, withinGoogleWindow} from '../../fleet/display.ts';
import type {FactRow} from '../../fleet/display.ts';
import {safeTarget} from '../../fleet/go.ts';

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

/** The HTML not-found page (an unknown port, species or boat); `advisor` false drops the advisor's call to action (CF-33). */
export function notFoundPage(language: PageLanguage, settings: SiteSettings, path: string, advisor = true): string {
  const copy = copyFor(language);
  return layout({language, kind: 'missing', path, title: `${copy.notFoundTitle} · SkipperCast`, description: copy.notFoundBody, crumbs: [{name: copy.notFoundTitle, path: null}],
    noindex: true, body: html`<h1>${copy.notFoundTitle}</h1>\n<p>${copy.notFoundBody}</p>\n<p><a class="adv-button" href="/">${copy.openMap}</a></p>`, advisor}, settings);
}

// ---- CF-33: the charter fleet registry on /boats/<slug> (charter-fleet design § 13) ----------
// Everything below reads only what server/fleet/display.ts allows in public: a vessel
// that is active, listed and never asked for removal; facts with display-compatible
// rights, confidence ≥ 0.6, current, never AIS. No AIS table is read here.

export interface FleetVesselRow {
  id: string; region: string; slug: string; name: string; operator_id: string | null; port_id: string | null;
  vessel_class: string | null; year_built: number | null; passengers_max: number | null; length_ft: number | null;
  website: string | null; booking_url: string | null; phone_business: string | null; updated_at: string;
}
const VESSEL_COLUMNS = 'id,region,slug,name,operator_id,port_id,vessel_class,year_built,passengers_max,length_ft,website,booking_url,phone_business,updated_at';

/** A public fleet vessel by slug or id, else null (hidden, excluded, inactive, sold or removal requested). */
export async function publicFleetVessel(db: D1Database, by: 'slug' | 'id', key: string): Promise<FleetVesselRow | null> {
  return db.prepare(`SELECT ${VESSEL_COLUMNS} FROM fleet_vessels WHERE ${by === 'slug' ? 'slug' : 'id'}=? AND ${publicVesselSql()}`).bind(key).first<FleetVesselRow>();
}

export interface FleetOffering {name: string; tripType: string; hours: number | null; departs: string | null; priceCents: number | null;
  basis: string | null; currency: string; listedHost: string; listedOn: string}
export interface FleetSource {host: string; date: string}
/** What the profile may show of a vessel; every value already passed the display rules. */
export interface FleetProfile {
  vessel: FleetVesselRow;
  vesselClass: string | null; landing: string | null; lengthFt: number | null; passengers: number | null; yearBuilt: number | null;
  booking: boolean; website: boolean; phone: string | null;
  offerings: FleetOffering[];
  photos: {url: string; credit: string}[];
  google: {rating: number; count: number | null; placeUrl: string} | null;
  sources: FleetSource[];
  /** The operator consented to content sharing (content-sharing or partner, not revoked): the page may be indexed. */
  consented: boolean;
}

const MAX_FACTS = 500, MAX_OFFERINGS = 20, MAX_PHOTOS = 6;
/** The Google Maps place URL the google-places adapter records as the rating fact's source_url (the attribution link). */
const GOOGLE_PLACE = /^https:\/\/(?:www\.google\.com\/maps|maps\.google\.com|maps\.app\.goo\.gl)\//;
const hostOf = (url: string): string | null => { try { const u = new URL(url); return u.protocol === 'https:' ? u.hostname.replace(/^www\./, '') : null; } catch { return null; } };
const sameValue = (a: unknown, b: unknown): boolean => typeof a === 'number' && typeof b === 'number' ? Math.abs(a - b) < 1e-9 : a === b;
const newestFirst = (a: FactRow, b: FactRow): number => a.retrieved_at < b.retrieved_at ? 1 : a.retrieved_at > b.retrieved_at ? -1 : 0;

/** The registry profile of a public vessel at `now` (ms). */
export async function fleetProfile(db: D1Database, vessel: FleetVesselRow, now: number): Promise<FleetProfile> {
  const today = new Date(now).toISOString().slice(0, 10);
  const [facts, offerings, operator] = await Promise.all([
    db.prepare(`SELECT id,field,value_json,source_url,method,confidence,rights,retrieved_at,superseded_at FROM fleet_vessel_facts
        WHERE vessel_id=? AND superseded_at IS NULL ORDER BY retrieved_at DESC, id LIMIT ${MAX_FACTS}`).bind(vessel.id).all<FactRow>().then(r => r.results.filter(displayableFact)),
    db.prepare(`SELECT name,trip_type,duration_h,price_cents,price_basis,currency,departs_local,source_fact_ids_json FROM fleet_offerings
        WHERE vessel_id=? AND status='active' AND (valid_to IS NULL OR valid_to>=?) AND (valid_from IS NULL OR valid_from<=?)
        ORDER BY price_cents IS NULL, price_cents, name LIMIT ${MAX_OFFERINGS}`).bind(vessel.id, today, today)
      .all<{name: string; trip_type: string; duration_h: number | null; price_cents: number | null; price_basis: string | null; currency: string;
        departs_local: string | null; source_fact_ids_json: string | null}>().then(r => r.results),
    vessel.operator_id ? db.prepare('SELECT consent_status,consent_revoked_at FROM fleet_operators WHERE id=?').bind(vessel.operator_id)
      .first<{consent_status: string; consent_revoked_at: string | null}>() : Promise.resolve(null),
  ]);
  const used = new Map<string, FactRow>();
  const use = (fact: FactRow | undefined): FactRow | undefined => { if (fact) used.set(fact.id, fact); return fact; };
  /** A resolved column, shown only when a displayable fact for `field` carries the same value. */
  const backed = <T>(field: string, value: T | null): T | null =>
    value !== null && use(facts.find(f => f.field === field && sameValue(factValue(f), value))) ? value : null;
  const best = (field: string): FactRow | undefined => facts.filter(f => f.field === field).sort((a, b) => b.confidence - a.confidence || newestFirst(a, b))[0];

  const vesselClass = backed('vessel_class', vessel.vessel_class), lengthFt = backed('length_ft', vessel.length_ft);
  const passengers = backed('passengers_max', vessel.passengers_max), yearBuilt = backed('year_built', vessel.year_built);
  const landingFact = best('landing'), landingValue = landingFact ? factValue(landingFact) : null;
  const landing = typeof landingValue === 'string' && landingValue.length > 0 && landingValue.length <= 80 ? (use(landingFact), landingValue) : null;
  const phone = vessel.phone_business && /^\+1[2-9]\d{9}$/.test(vessel.phone_business) ? backed('phone_business', vessel.phone_business) : null;
  const booking = displayableLink(vessel.booking_url, 'booking_url', facts), website = displayableLink(vessel.website, 'website', facts);
  if (booking) use(facts.find(f => f.field === 'booking_url' && factValue(f) === vessel.booking_url));
  if (website) use(facts.find(f => f.field === 'website' && factValue(f) === vessel.website));

  const byId = new Map(facts.map(f => [f.id, f]));
  const listed: FleetOffering[] = [];
  for (const o of offerings) {
    let ids: unknown; try { ids = JSON.parse(o.source_fact_ids_json ?? '[]'); } catch { ids = []; }
    // An offering shows only with a displayable source fact; the newest one names the host and the date.
    const source = (Array.isArray(ids) ? ids : []).map(id => byId.get(String(id))).filter((f): f is FactRow => Boolean(f && hostOf(f.source_url))).sort(newestFirst)[0];
    if (!source) continue;
    use(source);
    listed.push({name: o.name, tripType: o.trip_type, hours: o.duration_h, departs: o.departs_local, priceCents: o.price_cents, basis: o.price_basis,
      currency: o.currency, listedHost: hostOf(source.source_url)!, listedOn: source.retrieved_at.slice(0, 10)});
  }

  // Photos are links with their credit, never embedded: field `photos[]`, value {url, attribution}.
  const photos: {url: string; credit: string}[] = [];
  for (const f of facts) {
    if (f.field !== 'photos[]' || photos.length >= MAX_PHOTOS) continue;
    const v = factValue(f) as {url?: unknown; attribution?: unknown} | null | undefined;
    const url = v && typeof v === 'object' ? safeTarget(v.url) : null;
    const credit = v && typeof v === 'object' && typeof v.attribution === 'string' ? v.attribution.trim() : '';
    if (!url || !credit || credit.length > 120 || photos.some(p => p.url === url.href)) continue;
    use(f); photos.push({url: url.href, credit});
  }

  // Google: numbers only (never review text), only inside the 30-day window, only with the link to the place.
  let google: FleetProfile['google'] = null;
  const ratingFact = best('reputation.google_rating'), rating = ratingFact ? factValue(ratingFact) : null;
  if (ratingFact && typeof rating === 'number' && rating >= 1 && rating <= 5 && GOOGLE_PLACE.test(ratingFact.source_url) && withinGoogleWindow(ratingFact.retrieved_at, now)) {
    const countFact = best('reputation.google_reviews'), count = countFact ? factValue(countFact) : null;
    const countOk = Boolean(countFact && typeof count === 'number' && Number.isInteger(count) && count >= 0 && withinGoogleWindow(countFact.retrieved_at, now));
    use(ratingFact); if (countOk) use(countFact);
    google = {rating, count: countOk ? count as number : null, placeUrl: ratingFact.source_url};
  }

  const sources = new Map<string, string>();
  for (const f of used.values()) {
    const host = hostOf(f.source_url), date = f.retrieved_at.slice(0, 10);
    if (host && (!sources.has(host) || sources.get(host)! < date)) sources.set(host, date);
  }
  return {
    vessel, vesselClass, landing, lengthFt, passengers, yearBuilt,
    booking: Boolean(booking), website: Boolean(website), phone,
    offerings: listed, photos, google,
    sources: [...sources].map(([host, date]) => ({host, date})).sort((a, b) => a.host.localeCompare(b.host)),
    consented: Boolean(operator && ['content-sharing', 'partner'].includes(operator.consent_status) && !operator.consent_revoked_at),
  };
}
