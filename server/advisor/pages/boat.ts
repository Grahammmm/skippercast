// GET /boats/<slug> (docs/plans/text-advisor/05-skipper-intake.md § The boat
// page, 08 § Public pages; SK-5, TA-W1): name, landing, port, the verified
// badge (a pending boat renders only its name, port, "Not verified yet" and the
// note, and is kept out of search and the sitemap; a rejected boat has no page), the last 30 days of published
// reports with an "edited" marker when version > 1, the last 12 approved or
// posted photos through /media/<id>.jpg with their credit, the booking link or
// phone, the Instagram link and the call to action.
import {addDays, localDate} from '../answers/time.ts';
import {regionConfig} from '../answers/regions.ts';
import {portName} from '../links.ts';
import {html, layout, copyFor} from './render.ts';
import type {SiteSettings} from './render.ts';
import {publicPhotos, reportsTable} from './data.ts';
import type {PageDeps, ReportRow} from './data.ts';
import type {PageLanguage} from '../../../web/advisor/copy.ts';
import type {Env} from '../../env.ts';

export const BOAT_REPORT_DAYS = 30;
export const BOAT_PHOTOS = 12;
export const BOAT_MAX_AGE = 300;          // 05: edge 5 min
export const BOAT_SLUG = /^[a-z0-9](?:[a-z0-9-]{0,38}[a-z0-9])?$/;   // 02 § advisor_boats.slug

interface BoatRow {id: string; slug: string; name: string; landing: string | null; port: string; region: string; instagram: string | null;
  booking_url: string | null; phone_public: string | null; status: string}

/** "(805) 555-0123" for a US E.164 number; others as stored. */
export const phoneText = (e164: string): string => { const m = /^\+1(\d{3})(\d{3})(\d{4})$/.exec(e164); return m ? `(${m[1]}) ${m[2]}-${m[3]}` : e164; };
const httpsUrl = (value: string | null): string | null => {
  if (!value) return null;
  try { const url = new URL(value); return url.protocol === 'https:' && !url.username && !url.password ? url.toString() : null; } catch { return null; }
};

/** The page, or null for an unknown slug or a rejected boat. */
export async function boatPage(env: Env, slug: string, language: PageLanguage, settings: SiteSettings, deps: PageDeps = {}): Promise<string | null> {
  if (!BOAT_SLUG.test(slug)) return null;
  const db = env.DB!, copy = copyFor(language), now = (deps.clock ?? Date.now)();
  const boat = await db.prepare("SELECT id,slug,name,landing,port,region,instagram,booking_url,phone_public,status FROM advisor_boats WHERE slug=? AND status IN ('verified','pending')")
    .bind(slug).first<BoatRow>();
  if (!boat) return null;
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
  return layout({language, kind: 'boat', path: `/boats/${boat.slug}`, title: `${copy.boatTitle(boat.name)} · SkipperCast`, description: copy.boatDescription(boat.name, port),
    image: photos[0]?.url ?? null, crumbs: [{name: copy.boats, path: null}, {name: boat.name, path: `/boats/${boat.slug}`}], region: boat.region,
    noindex: false, body}, settings);
}
