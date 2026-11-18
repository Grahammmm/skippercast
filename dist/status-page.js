// Public status page (dist/status.html, served at /status; SC-LAUNCH-5).
// Publishes what the existing freshness watchdog already knows: every published
// feed carries, per source, its status, its last successful read and the age it
// may reach (max_age_hours); catalog/feed-health.json holds the feed limits that
// scripts/check_feed_freshness.py and server/watchdog.ts share. This page only
// reads those published feeds in the visitor's browser: no timer, no detector,
// no second monitoring path. Request URLs, error text and run ids in the feeds
// are never shown.
import health from '../catalog/feed-health.json' with {type: 'json'};
import {SOURCE_NAMES} from './status-names.js';
import english from './status-strings.generated.json' with {type: 'json'};
import {lookup} from '../web/i18n-core.ts';
import {bilingual, initReadyLanguage} from '../web/i18n-catalogue.ts';
const STRINGS = bilingual(english);
const t = (id, lang = 'en', vars = {}) => lookup(STRINGS, 'status.' + id, lang, vars);
const providerLabel = (value, lang) => STRINGS['status.provider.' + String(value).replaceAll(' ', '-')] ? t('provider.' + String(value).replaceAll(' ', '-'), lang) : value;

/** Translate only marked static hosts; English leaves the authored bytes alone. */
export async function initStatusPage(doc, env) {
  const lang = await initReadyLanguage(env);
  if (doc.documentElement) doc.documentElement.lang = lang;
  if (lang === 'en') return lang;
  doc.title = t('title', lang);
  for (const [attr, apply] of [['data-i18n', (el, value) => { el.textContent = value; }], ['data-i18n-lead', (el, value) => { el.firstChild.nodeValue = value + ' '; }], ['data-i18n-aria', (el, value) => { el.setAttribute('aria-label', value); }]]) {
    for (const el of doc.querySelectorAll('[' + attr + ']')) apply(el, lookup(STRINGS, el.getAttribute(attr), lang));
  }
  return lang;
}

const HOUR = 3_600_000;
const FUTURE_TOLERANCE = 10 * 60_000;   // scripts/check_feed_freshness.py FUTURE_TOLERANCE
export const STATES = Object.freeze({
  ok: 'Inside its interval',
  late: 'Overdue',
  degraded: 'Provider data not current',
  unavailable: 'Cannot be read',
});

const clock = value => (typeof value === 'string' && /(Z|[+-]\d\d:?\d\d)$/.test(value) ? Date.parse(value) : NaN);
const iso = ms => (Number.isFinite(ms) ? new Date(ms).toISOString() : null);

/** One row: a published thing, when it last succeeded, how often it may lag, and whether it is inside that. */
function row(group, name, lastMs, expectedHours, now, {degraded = '', note = '', lang = 'en'} = {}) {
  if (Number.isFinite(lastMs) && lastMs - now > FUTURE_TOLERANCE) {
    // The checker rejects a stamp more than 10 minutes ahead as unreadable (clock or stamp error).
    return {group, name, lastSuccess: iso(lastMs), expectedHours, ageHours: null, state: 'unavailable', note: t('future', lang)};
  }
  const age = Number.isFinite(lastMs) ? Math.max(0, (now - lastMs) / HOUR) : null;
  const state = degraded ? 'degraded' : age === null ? 'unavailable' : age > expectedHours ? 'late' : 'ok';
  return {group, name, lastSuccess: iso(lastMs), expectedHours, ageHours: age, state, note: degraded || note};
}

const unreadable = (group, name, expectedHours, note = '') => ({group, name, lastSuccess: null, expectedHours, ageHours: null, state: 'unavailable', note});

/** Whole-feed row from its own publication stamp. */
function feedRow(group, name, feed, expectedHours, now, lang = 'en') {
  if (!feed || typeof feed !== 'object') return unreadable(group, name, expectedHours);
  const limit = Number(feed.schedule?.max_delay_hours) > 0 ? Number(feed.schedule.max_delay_hours) : expectedHours;
  return row(group, name, clock(feed.published_at ?? feed.completed_at ?? feed.generated_at), limit, now, {lang});
}

/** Not current service, as degraded_sources() in scripts/check_feed_freshness.py: any status but ok, or a backup
 * station standing in for its primary (fallback_for), which the checker reports as degraded service. */
const notCurrent = s => s.status !== 'ok' || Boolean(s.fallback_for);
const notCurrentLabel = (s, lang) => providerLabel(s.status !== 'ok' ? s.status || 'unknown' : 'backup station', lang);

const sourcesOf = feed => Object.values(feed?.sources && typeof feed.sources === 'object' ? feed.sources : {}).filter(s => s && typeof s === 'object');

const RANK = Object.freeze({unavailable: 3, late: 2, ok: 0});

/** Roll several source objects into one row, judged by its worst member: each source against its own
 * max_age_hours, the row showing the worst (then oldest) one. A reused source (an older landing day kept
 * from an earlier run on purpose) is not judged by its age, only by its status. */
function rollup(group, name, sources, now, expectedFallback, lang = 'en') {
  if (!sources.length) return unreadable(group, name, expectedFallback);
  const current = sources.filter(s => !s.reused);
  const bad = sources.filter(notCurrent);
  const each = current.map(s => row(group, name, clock(s.last_success_at), Number(s.max_age_hours) || expectedFallback, now, {lang}));
  if (!each.length) each.push(unreadable(group, name, expectedFallback));
  each.sort((a, b) => RANK[b.state] - RANK[a.state] || (b.ageHours ?? Infinity) - (a.ageHours ?? Infinity));
  const out = {...each[0]};
  const off = each.filter(r => r.state !== 'ok');
  if (bad.length) {
    out.state = 'degraded';
    out.note = t('notCurrent', lang, {bad: bad.length, total: sources.length, labels: [...new Set(bad.map(s => notCurrentLabel(s, lang)))].join(', ')});
  } else if (off.length && sources.length > 1) {
    out.note = t('off', lang, {bad: off.length, total: sources.length, label: t(off.every(r => r.state === 'late') ? 'overdue' : 'unreadableOrOverdue', lang)});
  } else if (!off.length && sources.length > 1) out.note = t('sources', lang, {total: sources.length});
  return out;
}

const FORECAST_NAMES = Object.freeze({'model-gfs_global': 'NOAA wind forecast tiles', 'model-ecmwf_ifs025': 'European wind forecast tiles',
  'model-ncep_gfswave016': 'NOAA wave forecast tiles', 'model-ecmwf_wam': 'European wave forecast tiles'});

const REGION_ID = /^[a-z0-9-]+$/;
const isObject = value => Boolean(value) && typeof value === 'object' && !Array.isArray(value);

/** The region index's entries, or [] when the index or ANY member has the wrong shape (the whole list is then
 * unavailable: a valid subset must not read as complete coverage, and no id is ever invented). */
function regionEntries(index) {
  const list = isObject(index) ? index.regions : null;
  return Array.isArray(list) && list.every(e => isObject(e) && typeof e.id === 'string' && REGION_ID.test(e.id)) ? list : [];
}

/**
 * The status rows for what the visitor's browser read.
 * feeds: {conditions, data, index, regions: {id: feed}, coast?: {feed name: feed}} where a feed that failed to load is null/absent.
 */
export function statusRows(feeds, now = Date.now(), lang = 'en') {
  const rows = [];
  const live = health.feeds.conditions, daily = health.feeds.data, regional = health.regions;
  rows.push(feedRow(t('group.live', lang), t('names.live', lang), feeds.conditions, live.max_age_hours, now, lang));
  const entries = regionEntries(feeds.index);
  if (!entries.length) rows.push(unreadable(t('group.live', lang), t('names.regional', lang), regional.max_age_hours, t('regionalMissing', lang)));
  for (const entry of entries) {
    const feed = feeds.regions?.[entry.id];
    if (!feed) { rows.push(unreadable(t('group.live', lang), t('buoys', lang, {name: entry.name || entry.id}), regional.max_age_hours)); continue; }
    const base = feedRow(t('group.live', lang), t('buoys', lang, {name: entry.name || entry.id}), feed, regional.max_age_hours, now, lang);
    const bad = sourcesOf(feed).filter(notCurrent);
    if (bad.length && base.state !== 'unavailable') {
      base.state = 'degraded';
      base.note = t('buoyReadings', lang, {bad: bad.length, total: sourcesOf(feed).length, labels: [...new Set(bad.map(s => notCurrentLabel(s, lang)))].join(', ')});
    }
    rows.push(base);
  }
  rows.push(feedRow(t('group.daily', lang), t('names.daily', lang), feeds.data, daily.max_age_hours, now, lang));
  const sources = sourcesOf(feeds.data);
  const byKind = new Map();
  // The harbor page (catalog harbor-authority) is a page-watch source too, but not a fishing rule: own row.
  const groupOf = source => (source.kind === 'page-watch' && source.id === 'harbor' ? 'harbor' : source.kind || 'other');
  for (const source of sources) byKind.set(groupOf(source), [...(byKind.get(groupOf(source)) || []), source]);
  for (const [kind, list] of byKind) {
    if (kind === 'page-watch' || kind === 'charter-reports') { rows.push(rollup(t('group.daily', lang), t('kind.' + kind, lang), list, now, daily.max_age_hours, lang)); continue; }
    for (const source of list) rows.push(rollup(t('group.daily', lang), kind === 'forecast' ? FORECAST_NAMES[source.id] || 'Forecast model tiles' : String(source.name || source.id), [source], now, daily.max_age_hours, lang));
  }
  if (!sources.length && feeds.data) rows.push(unreadable(t('group.daily', lang), t('names.empty', lang), daily.max_age_hours));
  if (feeds.coast) rows.push(...coastRows(feeds.coast, now, lang));
  return rows;
}

const coastStatus = s => s.status ?? s.outcome;
// Only these values are shown; anything else in a feed reads as unknown, so no feed text reaches the page.
const coastLabel = value => (['error', 'pending', 'stale'].includes(value) ? value : 'unknown');

/**
 * The Morro Bay coast feeds (catalog/feed-health.json coast, the limits server/coast-data.ts uses): one row per
 * listed source, from that source's own fetchedAt and status/outcome in the feed; history from its generatedAt.
 * coast: {ocean, nearshore, 'water-quality', history}, each parsed JSON or null when it failed to load.
 */
export function coastRows(coast, now = Date.now(), lang = 'en') {
  const COAST = t('group.coast', lang);
  const rows = [];
  for (const [feedName, config] of Object.entries(health.coast)) {
    const feed = coast[feedName], limit = config.max_age_hours;
    for (const id of config.sources) {
      const name = SOURCE_NAMES[id] || id;
      if (!feed || typeof feed !== 'object' || Array.isArray(feed)) { rows.push(unreadable(COAST, name, limit)); continue; }
      if (feedName === 'history') { rows.push(row(COAST, name, clock(feed.generatedAt), limit, now, {lang})); continue; }
      // The nearshore feed lists one entry per CDIP site (cdip-<site>); they roll up into the one catalog row.
      const members = (Array.isArray(feed.sources) ? feed.sources : []).filter(s => s && typeof s === 'object' &&
        (feedName === 'nearshore' ? String(s.id).startsWith('cdip-') : s.id === id));
      if (!members.length) { rows.push(unreadable(COAST, name, limit, t('missingMember', lang))); continue; }
      if (members.length === 1) {
        const status = coastStatus(members[0]);
        rows.push(row(COAST, name, clock(members[0].fetchedAt), limit, now, {degraded: status === 'ok' ? '' : providerLabel(coastLabel(status), lang), lang}));
        continue;
      }
      rows.push(rollup(COAST, name, members.map(s => ({status: coastStatus(s) === 'ok' ? 'ok' : coastLabel(coastStatus(s)),
        last_success_at: s.fetchedAt, max_age_hours: limit})), now, limit, lang));
    }
  }
  return rows;
}

/** Sources in catalog/sources.json this page does not show a freshness for, with the reason. */
export const NOT_SHOWN = Object.freeze({
  watched: 'Shown above',
  'scheduled-unwatched': 'Published on a schedule, but the freshness check does not watch it yet',
  'browser-direct': 'Fetched by your browser from the provider; SkipperCast publishes nothing',
  'fixed': 'Fixed release or research data; nothing is published on a schedule',
});

/** catalog/sources.json id -> category. A test keeps this complete against the catalog. */
export const SOURCE_COVERAGE = Object.freeze({
  ...Object.fromEntries(['ndbc-buoys', 'nws-weather', 'noaa-tides', 'cdfw-mpas', 'cdfw-rules', 'noaa-gfs', 'ecmwf-ifs', 'noaa-gfs-wave', 'ecmwf-wam',
    'noaa-blended-sst', 'noaa-viirs-merged-chlorophyll', 'noaa-ndbc-hfr-uswc-6km', 'landing-reports', 'harbor-authority',
    'ndbc-history', 'noaa-goes-nowcoast', 'cdip-mop', 'slo-beach-water-quality', 'noaa-wcofs'].map(id => [id, 'watched'])),
  ...Object.fromEntries(['noaa-gefs-members', 'noaa-gefs-wave-prob'].map(id => [id, 'scheduled-unwatched'])),
  ...Object.fromEntries(['usgs-naip'].map(id => [id, 'browser-direct'])),
});
export const coverageOf = id => SOURCE_COVERAGE[id] || 'fixed';

/** Services docs/data-sources.md documents that have no catalog/sources.json entry: name and category. */
export const DOCUMENTED_EXTRA = Object.freeze({
  'noaa-enc-display': {name: "NOAA ENC display service (chart images on the map)", coverage: 'browser-direct'},
});

/** The sources of each category, by name. */
export function coverageGroups(names = SOURCE_NAMES, extra = DOCUMENTED_EXTRA) {
  const groups = {};
  for (const [id, name] of Object.entries(names)) (groups[coverageOf(id)] ||= []).push(name);
  for (const {name, coverage} of Object.values(extra)) (groups[coverage] ||= []).push(name);
  return groups;
}

const text = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
const hours = value => (value < 1 ? `${Math.round(value * 60)} min` : `${value < 10 ? value.toFixed(1) : Math.round(value)} h`);

/** The HTML of the table rows, one <section> per group. */
export function renderRows(rows, lang = 'en') {
  const groups = [...new Set(rows.map(r => r.group))];
  return groups.map(group => `<h2>${text(group)}</h2>
<div class="forecast-table-wrap" role="region" tabindex="0" aria-label="${text(t('table', lang, {group}))}"><table class="evidence-table status-table"><thead><tr><th scope="col">${text(t('data', lang))}</th><th scope="col">${text(t('last', lang))}</th><th scope="col">${text(t('expected', lang))}</th><th scope="col">${text(t('status', lang))}</th></tr></thead><tbody>
${rows.filter(r => r.group === group).map(r => `<tr class="status-${r.state}"><th scope="row">${text(r.name)}</th><td>${r.lastSuccess ? `<time datetime="${text(r.lastSuccess)}">${text(r.lastSuccess.slice(0, 16).replace('T', ' '))}</time>${r.ageHours === null ? '' : ` (${text(t('ago', lang, {hours: hours(r.ageHours)}))})`}` : t('none', lang)}</td><td>${hours(r.expectedHours)}</td><td>${text(t('state.' + r.state, lang))}${r.note ? ` · ${text(r.note)}` : ''}</td></tr>`).join('\n')}
</tbody></table></div>`).join('\n');
}

/** The not-shown section. */
export function renderCoverage(names = SOURCE_NAMES, lang = 'en') {
  const groups = coverageGroups(names);
  return ['scheduled-unwatched', 'browser-direct', 'fixed'].filter(k => groups[k]?.length).map(k =>
    `<h3>${text(t('coverage.' + k, lang))}</h3>\n<ul>${groups[k].map(n => `<li>${text(n)}</li>`).join('')}</ul>`).join('\n');
}

async function load(url) {
  try { const response = await fetch(url, {cache: 'no-store'}); return response.ok ? await response.json() : null; } catch { return null; }
}

export async function main() {
  const lang = await initStatusPage(document);
  const coastNames = Object.keys(health.coast);
  const [conditions, data, index, ...coastFeeds] = await Promise.all([load('/feeds/conditions/latest.json'), load('/feeds/data/latest.json'), load('/regions/index.json'),
    ...coastNames.map(name => load(`/feeds/${health.coast[name].path}`))]);
  const coast = Object.fromEntries(coastNames.map((name, i) => [name, coastFeeds[i]]));
  const regions = {};
  await Promise.all(regionEntries(index).map(async entry => { regions[entry.id] = await load(`/feeds/conditions/regions/${encodeURIComponent(entry.id)}/latest.json`); }));
  const now = Date.now();
  document.getElementById('status-rows').innerHTML = renderRows(statusRows({conditions, data, index, regions, coast}, now, lang), lang);
  document.getElementById('status-checked').textContent = new Date(now).toISOString().slice(0, 16).replace('T', ' ') + ' UTC';
  document.getElementById('status-coverage').innerHTML = renderCoverage(undefined, lang);
}

if (typeof document !== 'undefined' && document.getElementById('status-rows')) main();
