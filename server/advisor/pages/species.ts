// GET /species/<key> (docs/plans/text-advisor/08-website.md § Public pages;
// WH-4, TA-W1): the species' names in English and Spanish and its description
// (catalog/advisor/species-pages.json, TA-A3), its field marks and look-alikes
// (lookalikes.json), the rules card from advisor_rules at #rules with source and
// reviewed date (a stale row says "under review"; a species without its own row
// shows its parent group's, as get_rules does), recent catches of the species
// from verified boats by date and port, and the method summary get_strategy
// gives. Nothing here states a rule that is not in the rules table.
import speciesPages from '../../../catalog/advisor/species-pages.json' with {type: 'json'};
import lookalikes from '../../../catalog/advisor/lookalikes.json' with {type: 'json'};
import coasts from '../../../catalog/coasts.json' with {type: 'json'};
import {canonicalSpecies, speciesCues} from '../vision/species.ts';
import {exactSpecies} from '../answers/resolve.ts';
import {strategyFor} from '../answers/advice.ts';
import {ruleKeys, isStale} from '../answers/rules.ts';
import type {RuleRow} from '../answers/rules.ts';
import {jurisdictionFor, regionConfig} from '../answers/regions.ts';
import {addDays, localDate} from '../answers/time.ts';
import {portName} from '../links.ts';
import {html, layout, copyFor, shortDate, longDate, countLines} from './render.ts';
import type {Html, SiteSettings} from './render.ts';
import type {PageDeps} from './data.ts';
import type {PageCopy, PageLanguage} from '../../../web/advisor/copy.ts';
import type {Env} from '../../env.ts';

export const SPECIES_CATCH_DAYS = 14;
export const SPECIES_MAX_AGE = 900;       // 08: edge 15 min

interface SpeciesPage {names: {en: string; es: string}; parent: string | null; description: {en: string; es: string}; sources: string[]}
const PAGES = speciesPages.species as Record<string, SpeciesPage>;
interface Lookalike {lookalikes: string[]; source: string}
const LOOKALIKES = lookalikes.species as Record<string, Lookalike>;
const COASTS = coasts.regions as {id: string; name: string}[];

/** Every key a species page exists for (species-pages.json). */
export const SPECIES_PAGE_KEYS: readonly string[] = Object.keys(PAGES);
/** The page key for a path segment: a page key, or a synonym of one (california-halibut -> halibut); null otherwise. */
export function speciesPageKey(segment: string): string | null {
  const key = canonicalSpecies(String(segment ?? '').toLowerCase());
  return Object.hasOwn(PAGES, key) ? key : null;
}

/** The look-alike entry of a key, through its synonyms (halibut uses california-halibut's). */
function lookalikeEntry(key: string): Lookalike | null {
  if (LOOKALIKES[key]) return LOOKALIKES[key]!;
  for (const [k, v] of Object.entries(LOOKALIKES)) if (canonicalSpecies(k) === key) return v;
  return null;
}

/** Catalog wording that a public page never carries: no probability or hotspot language (copy rules, 08). */
export function pageSafe(text: string | null | undefined): string | null {
  if (!text) return null;
  const kept = String(text).split(/(?<=[.!?])\s+/).filter(s => !/%|\bpercent|\bhot ?spots?\b|\bprobab|\bodds\b|\bchance\b/i.test(s)).join(' ').trim();
  return kept || null;
}

// ---- the rules card ----------------------------------------------------------------------

/** "Apr 1" from MM-DD; "Apr 1, 2026" from YYYY-MM-DD. */
function seasonDate(value: string, language: PageLanguage): string {
  const iso = /^\d{4}-\d{2}-\d{2}$/.test(value), md = /^\d{2}-\d{2}$/.test(value);
  if (!iso && !md) return value;
  const d = new Date(`${iso ? value : `2001-${value}`}T12:00:00Z`);
  return new Intl.DateTimeFormat(language === 'es' ? 'es-MX' : 'en-US', {month: 'short', day: 'numeric', ...(iso ? {year: 'numeric'} : {}), timeZone: 'UTC'}).format(d);
}
function seasonText(row: RuleRow, copy: PageCopy, language: PageLanguage): string {
  if (row.season_open && row.season_close) return copy.seasonRange(seasonDate(row.season_open, language), seasonDate(row.season_close, language));
  if (row.bag_limit === 0) return copy.noTake;
  return copy.noSeasonDates;
}
const jurisdictionName = (id: string): string => { const coast = COASTS.find(c => `california-${c.id}` === id); return coast?.name ?? id; };

/** Active and review rows of every jurisdiction for the key (and its group), the default region's jurisdiction first, never retired. */
export async function speciesRules(db: D1Database, key: string, firstJurisdiction: string | null): Promise<{row: RuleRow; group: boolean}[]> {
  const {species, group} = ruleKeys(key), keys = [...species, ...group];
  const marks = keys.map(() => '?').join(',');
  const rows = (await db.prepare(`SELECT * FROM advisor_rules WHERE species_key IN (${marks}) AND status IN ('active','review')
      ORDER BY CASE WHEN jurisdiction=? THEN 0 ELSE 1 END, jurisdiction, CASE WHEN region='*' THEN 1 ELSE 0 END, region, species_key, species_label LIMIT 80`)
    .bind(...keys, firstJurisdiction ?? '').all<RuleRow>()).results;
  // A species with its own rows shows those; otherwise its group's (applies_as 'group', as get_rules).
  const own = rows.filter(r => species.includes(r.species_key));
  return (own.length ? own : rows).map(row => ({row, group: !species.includes(row.species_key)}));
}

function rulesCard(rules: {row: RuleRow; group: boolean}[], copy: PageCopy, language: PageLanguage, today: string): Html {
  const groups = new Map<string, {row: RuleRow; group: boolean}[]>();
  for (const r of rules) { const g = groups.get(r.row.jurisdiction) ?? []; g.push(r); groups.set(r.row.jurisdiction, g); }
  return html`<section class="adv-card" id="rules" aria-labelledby="rules-title">
<h2 id="rules-title">${copy.rulesHeading}</h2>
${rules.length ? [...groups].map(([jurisdiction, list]) => html`<h3>${copy.regionRule(jurisdictionName(jurisdiction))}</h3>
${list.map(({row, group}) => {
    const stale = isStale(row, today);
    const facts: [string, Html | string][] = [];
    if (row.size_min_in !== null) facts.push([copy.minSize, copy.inches(row.size_min_in)]);
    if (row.size_max_in !== null) facts.push([copy.maxSize, copy.inches(row.size_max_in)]);
    if (row.bag_limit !== null || row.bag_notes) facts.push([copy.bag, [row.bag_limit !== null ? copy.bagValue(row.bag_limit) : '', row.bag_notes ?? ''].filter(Boolean).join('. ')]);
    facts.push([copy.season, seasonText(row, copy, language)]);
    if (row.depth_limit_ft !== null) facts.push([copy.depth, copy.feetMax(row.depth_limit_ft)]);
    if (row.area_notes) facts.push([copy.area, row.area_notes]);
    if (row.gear_notes) facts.push([copy.gear, row.gear_notes]);
    facts.push([copy.source, html`<a href="${row.source_url}" rel="noopener">${row.source_name}</a>`]);
    facts.push([copy.reviewed, longDate(row.reviewed_at, language)]);
    const regionName = row.region !== '*' ? ((regionConfig(row.region) as {name?: string} | null)?.name ?? row.region) : null;
    return html`<article class="adv-rule${stale ? ' is-stale' : ''}">
<h4>${group ? copy.groupRule(row.species_label) : row.species_label}${regionName ? html` <span class="adv-muted">${regionName}</span>` : ''}${stale ? html` <span class="adv-state adv-state-review">${copy.underReview}</span>` : ''}</h4>
${stale ? html`<p class="adv-warn">${copy.underReviewNote}</p>` : ''}
<dl class="adv-facts">${facts.map(([k, v]) => html`<div><dt>${k}</dt><dd>${v}</dd></div>`)}</dl>
</article>`;
  })}`) : html`<p>${copy.rulesNone}</p>`}
</section>`;
}

// ---- recent catches ----------------------------------------------------------------------

export interface CatchDay {date: string; port: string; kept: number; released: number; boats: number}

/** Lines of published reports from verified boats in the window that are this species: its key, or a label that names it (vermilion under rockfish). */
export async function recentCatches(db: D1Database, key: string, from: string, to: string): Promise<CatchDay[]> {
  const rows = (await db.prepare(`SELECT r.boat_id,r.port,r.report_date,r.counts_json FROM advisor_reports r JOIN advisor_boats b ON b.id=r.boat_id
      WHERE r.status='published' AND r.verified=1 AND b.status='verified' AND r.report_date>=? AND r.report_date<=? ORDER BY r.report_date DESC, r.port LIMIT 500`)
    .bind(from, to).all<{boat_id: string; port: string; report_date: string; counts_json: string}>()).results;
  const days = new Map<string, CatchDay & {ids: Set<string>}>();
  for (const r of rows) {
    const lines = countLines(r.counts_json).filter(c => c.species_key === key || exactSpecies(c.label)?.key === key);
    if (!lines.length) continue;
    const id = `${r.report_date}|${r.port}`;
    const day = days.get(id) ?? {date: r.report_date, port: r.port, kept: 0, released: 0, boats: 0, ids: new Set<string>()};
    for (const c of lines) { day.kept += c.kept ?? 0; day.released += c.released ?? 0; }
    day.ids.add(r.boat_id); day.boats = day.ids.size;
    days.set(id, day);
  }
  return [...days.values()].map(({ids: _ids, ...d}) => d).sort((a, b) => b.date.localeCompare(a.date) || a.port.localeCompare(b.port));
}

// ---- the page ----------------------------------------------------------------------------

/** The page for a page key (speciesPageKey), or null when there is none. */
export async function speciesPage(env: Env, key: string, language: PageLanguage, settings: SiteSettings & {regionDefault: string}, deps: PageDeps = {}): Promise<string | null> {
  const page = PAGES[key];
  if (!page) return null;
  const db = env.DB!, copy = copyFor(language), now = (deps.clock ?? Date.now)();
  const tz = regionConfig(settings.regionDefault)?.timezone ?? 'America/Los_Angeles', today = localDate(now, tz);
  const lang = language === 'es' ? '?lang=es' : '';
  const name = page.names[language];
  const look = lookalikeEntry(key);
  const cues = speciesCues(key, language);
  const others = [...new Set((look?.lookalikes ?? []).map(canonicalSpecies))].filter(k => k !== key && PAGES[k]);
  const [rules, catches] = await Promise.all([
    speciesRules(db, key, jurisdictionFor(settings.regionDefault)),
    recentCatches(db, key, addDays(today, -(SPECIES_CATCH_DAYS - 1)), today),
  ]);
  const strategy = strategyFor(key, settings.regionDefault);
  const how = (strategy?.how ?? []).map(pageSafe).filter((s): s is string => Boolean(s)).slice(0, 3);
  const methods: [string, string | null][] = strategy ? [[copy.rig, pageSafe(strategy.rig)], [copy.baitOrLure, pageSafe(strategy.bait_or_lure)],
    [copy.where, pageSafe(strategy.general_area)], [copy.when, pageSafe(strategy.season_note)]] : [];
  const shown = methods.filter((m): m is [string, string] => Boolean(m[1]));
  const sources = [...new Set([...page.sources, ...(look?.source ? [look.source] : [])])].filter(u => /^https:\/\//.test(u));

  const body = html`<header class="adv-title">
<h1>${name}</h1>
<p class="adv-sub">${copy.speciesNames(page.names.en, page.names.es)}</p>
</header>
<section class="adv-card" aria-labelledby="about-title">
<h2 id="about-title" class="adv-visually-hidden">${name}</h2>
<p>${page.description[language]}</p>
</section>
<section class="adv-card" aria-labelledby="id-title">
<h2 id="id-title">${copy.idHeading}</h2>
${cues.length ? html`<ul class="adv-list">${cues.map(c => html`<li>${c}</li>`)}</ul>` : html`<p>${copy.idNone}</p>`}
${others.length ? html`<h3>${copy.lookalikesHeading}</h3><ul class="adv-inline">${others.map(k => html`<li><a href="/species/${k}${lang}">${PAGES[k]!.names[language]}</a></li>`)}</ul>` : ''}
</section>
${rulesCard(rules, copy, language, today)}
<section class="adv-card" aria-labelledby="catches-title">
<h2 id="catches-title">${copy.catchesHeading}</h2>
${catches.length ? html`<div class="adv-table-wrap" tabindex="0" role="group" aria-label="${copy.catchesHeading}"><table class="adv-table">
<thead><tr><th scope="col">${copy.date}</th><th scope="col">${copy.port}</th><th scope="col">${copy.kept}</th><th scope="col">${copy.releasedHeader}</th><th scope="col">${copy.boats}</th></tr></thead>
<tbody>${catches.map(c => html`<tr><td>${shortDate(c.date, language)}</td><td><a href="/ports/${c.port}${lang}">${portName(c.port) ?? c.port}</a></td><td>${c.kept}</td><td>${c.released}</td><td>${c.boats}</td></tr>`)}</tbody>
</table></div>
<p class="adv-note">${copy.catchesNote}</p>` : html`<p>${copy.catchesNone}</p>`}
</section>
<section class="adv-card" aria-labelledby="strategy-title">
<h2 id="strategy-title">${copy.strategyHeading}</h2>
${how.length || shown.length ? html`${copy.strategyLanguageNote ? html`<p class="adv-note">${copy.strategyLanguageNote}</p>` : ''}
<div lang="en">
${how.length ? html`<ul class="adv-list">${how.map(s => html`<li>${s}</li>`)}</ul>` : ''}
${shown.length ? html`<dl class="adv-facts">${shown.map(([k, v]) => html`<div><dt lang="${language}">${k}</dt><dd>${v}</dd></div>`)}</dl>` : ''}
</div>` : html`<p>${copy.strategyNone}</p>`}
</section>
${sources.length ? html`<section class="adv-card" aria-labelledby="sources-title">
<h2 id="sources-title">${copy.sourcesHeading}</h2>
<ul class="adv-list adv-sources">${sources.map(u => html`<li><a href="${u}" rel="noopener">${u.replace(/^https:\/\//, '')}</a></li>`)}</ul>
</section>` : ''}`;
  return layout({language, kind: 'species', path: `/species/${key}`, title: `${copy.speciesTitle(name)} · SkipperCast`, description: copy.speciesDescription(name),
    crumbs: [{name: copy.species, path: null}, {name, path: `/species/${key}`}], body}, settings);
}
