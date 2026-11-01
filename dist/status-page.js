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

const HOUR = 3_600_000;
export const STATES = Object.freeze({
  ok: 'Inside its interval',
  late: 'Overdue',
  degraded: 'Provider data not current',
  unavailable: 'Cannot be read',
});

const clock = value => (typeof value === 'string' && /(Z|[+-]\d\d:?\d\d)$/.test(value) ? Date.parse(value) : NaN);
const iso = ms => (Number.isFinite(ms) ? new Date(ms).toISOString() : null);

/** One row: a published thing, when it last succeeded, how often it may lag, and whether it is inside that. */
function row(group, name, lastMs, expectedHours, now, {degraded = '', note = ''} = {}) {
  const age = Number.isFinite(lastMs) ? Math.max(0, (now - lastMs) / HOUR) : null;
  const state = degraded ? 'degraded' : age === null ? 'unavailable' : age > expectedHours ? 'late' : 'ok';
  return {group, name, lastSuccess: iso(lastMs), expectedHours, ageHours: age, state, note: degraded || note};
}

const unreadable = (group, name, expectedHours) => ({group, name, lastSuccess: null, expectedHours, ageHours: null, state: 'unavailable', note: ''});

/** Whole-feed row from its own publication stamp. */
function feedRow(group, name, feed, expectedHours, now) {
  if (!feed || typeof feed !== 'object') return unreadable(group, name, expectedHours);
  const limit = Number(feed.schedule?.max_delay_hours) > 0 ? Number(feed.schedule.max_delay_hours) : expectedHours;
  return row(group, name, clock(feed.published_at ?? feed.completed_at ?? feed.generated_at), limit, now);
}

const sourcesOf = feed => Object.values(feed?.sources && typeof feed.sources === 'object' ? feed.sources : {}).filter(s => s && typeof s === 'object');

/** Roll several source objects into one row: newest success, worst state, how many are not current. */
function rollup(group, name, sources, now, expectedFallback) {
  if (!sources.length) return unreadable(group, name, expectedFallback);
  const current = sources.filter(s => !s.reused);
  const bad = sources.filter(s => s.status !== 'ok');
  const times = current.map(s => clock(s.last_success_at)).filter(Number.isFinite);
  const expected = Math.max(...sources.map(s => Number(s.max_age_hours) || expectedFallback));
  const last = times.length ? Math.max(...times) : NaN;
  const out = row(group, name, last, expected, now, bad.length ? {degraded: `${bad.length} of ${sources.length} not current (${[...new Set(bad.map(s => s.status || 'unknown'))].join(', ')})`} : {});
  if (!bad.length && sources.length > 1) out.note = `${sources.length} sources`;
  return out;
}

const FORECAST_NAMES = Object.freeze({'model-gfs_global': 'NOAA wind forecast tiles', 'model-ecmwf_ifs025': 'European wind forecast tiles',
  'model-ncep_gfswave016': 'NOAA wave forecast tiles', 'model-ecmwf_wam': 'European wave forecast tiles'});

const KIND_LABELS = Object.freeze({
  grid: 'Satellite and radar grids',
  observation: 'Buoy observations',
  prediction: 'Tide predictions',
  advisory: 'Marine advisories',
  boundaries: 'Protected-area boundaries',
  forecast: 'Forecast models',
  'page-watch': 'Fishing-rule pages',
  'charter-reports': 'Landing reports',
});

/**
 * The status rows for what the visitor's browser read.
 * feeds: {conditions, data, index, regions: {id: feed}} where a feed that failed to load is null/absent.
 */
export function statusRows(feeds, now = Date.now()) {
  const rows = [];
  const live = health.feeds.conditions, daily = health.feeds.data, regional = health.regions;
  rows.push(feedRow('Live conditions', 'Live conditions feed', feeds.conditions, live.max_age_hours, now));
  const entries = Array.isArray(feeds.index?.regions) ? feeds.index.regions : [];
  for (const entry of entries) {
    const feed = feeds.regions?.[entry.id];
    if (!feed) { rows.push(unreadable('Live conditions', `Buoys: ${entry.name || entry.id}`, regional.max_age_hours)); continue; }
    const base = feedRow('Live conditions', `Buoys: ${entry.name || entry.id}`, feed, regional.max_age_hours, now);
    const bad = sourcesOf(feed).filter(s => s.status !== 'ok');
    if (bad.length && base.state !== 'unavailable') { base.state = 'degraded'; base.note = `${bad.length} of ${sourcesOf(feed).length} buoy readings not current`; }
    rows.push(base);
  }
  rows.push(feedRow('Daily evidence', 'Daily evidence feed', feeds.data, daily.max_age_hours, now));
  const sources = sourcesOf(feeds.data);
  const byKind = new Map();
  for (const source of sources) byKind.set(source.kind || 'other', [...(byKind.get(source.kind || 'other') || []), source]);
  for (const [kind, list] of byKind) {
    if (kind === 'page-watch' || kind === 'charter-reports') { rows.push(rollup('Daily evidence', KIND_LABELS[kind], list, now, daily.max_age_hours)); continue; }
    for (const source of list) rows.push(rollup('Daily evidence', kind === 'forecast' ? FORECAST_NAMES[source.id] || 'Forecast model tiles' : String(source.name || source.id), [source], now, daily.max_age_hours));
  }
  if (!sources.length && feeds.data) rows.push(unreadable('Daily evidence', 'Daily evidence sources', daily.max_age_hours));
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
    'noaa-blended-sst', 'noaa-viirs-merged-chlorophyll', 'noaa-ndbc-hfr-uswc-6km', 'landing-reports'].map(id => [id, 'watched'])),
  ...Object.fromEntries(['ndbc-history', 'noaa-goes-nowcoast', 'cdip-mop', 'slo-beach-water-quality', 'noaa-wcofs', 'noaa-gefs-members', 'noaa-gefs-wave-prob']
    .map(id => [id, 'scheduled-unwatched'])),
  ...Object.fromEntries(['usgs-naip'].map(id => [id, 'browser-direct'])),
});
export const coverageOf = id => SOURCE_COVERAGE[id] || 'fixed';

/** The sources of each category, by name. */
export function coverageGroups(names = SOURCE_NAMES) {
  const groups = {};
  for (const [id, name] of Object.entries(names)) (groups[coverageOf(id)] ||= []).push(name);
  return groups;
}

const text = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
const hours = value => (value < 1 ? `${Math.round(value * 60)} min` : `${value < 10 ? value.toFixed(1) : Math.round(value)} h`);

/** The HTML of the table rows, one <section> per group. */
export function renderRows(rows) {
  const groups = [...new Set(rows.map(r => r.group))];
  return groups.map(group => `<h2>${text(group)}</h2>
<table class="evidence-table status-table"><thead><tr><th scope="col">Data</th><th scope="col">Last successful publish (UTC)</th><th scope="col">Expected within</th><th scope="col">Status</th></tr></thead><tbody>
${rows.filter(r => r.group === group).map(r => `<tr class="status-${r.state}"><th scope="row">${text(r.name)}</th><td>${r.lastSuccess ? `<time datetime="${text(r.lastSuccess)}">${text(r.lastSuccess.slice(0, 16).replace('T', ' '))}</time> (${hours(r.ageHours)} ago)` : 'none'}</td><td>${hours(r.expectedHours)}</td><td>${text(STATES[r.state])}${r.note ? ` · ${text(r.note)}` : ''}</td></tr>`).join('\n')}
</tbody></table>`).join('\n');
}

/** The not-shown section. */
export function renderCoverage(names = SOURCE_NAMES) {
  const groups = coverageGroups(names);
  return ['scheduled-unwatched', 'browser-direct', 'fixed'].filter(k => groups[k]?.length).map(k =>
    `<h3>${text(NOT_SHOWN[k])}</h3>\n<ul>${groups[k].map(n => `<li>${text(n)}</li>`).join('')}</ul>`).join('\n');
}

async function load(url) {
  try { const response = await fetch(url, {cache: 'no-store'}); return response.ok ? await response.json() : null; } catch { return null; }
}

async function main() {
  const [conditions, data, index] = await Promise.all([load('/feeds/conditions/latest.json'), load('/feeds/data/latest.json'), load('/regions/index.json')]);
  const regions = {};
  await Promise.all((index?.regions || []).map(async entry => { regions[entry.id] = await load(`/feeds/conditions/regions/${encodeURIComponent(entry.id)}/latest.json`); }));
  const now = Date.now();
  document.getElementById('status-rows').innerHTML = renderRows(statusRows({conditions, data, index, regions}, now));
  document.getElementById('status-checked').textContent = new Date(now).toISOString().slice(0, 16).replace('T', ' ') + ' UTC';
  document.getElementById('status-coverage').innerHTML = renderCoverage();
}

if (typeof document !== 'undefined' && document.getElementById('status-rows')) main();
