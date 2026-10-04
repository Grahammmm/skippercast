// GET /ports/<port-id> (docs/plans/text-advisor/08-website.md § Public pages;
// WH-4, TA-W1): the port and its region, today's daily answer (the stored one
// when its inputs are current, else the same deterministic composition the
// advisor would send; a page view never calls the model), published skipper
// reports from the last 14 days (verified boats linked, others "Another
// boat"), today's fishing-window conditions and advisories from the same
// inputs, the port's verified boats, and the species of its coastal-directory
// region with today's season state from the rules table.
import ports from '../../../catalog/home-ports.json' with {type: 'json'};
import coasts from '../../../catalog/coasts.json' with {type: 'json'};
import speciesPages from '../../../catalog/advisor/species-pages.json' with {type: 'json'};
import {dailyInputs, hashInputs, composeDaily, seasonOpen} from '../answers/reports.ts';
import type {DailyInputs} from '../answers/reports.ts';
import {targetSpecies} from '../answers/confidence.ts';
import {regionConfig} from '../answers/regions.ts';
import {lookupRules} from '../answers/rules.ts';
import {addDays, localDate} from '../answers/time.ts';
import {portName, portRegion, resolveLinks, PORT_IDS} from '../links.ts';
import {html, layout, copyFor} from './render.ts';
import type {Html, SiteSettings} from './render.ts';
import {publicPhotos, reportsTable} from './data.ts';
import type {PageDeps, ReportRow} from './data.ts';
import type {PageLanguage, RuleState} from '../../../web/advisor/copy.ts';
import type {Env} from '../../env.ts';

export const PORT_REPORT_DAYS = 14;
export const PORT_MAX_AGE = 300;          // 08: edge 5 min
const PAGES = speciesPages.species as Record<string, {names: {en: string; es: string}}>;
const COASTS = coasts.regions as {id: string; name: string; packages: string[]; targets: string[]}[];

/** The ports a page exists for: catalog ports whose region manifest is built (draft regions are not). */
export const portExists = (id: string): boolean => PORT_IDS.has(id) && Boolean(regionConfig(portRegion(id)));
/** Ports of active regions (the sitemap's list). */
export const activePortIds = (): string[] => ports.ports.filter(p => regionConfig(p.region)?.status === 'active').map(p => p.id);

/** The coastal-directory targets for a region (catalog/coasts.json), else the region's own species list. */
export function regionTargets(regionId: string): string[] {
  return COASTS.find(c => c.packages.includes(regionId))?.targets ?? regionConfig(regionId)?.species ?? [];
}
/** The species-page keys a region's targets cover, in target order ('reef' is lingcod and rockfish). */
export function portSpeciesKeys(regionId: string): string[] {
  const out: string[] = [];
  for (const target of regionTargets(regionId)) for (const key of targetSpecies(target)) if (PAGES[key] && !out.includes(key)) out.push(key);
  return out;
}

/** Today's season state for one species in a region: stale rows are "under review", no row "check the rules". */
export async function ruleState(db: D1Database, region: string, key: string, date: string, now: number): Promise<RuleState> {
  const rows = await lookupRules(db, {region, speciesKey: key, now});
  const row = rows.find(r => r.applies_as === 'species') ?? rows[0];
  if (!row) return 'unknown';
  if (row.stale) return 'review';
  const open = seasonOpen(row, date);
  return open === false ? 'closed' : 'open';
}

/** The daily answer's text without the link back to this page (the page is that link). */
export function withoutSelfLink(text: string, url: string): string {
  const at = text.lastIndexOf(url);
  if (at < 0) return text.trim();
  const before = text.slice(0, at), after = text.slice(at + url.length);
  if (!after.trim()) {
    // The link closes the text: drop it and its lead-in ("Full picture:") back to the last sentence end.
    const end = Math.max(before.lastIndexOf('. '), before.lastIndexOf('! '), before.lastIndexOf('? '));
    const lead = before.slice(end + 1);
    return (/:\s*$/.test(lead) ? before.slice(0, end + 1) : before).trim();
  }
  return (before + after).replace(/\s{2,}/g, ' ').trim();
}

interface Daily {text: string}
async function todaysAnswer(env: Env, inputs: DailyInputs, language: PageLanguage, base: string): Promise<Daily> {
  const hash = await hashInputs(inputs);
  const row = await env.DB!.prepare('SELECT text_en,text_es,inputs_hash FROM advisor_daily_answers WHERE key=?').bind(`${inputs.port}:${inputs.date}`)
    .first<{text_en: string; text_es: string; inputs_hash: string}>();
  const self = `${base}/ports/${inputs.port}?s=txt`;
  // The stored answer while it is current (or while a feed is down, as dailyAnswer does); else the composition.
  if (row && (row.inputs_hash === hash || !inputs.feeds.daily || !inputs.feeds.intelligence)) return {text: withoutSelfLink(language === 'es' ? row.text_es : row.text_en, self)};
  return {text: withoutSelfLink(resolveLinks(composeDaily(inputs, language), base).text, self)};
}

const range = (r: [number, number] | null | undefined): string | null => r ? (r[0] === r[1] ? String(r[0]) : `${r[0]}-${r[1]}`) : null;

function conditionsSection(inputs: DailyInputs, language: PageLanguage): Html {
  const copy = copyFor(language), d = inputs.conditions.day;
  const seas = range(d?.seas_ft), wind = range(d?.wind_kt), comfort = d?.comfort ? copy.comfort[d.comfort] : undefined;
  const rows: [string, string][] = [];
  if (seas) rows.push([copy.seas, copy.seasValue(seas, d?.sea_period_s ?? null)]);
  if (wind) rows.push([copy.wind, copy.windValue(wind, d?.wind_from ?? null)]);
  if (comfort) rows.push([copy.ride, copy.rideValue(comfort)]);
  return html`<section class="adv-card" aria-labelledby="conditions-title">
<h2 id="conditions-title">${copy.conditionsHeading}</h2>
${inputs.conditions.advisories.length ? html`<div class="adv-advisories" role="note"><h3>${copy.advisoriesHeading}</h3><ul>${inputs.conditions.advisories.map(a => html`<li>${a}</li>`)}</ul></div>` : ''}
${rows.length ? html`<dl class="adv-facts">${rows.map(([k, v]) => html`<div><dt>${k}</dt><dd>${v}</dd></div>`)}</dl>` : html`<p>${copy.conditionsNone}</p>`}
<p class="adv-note">${copy.forecastNote}</p>
</section>`;
}

/** The page, or null for an unknown port. */
export async function portPage(env: Env, id: string, language: PageLanguage, settings: SiteSettings, deps: PageDeps = {}): Promise<string | null> {
  if (!portExists(id)) return null;
  const db = env.DB!, copy = copyFor(language), now = (deps.clock ?? Date.now)();
  const regionId = portRegion(id)!, region = regionConfig(regionId)!;
  const date = localDate(now, region.timezone), name = portName(id) ?? id;
  const inputs = await dailyInputs(env, id, date, deps, now);
  const [today, reports, boats, photo] = await Promise.all([
    todaysAnswer(env, inputs, language, settings.publicBase),
    db.prepare(`SELECT r.id,r.report_date,r.trip_type,r.anglers,r.counts_json,r.verified,r.version,b.name AS boat_name,b.slug AS boat_slug,b.status AS boat_status
        FROM advisor_reports r JOIN advisor_boats b ON b.id=r.boat_id WHERE r.port=? AND r.status='published' AND r.report_date>=? AND r.report_date<=?
        ORDER BY r.report_date DESC, r.published_at DESC, r.id LIMIT 60`).bind(id, addDays(date, -(PORT_REPORT_DAYS - 1)), date).all<ReportRow>().then(r => r.results),
    db.prepare("SELECT name,slug,landing FROM advisor_boats WHERE port=? AND status='verified' ORDER BY name LIMIT 60").bind(id)
      .all<{name: string; slug: string; landing: string | null}>().then(r => r.results),
    publicPhotos(env, "b.port=? AND b.status='verified'", [id], 1),
  ]);
  const keys = portSpeciesKeys(regionId);
  const states = await Promise.all(keys.map(key => ruleState(db, regionId, key, date, now)));
  const lang = language === 'es' ? '?lang=es' : '';
  const regionName = (region as {name?: string}).name ?? regionId;
  const anonymous = reports.some(r => !(r.verified === 1 && r.boat_status === 'verified'));

  const body = html`<header class="adv-title">
<h1>${copy.portTitle(name)}</h1>
<p class="adv-sub">${copy.portRegion(regionName)}</p>
</header>
<section class="adv-card adv-today" aria-labelledby="today-title">
<h2 id="today-title">${copy.todayHeading}</h2>
<p>${today.text}</p>
</section>
<section class="adv-card" aria-labelledby="reports-title">
<h2 id="reports-title">${copy.reportsHeading}</h2>
${reports.length ? reportsTable(reports, language, {boats: true, label: copy.reportsHeading}) : html`<p>${copy.reportsNone}</p>`}
${anonymous ? html`<p class="adv-note">${copy.reportsUnverifiedNote}</p>` : ''}
</section>
${conditionsSection(inputs, language)}
<section class="adv-card" aria-labelledby="boats-title">
<h2 id="boats-title">${copy.boatsHeading(name)}</h2>
${boats.length ? html`<ul class="adv-list">${boats.map(b => html`<li><a href="/boats/${b.slug}${lang}">${b.name}</a>${b.landing ? html` <span class="adv-muted">${b.landing}</span>` : ''}</li>`)}</ul>` : html`<p>${copy.boatsNone}</p>`}
</section>
<section class="adv-card" aria-labelledby="seasons-title">
<h2 id="seasons-title">${copy.seasonsHeading}</h2>
<ul class="adv-seasons">${keys.map((key, i) => html`<li><a href="/species/${key}${lang}#rules">${PAGES[key]!.names[language]}</a> <span class="adv-state adv-state-${states[i]!}">${copy.ruleState[states[i]!]}</span></li>`)}</ul>
<p class="adv-note">${copy.seasonsNote}</p>
</section>`;
  return layout({language, kind: 'port', path: `/ports/${id}`, title: `${copy.portTitle(name)} · SkipperCast`, description: copy.portDescription(name),
    image: photo[0]?.url ?? null, crumbs: [{name: copy.ports, path: null}, {name, path: `/ports/${id}`}], region: regionId,
    ctaMessage: copy.portCtaMessage(name), body}, settings);
}
