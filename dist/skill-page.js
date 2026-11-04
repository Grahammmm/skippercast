// Public forecast skill scorecard (dist/skill.html). The publisher script
// (scripts/publish_forecast_skill.py) writes data/forecast-skill.json: per active port and buoy, how often each
// forecast was within a stated tolerance of what the buoy then read, over a named rolling window, with its sample
// size. Like the status page, this only reads the published file in the visitor's browser: no timer, no second
// source. A figure is never shown without its sample size and window, or when the sample is below the minimum.
export const WINDOWS = Object.freeze([7, 30]);
export const LEADS = Object.freeze({24: 'Up to 24 h ahead', 48: '24–48 h ahead', 72: '48–72 h ahead'});
export const VARIABLES = Object.freeze({wind_speed_10m: 'Wind speed', wave_height: 'Wave height'});
const FUTURE_TOLERANCE = 10 * 60_000;   // as dist/status-page.js: a stamp further ahead than this is a clock or stamp error

const text = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
const clock = value => (typeof value === 'string' && /(Z|[+-]\d\d:?\d\d)$/.test(value) ? Date.parse(value) : NaN);
const whole = value => Number.isInteger(value) && value >= 0;
const object = value => Boolean(value) && typeof value === 'object' && !Array.isArray(value);

/** Whole percent that never rounds a miss up to 100% or a hit down to 0%. */
export const percent = (within, n) => (within === n ? 100 : within === 0 ? 0 : Math.min(99, Math.max(1, Math.round(100 * within / n))));

const validRow = r => object(r) && typeof r.port === 'string' && typeof r.station === 'string' && Object.hasOwn(VARIABLES, r.variable) && Object.hasOwn(LEADS, r.lead_hours) &&
  WINDOWS.includes(r.window_days) && whole(r.n) && (r.within === null || (whole(r.within) && r.within <= r.n)) && typeof r.tolerance === 'string' && typeof r.enough === 'boolean';

/**
 * What the page may show, or null when the file or the region list cannot be trusted.
 * Ports missing from the region list and rows that do not read are left out and counted.
 */
export function readScorecard(file, index, now = Date.now()) {
  if (!object(file) || file.schema_version !== 1 || !Array.isArray(file.ports) || !Array.isArray(file.scores) || !object(file.minimum)) return null;
  const minimum = file.minimum.valid_times, generated = clock(file.generated_at);
  if (!whole(minimum) || minimum < 1 || !Number.isFinite(generated) || !Array.isArray(index?.regions)) return null;
  const known = new Set(index.regions.map(r => r?.id));
  const ports = file.ports.filter(p => object(p) && typeof p.id === 'string' && typeof p.name === 'string' && known.has(p.id));
  const valid = file.scores.filter(validRow);
  return {minimum, generated, future: generated - now > FUTURE_TOLERANCE, now, skippedPorts: file.ports.length - ports.length, skippedRows: file.scores.length - valid.length,
    ports: ports.map(p => ({id: p.id, name: p.name, stations: (Array.isArray(p.stations) ? p.stations : []).filter(s => object(s) && typeof s.id === 'string')
      .map(s => ({id: s.id, name: typeof s.name === 'string' ? s.name : s.id, rows: valid.filter(r => r.port === p.id && r.station === s.id)}))}))};
}

/** One table cell: the hit rate with its sample size and window, or "not enough data yet" and no percentage. */
export function cell(row, minimum, window) {
  const label = `last ${window} days`;
  if (!row || !row.enough || row.within === null || row.n < minimum) return `<td class="skill-none">Not enough data yet${row ? ` <small>(${row.n} checked, ${label})</small>` : ` <small>(${label})</small>`}</td>`;
  return `<td><strong>${percent(row.within, row.n)}%</strong> <small>(${row.within} of ${row.n} checked, ${label})</small></td>`;
}

/** The HTML of the scorecard: one table per buoy of each port, one row per variable and lead time. */
export function renderScorecard(card) {
  const stamp = card.future ? 'The publish time on this scorecard is in the future, so its age and windows cannot be trusted.'
    : `Published <time datetime="${text(new Date(card.generated).toISOString())}">${text(new Date(card.generated).toISOString().slice(0, 16).replace('T', ' '))} UTC</time>.`;
  const skipped = [card.skippedPorts && `${card.skippedPorts} port(s) left out because they are not in the region list`, card.skippedRows && `${card.skippedRows} row(s) could not be read`].filter(Boolean);
  const body = card.ports.map(port => `<h2>${text(port.name)}</h2>\n${port.stations.map(station => {
    const find = (variable, lead, window) => station.rows.find(r => r.variable === variable && Number(r.lead_hours) === Number(lead) && r.window_days === window);
    const rows = Object.entries(VARIABLES).flatMap(([variable, name]) => Object.entries(LEADS).filter(([lead]) => WINDOWS.some(w => find(variable, lead, w))).map(([lead, leadName]) =>
      `<tr><th scope="row">${text(name)}</th><td>${text(leadName)}</td><td>${text((find(variable, lead, 7) || find(variable, lead, 30)).tolerance)}</td>${WINDOWS.map(w => cell(find(variable, lead, w), card.minimum, w)).join('')}</tr>`));
    return `<h3>${text(station.name)} <small>(buoy ${text(station.id)})</small></h3>\n${rows.length ? `<table class="evidence-table skill-table"><thead><tr><th scope="col">Forecast</th><th scope="col">Lead time</th><th scope="col">Counts as right when</th><th scope="col">Last 7 days</th><th scope="col">Last 30 days</th></tr></thead><tbody>\n${rows.join('\n')}\n</tbody></table>` : '<p>No scores are published for this buoy yet.</p>'}`;
  }).join('\n') || '<p>No buoy is verified for this port yet.</p>'}`).join('\n');
  return `<p>${stamp}</p>${skipped.length ? `<p>${text(skipped.join('; '))}.</p>` : ''}\n${body || '<p>No port has a published record yet.</p>'}`;
}

export const UNREADABLE = '<p>The scorecard could not be read. No scores are shown.</p>';

async function load(url) {
  try { const response = await fetch(url, {cache: 'no-store'}); return response.ok ? await response.json() : null; } catch { return null; }
}

async function main() {
  const [file, index] = await Promise.all([load('/data/forecast-skill.json'), load('/regions/index.json')]);
  const card = readScorecard(file, index, Date.now());
  document.getElementById('skill-rows').innerHTML = card ? renderScorecard(card) : UNREADABLE;
}

if (typeof document !== 'undefined' && document.getElementById('skill-rows')) main();
