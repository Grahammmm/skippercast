// GET /boats/<slug> (docs/plans/text-advisor/05-skipper-intake.md § The boat
// page, 08 § Public pages; SK-5, TA-W1): name, landing, port, the verified
// badge (a pending boat renders only its name, port, "Not verified yet" and the
// note, and is kept out of search and the sitemap; a rejected boat has no page), the last 30 days of published
// reports with an "edited" marker when version > 1, the last 12 approved or
// posted photos through /media/<id>.jpg with their credit, the booking link or
// phone, the Instagram link and the call to action.
//
// CF-33 (docs/plans/charter-fleet/design.md § 13): with FLEET_ENABLED on, a public
// registry vessel (active, listed, no removal request) gets a profile at its own slug,
// and a verified advisor boat linked to one (advisor_boats.fleet_vessel_id) gains the
// registry cards. Only displayable facts render (server/fleet/display.ts): no AIS data,
// no `noaa-planning-only` or `internal-only` fact, nothing under 0.6 confidence; the
// Google rating and count only inside their 30-day window, with the Google link; links
// out go through /go/. A registry-only page is noindex until its operator consents.
// With FLEET_ENABLED off an advisor boat's page is byte-identical to before.
import {addDays, localDate} from '../answers/time.ts';
import {regionConfig} from '../answers/regions.ts';
import {portName} from '../links.ts';
import {html, raw, layout, copyFor, longDate} from './render.ts';
import type {Html, SiteSettings} from './render.ts';
import {publicPhotos, reportsTable, publicFleetVessel, fleetProfile} from './data.ts';
import type {FleetProfile, PageDeps, ReportRow} from './data.ts';
import {advisorSettings} from '../settings.ts';
import {fleetSettings} from '../../fleet/settings.ts';
import {FLEET_SLUG} from '../../fleet/display.ts';
import type {PageLanguage} from '../../../web/advisor/copy.ts';
import type {Env} from '../../env.ts';

export const BOAT_REPORT_DAYS = 30;
export const BOAT_PHOTOS = 12;
export const BOAT_MAX_AGE = 300;          // 05: edge 5 min
export const BOAT_SLUG = /^[a-z0-9](?:[a-z0-9-]{0,38}[a-z0-9])?$/;   // 02 § advisor_boats.slug

interface BoatRow {id: string; slug: string; name: string; landing: string | null; port: string; region: string; instagram: string | null;
  booking_url: string | null; phone_public: string | null; status: string; fleet_vessel_id: string | null}

/** "(805) 555-0123" for a US E.164 number; others as stored. */
export const phoneText = (e164: string): string => { const m = /^\+1(\d{3})(\d{3})(\d{4})$/.exec(e164); return m ? `(${m[1]}) ${m[2]}-${m[3]}` : e164; };
const httpsUrl = (value: string | null): string | null => {
  if (!value) return null;
  try { const url = new URL(value); return url.protocol === 'https:' && !url.username && !url.password ? url.toString() : null; } catch { return null; }
};

/**
 * The page, or null for an unknown slug or a rejected boat. The route's gate passes when
 * either flag is on (CF-33): advisor boats are looked up only while the Text Advisor is on,
 * registry vessels (and a linked advisor boat's registry section) only while FLEET_ENABLED is.
 */
export async function boatPage(env: Env, slug: string, language: PageLanguage, settings: SiteSettings, deps: PageDeps = {}): Promise<string | null> {
  const advisorOn = advisorSettings(env).enabled, fleetOn = fleetSettings(env).enabled;
  if (!BOAT_SLUG.test(slug) && !(fleetOn && FLEET_SLUG.test(slug))) return null;
  const db = env.DB!, copy = copyFor(language), now = (deps.clock ?? Date.now)();
  const boat = advisorOn && BOAT_SLUG.test(slug)
    ? await db.prepare("SELECT id,slug,name,landing,port,region,instagram,booking_url,phone_public,status,fleet_vessel_id FROM advisor_boats WHERE slug=? AND status IN ('verified','pending')")
      .bind(slug).first<BoatRow>()
    : null;
  if (!boat) return fleetOn ? registryPage(db, slug, language, settings, now, advisorOn) : null;
  const verified = boat.status === 'verified';
  const port = portName(boat.port) ?? boat.port, lang = language === 'es' ? '?lang=es' : '';
  // Hardening (threat model § 9.6): a pending boat's details are self-entered and unreviewed, so its page shows only
  // the name, the port, the badge and the note: no landing, reports, photos, booking link, phone or Instagram until
  // the team verifies it (anyone who texts the number could otherwise host a link under skippercast.com/boats/).
  if (!verified) {
    const body = html`<header class="adv-title">
<h1>${boat.name}</h1>
<p class="adv-sub"><a href="/ports/${boat.port}${lang}">${copy.portTitle(port)}</a></p>
<p><span class="adv-badge adv-badge-pending">${copy.unverified}</span></p>
<p class="adv-note">${copy.unverifiedNote}</p>
</header>`;
    return layout({language, kind: 'boat', path: `/boats/${boat.slug}`, title: `${copy.boatTitle(boat.name)} · SkipperCast`, description: copy.boatDescription(boat.name, port),
      image: null, crumbs: [{name: copy.boats, path: null}, {name: boat.name, path: `/boats/${boat.slug}`}], region: boat.region, noindex: true, body}, settings);
  }
  const today = localDate(now, regionConfig(boat.region)?.timezone ?? 'America/Los_Angeles');
  const [reports, photos] = await Promise.all([
    db.prepare(`SELECT id,report_date,trip_type,anglers,counts_json,verified,version FROM advisor_reports WHERE boat_id=? AND status='published' AND report_date>=? AND report_date<=?
        ORDER BY report_date DESC, published_at DESC, id LIMIT 60`).bind(boat.id, addDays(today, -(BOAT_REPORT_DAYS - 1)), today).all<ReportRow>().then(r => r.results),
    publicPhotos(env, 'm.boat_id=?', [boat.id], BOAT_PHOTOS),
  ]);
  const booking = httpsUrl(boat.booking_url), phone = boat.phone_public && /^\+\d{8,15}$/.test(boat.phone_public) ? boat.phone_public : null;
  const instagram = boat.instagram && /^[a-z0-9._]{1,30}$/.test(boat.instagram) ? boat.instagram : null;

  const body = html`<header class="adv-title">
<h1>${boat.name}</h1>
<p class="adv-sub">${boat.landing ? copy.landing(boat.landing, port) : port} · <a href="/ports/${boat.port}${lang}">${copy.portTitle(port)}</a></p>
<p><span class="adv-badge adv-badge-verified">${copy.verified}</span></p>
</header>
<section class="adv-card" aria-labelledby="reports-title">
<h2 id="reports-title">${copy.boatReportsHeading}</h2>
${reports.length ? reportsTable(reports, language, {boats: false, label: copy.boatReportsHeading}) : html`<p>${copy.boatReportsNone}</p>`}
</section>
${photos.length ? html`<section class="adv-card" aria-labelledby="photos-title">
<h2 id="photos-title">${copy.photosHeading}</h2>
<ul class="adv-photos">${photos.map(p => html`<li><figure><img src="${p.url}" alt="${copy.photoAlt(boat.name)}" loading="lazy"${p.width && p.height ? html` width="${p.width}" height="${p.height}"` : ''}><figcaption>${copy.photoCredit(p.credit || boat.name)}</figcaption></figure></li>`)}</ul>
</section>` : ''}
${booking || phone || instagram ? html`<section class="adv-card" aria-labelledby="book-title">
<h2 id="book-title">${copy.bookHeading}</h2>
<ul class="adv-list">
${booking ? html`<li><a href="${booking}" rel="noopener nofollow">${copy.bookingLink}</a></li>` : ''}
${phone ? html`<li><a href="tel:${phone}">${copy.call(phoneText(phone))}</a></li>` : ''}
${instagram ? html`<li><a href="https://www.instagram.com/${instagram}/" rel="noopener nofollow">${copy.instagram(instagram)}</a></li>` : ''}
</ul>
</section>` : ''}`;
  // CF-33: a verified boat the team linked to a registry vessel (advisor_boats.fleet_vessel_id) gains the
  // registry section after its own, only while FLEET_ENABLED is on and the vessel is public.
  const vessel = fleetOn && boat.fleet_vessel_id ? await publicFleetVessel(db, 'id', boat.fleet_vessel_id) : null;
  const registry = vessel ? fleetSections(await fleetProfile(db, vessel, now), language) : null;
  return layout({language, kind: 'boat', path: `/boats/${boat.slug}`, title: `${copy.boatTitle(boat.name)} · SkipperCast`, description: copy.boatDescription(boat.name, port),
    image: photos[0]?.url ?? null, crumbs: [{name: copy.boats, path: null}, {name: boat.name, path: `/boats/${boat.slug}`}], region: boat.region,
    noindex: false, body: registry ? html`${body}\n${registry}` : body}, settings);
}

// ---- CF-33: the charter fleet registry profile (charter-fleet design § 13) ----------------

/** A registry-only page: a public fleet vessel by slug, else null. noindex until its operator consents. */
async function registryPage(db: D1Database, slug: string, language: PageLanguage, settings: SiteSettings, now: number, advisorOn: boolean): Promise<string | null> {
  const vessel = await publicFleetVessel(db, 'slug', slug);
  if (!vessel) return null;
  const copy = copyFor(language), profile = await fleetProfile(db, vessel, now);
  const port = portName(vessel.port_id), lang = language === 'es' ? '?lang=es' : '';
  // A vessel the team linked to a verified advisor boat has that boat's page as its main page: this one stays out of search.
  const linked = advisorOn ? await db.prepare("SELECT 1 AS linked FROM advisor_boats WHERE fleet_vessel_id=? AND status='verified' LIMIT 1").bind(vessel.id).first() : null;
  const where = profile.landing && port ? copy.landing(profile.landing, port) : profile.landing ?? port;
  const body = html`<header class="adv-title">
<h1>${vessel.name}</h1>
${where ? html`<p class="adv-sub">${where}${port && advisorOn ? html` · <a href="/ports/${vessel.port_id}${lang}">${copy.portTitle(port)}</a>` : ''}</p>` : ''}
</header>
${fleetSections(profile, language)}`;
  return layout({language, kind: 'boat', path: `/boats/${vessel.slug}`, title: `${copy.fleetTitle(vessel.name)} · SkipperCast`,
    description: copy.fleetDescription(vessel.name, port ?? vessel.region), image: null,
    crumbs: [{name: copy.boats, path: null}, {name: vessel.name, path: `/boats/${vessel.slug}`}], region: vessel.region,
    noindex: !profile.consented || Boolean(linked), advisor: advisorOn, body}, settings);
}

const decimal = (n: number): string => String(Math.round(n * 10) / 10);
function price(cents: number, currency: string, language: PageLanguage): string {
  try {
    return new Intl.NumberFormat(language === 'es' ? 'es-MX' : 'en-US', {style: 'currency', currency, minimumFractionDigits: cents % 100 ? 2 : 0}).format(cents / 100);
  } catch { return `${(cents / 100).toFixed(2)} ${currency}`; }
}

/**
 * The registry cards: about (class, size, year, Google rating), trips with prices as
 * listed, booking and website links through /go/, the business phone, photo links with
 * their credit and the dated sources. The landing is in the page header. Links to
 * /go/ use the fleet vessel's slug (the one /go/ looks up), never the advisor boat's.
 */
export function fleetSections(p: FleetProfile, language: PageLanguage): Html {
  const copy = copyFor(language), slug = p.vessel.slug;
  const go = (t: 'booking' | 'website'): string => `/go/${slug}?t=${t}&p=profile`;
  const facts = [
    p.vesselClass ? copy.vesselClasses[p.vesselClass] ?? null : null,
    p.lengthFt !== null ? copy.lengthFt(decimal(p.lengthFt)) : null,
    p.passengers !== null ? copy.passengersMax(p.passengers) : null,
    p.yearBuilt !== null ? copy.builtIn(p.yearBuilt) : null,
  ].filter((v): v is string => Boolean(v));
  const google = p.google ? html`<li><a href="${p.google.placeUrl}" rel="noopener nofollow">Google</a>: ${copy.googleRating(p.google.rating.toFixed(1))}${p.google.count !== null ? ` · ${copy.googleReviews(p.google.count)}` : ''}</li>` : '';
  const out: Html[] = [];
  if (facts.length || google) out.push(html`<section class="adv-card" aria-labelledby="fleet-about-title">
<h2 id="fleet-about-title">${copy.fleetAboutHeading}</h2>
<ul class="adv-list">${facts.map(f => html`<li>${f}</li>`)}${google}</ul>
</section>`);
  if (p.offerings.length) out.push(html`<section class="adv-card" aria-labelledby="fleet-trips-title">
<h2 id="fleet-trips-title">${copy.fleetTripsHeading}</h2>
<ul class="adv-list">${p.offerings.map(o => {
    const parts = [copy.fleetTrips[o.tripType] ?? o.tripType, o.hours !== null ? copy.hours(decimal(o.hours)) : null, o.departs ? copy.departs(o.departs) : null].filter(Boolean).join(' · ');
    const listed = o.priceCents !== null ? copy.priceListed(price(o.priceCents, o.currency, language), o.basis, o.listedHost, longDate(o.listedOn, language)) : copy.listedOn(o.listedHost, longDate(o.listedOn, language));
    return html`<li><strong>${o.name}</strong> · ${parts}<br>${listed}</li>`;
  })}</ul>
</section>`);
  if (p.booking || p.website || p.phone) out.push(html`<section class="adv-card" aria-labelledby="fleet-book-title">
<h2 id="fleet-book-title">${copy.bookHeading}</h2>
<ul class="adv-list">
${p.booking ? html`<li><a href="${go('booking')}" rel="nofollow">${copy.bookingLink}</a></li>` : ''}
${p.website ? html`<li><a href="${go('website')}" rel="nofollow">${copy.websiteLink}</a></li>` : ''}
${p.phone ? html`<li><a href="tel:${p.phone}">${copy.call(phoneText(p.phone))}</a></li>` : ''}
</ul>
</section>`);
  if (p.photos.length) out.push(html`<section class="adv-card" aria-labelledby="fleet-photos-title">
<h2 id="fleet-photos-title">${copy.photoLinksHeading}</h2>
<ul class="adv-list">${p.photos.map(ph => html`<li><a href="${ph.url}" rel="noopener nofollow">${copy.photoCredit(ph.credit)}</a></li>`)}</ul>
</section>`);
  if (p.sources.length) out.push(html`<section class="adv-card" aria-labelledby="fleet-sources-title">
<h2 id="fleet-sources-title">${copy.sourcesHeading}</h2>
<p class="adv-note">${copy.fleetSourcesNote}</p>
<ul class="adv-list">${p.sources.map(s => html`<li>${copy.sourceChecked(s.host, longDate(s.date, language))}</li>`)}</ul>
</section>`);
  return raw(out.map(h => h.value).join('\n'));
}
