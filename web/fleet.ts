// The Fleet view's data (FE-53, docs/plans/front-end/design.md § 6 and § 9):
// the admin filter form's choices and values, ported from dist/fleet-activity.js
// (`FILTERS`, `filterOptions`, `readFilters`) as data rather than HTML, and the
// boat directory link.
//
// v1's module is not imported here: it reads v1's region and chart modules, and
// the app entry must not carry them for a visitor. tests/test_fleet_view.mjs pins
// these names and labels to v1's own. The queries themselves stay v1's
// (`layerQuery` through `fetchLayer`, web/map/fleet.ts), so a filter reaches the
// map API exactly as v1 sends it.
//
// Privacy: the choices exist only once the server admitted the viewer (the map
// API's filters probe is admin only and a 404 while either fleet flag is off), so
// no boat name reaches a visitor's view. The directory link points at the public
// port pages' "Boats out of …" list (charter-fleet design § 15, pick 1), shown
// only while that page answers.
//
// Erasable syntax only: Node tests import this file by type stripping.
import {loadPorts, type Port} from './ports.ts';

/** v1's query names, in its form's order (dist/fleet-activity.js `FILTERS`). */
export const FILTERS = ['vessel', 'port', 'class', 'trip_type', 'kind', 'from', 'to', 'season', 'season_part'] as const;
export type FilterName = typeof FILTERS[number];
export type Filters = Partial<Record<FilterName, string>>;
/** The form's labels (v1's dist/index.html `#fleet-filters`). */
export const FILTER_LABELS: Readonly<Record<FilterName, string>> = {vessel: 'Boat', port: 'Port', class: 'Vessel class', trip_type: 'Trip type',
  kind: 'Activity type', from: 'From', to: 'To', season: 'Season', season_part: 'Season part'};
/** v1's event labels (dist/fleet-activity.js `EVENT_STYLE`). */
const KIND_LABELS: Readonly<Record<string, string>> = {'drift-anchor': 'Drift or anchor', 'troll-slow': 'Slow troll', 'troll-pelagic': 'Offshore troll'};
export const VESSELS_NOTE = 'The boat list shows the first 500 boats by name.';
export const PLANNING_LABEL = 'Leave out NOAA planning-only rows';
export const HOW_INFERRED = 'Stops and segment kinds come from AIS speed and track shape. Drift or anchor stops are filled circles; troll stops are rings. Dates are each trip\'s local departure date. Heat cells hold no boat, port, class, trip type or source.';

export interface Choice {readonly value: string; readonly label: string}
export type SelectName = Exclude<FilterName, 'from' | 'to'>;

const label = (v: unknown): string => v ? String(v).replace(/[-_]+/g, ' ').replace(/^./, c => c.toUpperCase()) : '—';
const list = (v: unknown): unknown[] => Array.isArray(v) ? v : [];

/** The selects' options from GET /api/fleet/map/filters, as v1's `filterOptions` builds them. */
export function filterChoices(data: Record<string, unknown> | null): Record<SelectName, Choice[]> {
  const any: Choice = {value: '', label: 'Any'};
  const named = (key: string, text: (v: string) => string = label) => [any, ...list(data?.[key]).map(v => ({value: String(v), label: text(String(v))}))];
  return {
    vessel: [any, ...list(data?.vessels).map(v => { const b = v as {id: string; name?: string}; return {value: String(b.id), label: String(b.name || b.id)}; })],
    port: named('ports'), class: named('classes'), trip_type: named('trip_types'),
    kind: named('kinds', v => KIND_LABELS[v] ?? label(v)),
    season: named('seasons', v => v),
    season_part: [{value: '', label: 'Whole season'}, ...list(data?.season_parts).map(v => ({value: String(v), label: label(v)}))],
  };
}

/** The date inputs' bounds from the probe (`dates.min`, `dates.max`). */
export function dateBounds(data: Record<string, unknown> | null): {min?: string; max?: string} {
  const d = data?.dates as {min?: unknown; max?: unknown} | undefined;
  return {...typeof d?.min === 'string' ? {min: d.min} : {}, ...typeof d?.max === 'string' ? {max: d.max} : {}};
}

/** The form's values by name, trimmed, empty ones left out (v1's `readFilters`). */
export function readFilters(values: Readonly<Record<string, unknown>>): Filters {
  const out: Filters = {};
  for (const name of FILTERS) {
    const value = String(values[name] ?? '').trim();
    if (value) out[name] = value;
  }
  return out;
}

/** The public port page's boat list for `port`. */
export const directoryHref = (port: Pick<Port, 'id'>): string => `/ports/${encodeURIComponent(port.id)}#boats-title`;

/** The region's active ports, the saved one first. */
export function regionPorts(ports: readonly Port[], region: string | null, saved: string | null = null): Port[] {
  const here = ports.filter(p => p.region === region && p.status === 'active');
  return [...here.filter(p => p.id === saved), ...here.filter(p => p.id !== saved)];
}

// Share only a pending HEAD, keyed by fetcher and exact page. Never retain a
// settled answer: a later visit must still observe the public page's off gate.
const directoryProbes = new WeakMap<typeof fetch, Map<string, Promise<boolean>>>();
function directoryAnswers(url: string, fetcher: typeof fetch): Promise<boolean> {
  let probes = directoryProbes.get(fetcher);
  if (!probes) { probes = new Map(); directoryProbes.set(fetcher, probes); }
  const pending = probes.get(url);
  if (pending) return pending;
  const answer = Promise.resolve().then(() => fetcher(url, {method: 'HEAD', credentials: 'omit', cache: 'no-store'}))
    .then(r => r.ok, () => false).finally(() => { probes.delete(url); });
  probes.set(url, answer);
  return answer;
}

/**
 * The ports whose public boat list answers, else none. One HEAD of the first port's
 * page: the page 404s while it is switched off, so only an ok answer shows the link.
 * Concurrent calls share that HEAD; no cookie is sent or settled answer stored.
 */
export async function boatDirectory(region: string | null, saved: string | null = null, fetcher: typeof fetch = fetch,
  ports: () => Promise<readonly Port[]> = () => loadPorts(fetcher)): Promise<Port[]> {
  if (!region) return [];
  try {
    const here = regionPorts(await ports(), region, saved);
    if (!here.length) return [];
    const ok = await directoryAnswers(directoryHref(here[0]!).split('#')[0]!, fetcher);
    return ok ? here : [];
  } catch { return []; }
}
