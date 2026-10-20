// CI6-18: physical identities, never a logical primary's geometry for a backup.
// Pure model; no acquisition, station discovery, or inferred positions.
import type {County, Report} from '../../packages/coast/src/types.ts';
import type {RegionalDailyFeed, RegionalSource} from '../brief/types.ts';
import {ndbcStationURL, sourceStation, tidePredictionURL} from '../station-label.ts';
import type {ChartMark} from './coastline.ts';

export type Provider = 'ndbc' | 'coops';
export interface StationConfig {
  tide?: string; nearshore_buoy?: string; offshore_buoy?: string;
  roles?: Partial<Record<'tide' | 'nearshore_buoy' | 'offshore_buoy', {stations: readonly string[]}>>;
}
export interface StationRegion {id: string; stations?: StationConfig; contexts?: Record<string, {stations?: StationConfig}>; forecast_points?: readonly {id: string; context?: string}[]}
export interface Location {provider: string; id: string; name: string; latitude: number; longitude: number; program?: string; owner?: string}
export interface StationCatalog {stations: Readonly<Record<string, Location>>}
export interface StationIdentity {provider: Provider; id: string}
export interface StationPin {key: string; location: Location | null; mark: ChartMark; stale: boolean}
export const STATION_BASIS = 'NOAA NDBC buoy observations and CO-OPS tide predictions at station point locations (no grid), including CDIP/Scripps buoys served by NDBC. Locations remain visible; observations older than 3 hours and predictions retrieved over 36 hours ago are labelled stale, with last-good values and original times retained. Missing or invalid clocks are unavailable. CDIP MOP model sites use the bound report only: samples within 90 minutes of the selected hour, withheld after 48 hours from issue or 3 hours from retrieval. Model sites are not observing buoys.';
const HOUR = 3_600_000;
const finite = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v);
export const stationClock = (v: unknown): number => typeof v === 'string' && /(?:Z|[+-]\d\d:\d\d)$/.test(v) ? Date.parse(v) : NaN;
export function readingState(at: unknown, now: number, limit: number, retained = false): 'fresh' | 'stale' | 'unavailable' {
  const t = stationClock(at);
  if (!finite(t) || t > now + 5 * 60_000) return 'unavailable';
  return retained || now - t > limit ? 'stale' : 'fresh';
}
export function configuredStations(stations: StationConfig = {}): StationIdentity[] {
  const found = new Map<string, StationIdentity>();
  for (const role of ['tide', 'nearshore_buoy', 'offshore_buoy'] as const) {
    const provider = role === 'tide' ? 'coops' : 'ndbc';
    for (const id of [stations[role], ...(stations.roles?.[role]?.stations ?? [])])
      if (id) found.set(`${provider}:${id}`, {provider, id});
  }
  return [...found.values()];
}
export function selectedStations(region: StationRegion, context: string | null, county?: County | null): StationIdentity[] {
  const contextId = region.forecast_points?.find(p => p.id === context)?.context ?? context;
  const selected = configuredStations(contextId && region.contexts?.[contextId]?.stations || region.stations);
  if (county) selected.push({provider: 'coops', id: county.tideStation.id}, ...county.buoys.map(b => ({provider: 'ndbc' as const, id: b.id})), {provider: 'ndbc', id: county.temperatureStationId});
  return [...new Map(selected.map(s => [`${s.provider}:${s.id}`, s])).values()];
}
export function located(loc: Location | undefined): loc is Location {
  return !!loc && finite(loc.latitude) && finite(loc.longitude) && Math.abs(loc.latitude) <= 90 && Math.abs(loc.longitude) <= 180;
}
interface Sample {at: string; value: number; retained: boolean}
const VARIABLES = [
  {key: 'WVHT', field: 'waveFt', label: 'Seas', unit: 'ft', raw: 'm', scale: 3.280839895, offset: 0},
  {key: 'DPD', field: 'wavePeriodS', label: 'Period', unit: 's', raw: 'sec', scale: 1, offset: 0},
  {key: 'WTMP', field: 'waterTempF', label: 'Water', unit: '°F', raw: 'degC', scale: 1.8, offset: 32},
  {key: 'WSPD', field: 'windKnots', label: 'Wind', unit: 'kt', raw: 'm/s', scale: 1.943844492, offset: 0},
  {key: 'GST', field: 'gustKnots', label: 'Gust', unit: 'kt', raw: 'm/s', scale: 1.943844492, offset: 0},
] as const;
const rows = (v: unknown): Record<string, unknown>[] => Array.isArray(v) ? v.filter(r => r && typeof r === 'object') : [];
/** Mismatching payload identity is never relabelled with the role's station. */
function matches(source: RegionalSource, id: string): boolean {
  const dataId = source.data?.station;
  const actual = sourceStation(source, typeof dataId === 'string' ? dataId : null);
  return actual?.id === id && (dataId === undefined || dataId === id);
}
const clock = (s: RegionalSource): string => s.status === 'retained' ? s.data_retrieved_at ?? s.last_success_at ?? '' : s.data_retrieved_at ?? s.checked_at;
function observations(id: string, sources: RegionalSource[], report: Report | null, now: number): {text: string; stale: boolean} {
  let stale = false;
  const lines = VARIABLES.map(v => {
    const samples: Sample[] = [];
    for (const s of sources.filter(s => s.kind === 'observation' && matches(s, id))) {
      const units = s.data?.units as Record<string, unknown> | undefined;
      if (units?.[v.key] !== v.raw) continue;
      for (const r of rows(s.data?.observations)) if (finite(r[v.key]) && typeof r.time === 'string')
        samples.push({at: r.time, value: (r[v.key] as number) * v.scale + v.offset, retained: s.status !== 'ok'});
    }
    for (const o of report?.observations ?? []) if (o.stationId === id && finite(o[v.field]))
      samples.push({at: o.observedAt, value: o[v.field]!, retained: report!.sources.some(s => s.kind === 'observation' && s.url === o.url && s.outcome !== 'ok')});
    const sample = samples.filter(s => readingState(s.at, now, 3 * HOUR) !== 'unavailable')
      .sort((a, b) => stationClock(b.at) - stationClock(a.at) || Number(a.retained) - Number(b.retained))[0];
    if (!sample) return `${v.label}: unavailable`;
    const state = readingState(sample.at, now, 3 * HOUR, sample.retained);
    stale ||= state === 'stale';
    return `${v.label} ${sample.value.toFixed(1)} ${v.unit} · ${sample.at} · ${state}${sample.retained ? ' / last good' : ''}`;
  });
  return {text: lines.join('; '), stale: stale || lines.every(l => l.endsWith('unavailable'))};
}
function predictions(id: string, sources: RegionalSource[], report: Report | null, county: County | null, at: number, now: number): {text: string; stale: boolean} {
  const products: {points: {at: string; value: number; type: string}[]; fetched: string; retained: boolean; datum: string; note: string; start?: string; end?: string}[] = [];
  for (const s of sources.filter(s => s.kind === 'prediction' && matches(s, id))) {
    if (s.data?.units !== 'ft' || typeof s.data.datum !== 'string') continue;
    products.push({points: rows(s.data.predictions).filter(r => finite(r.height_ft) && typeof r.time === 'string').map(r => ({at: String(r.time), value: r.height_ft as number, type: r.type === 'H' ? 'high event' : r.type === 'L' ? 'low event' : 'prediction'})),
      fetched: clock(s), retained: s.status !== 'ok', datum: s.data.datum, note: String(s.data.note ?? ''), start: String(s.data.coverage_start ?? ''), end: String(s.data.coverage_end ?? '')});
  }
  if (report && county?.tideStation.id === id) {
    const predictionSources = report.sources.filter(s => s.kind === 'prediction');
    // Report points carry no sourceId. Use the oldest prediction retrieval,
    // never borrow a newer product's clock to freshen a retained curve.
    const s = [...predictionSources].sort((a, b) => (stationClock(a.fetchedAt) || -Infinity) - (stationClock(b.fetchedAt) || -Infinity))[0];
    if (s) {
      const curve = report.tides.length > 0;
      products.push({points: (curve ? report.tides : report.tideEvents).map(p => ({at: p.at, value: p.heightFt, type: 'type' in p ? p.type === 'H' ? 'high event' : 'low event' : 'prediction'})), fetched: s.fetchedAt,
        retained: predictionSources.some(p => p.outcome !== 'ok'), datum: 'MLLW', note: `Oldest bound prediction retrieval clock. ${county.tideStation.note}`});
    }
  }
  const product = products.filter(p => readingState(p.fetched, now, 36 * HOUR) !== 'unavailable')
    .sort((a, b) => stationClock(b.fetched) - stationClock(a.fetched))[0];
  if (!product) return {text: 'Tide prediction unavailable; no valid retrieval clock or data.', stale: true};
  const points = product.points.filter(p => finite(p.value) && finite(stationClock(p.at))).sort((a, b) => stationClock(a.at) - stationClock(b.at));
  const start = stationClock(product.start) || stationClock(points[0]?.at), end = stationClock(product.end) || stationClock(points.at(-1)?.at);
  const coverage = finite(start) && finite(end) ? `coverage ${new Date(start).toISOString()} – ${new Date(end).toISOString()}` : 'coverage unavailable';
  const state = readingState(product.fetched, now, 36 * HOUR, product.retained);
  const stamp = `retrieved ${product.fetched} · ${state}${product.retained ? ' / last good' : ''} · ${coverage}. ${product.note}`;
  if (!(at >= start && at <= end)) return {text: `Tide prediction unavailable for selected time; ${stamp}`, stale: true};
  const curve = points.filter(p => p.type === 'prediction');
  const point = curve.length ? curve.reduce((a, b) => Math.abs(stationClock(a.at) - at) <= Math.abs(stationClock(b.at) - at) ? a : b) : points.find(p => stationClock(p.at) >= at);
  if (!point || (curve.length && Math.abs(stationClock(point.at) - at) > 90 * 60_000)) return {text: `Tide prediction gap; ${stamp}`, stale: true};
  return {text: `Tide ${point.type}: ${point.value.toFixed(1)} ft ${product.datum} · valid ${point.at}; ${stamp}`, stale: state === 'stale'};
}
export function stationPins(input: {region: StationRegion; context?: string | null; catalog: StationCatalog; feed: RegionalDailyFeed | null; report?: Report | null; county?: County | null; now: Date; at: Date}): StationPin[] {
  const {region, catalog, now, at} = input, report = input.report ?? null, county = input.county ?? null;
  const sources = input.feed?.region_id === region.id ? Object.values(input.feed.sources).filter((s): s is RegionalSource => !!s) : [];
  return selectedStations(region, input.context ?? null, county).map(identity => {
    const {provider, id} = identity, key = `${provider}:${id}`, metadata = catalog.stations[key];
    const location = metadata?.id === id && metadata.provider === provider && located(metadata) ? metadata : null;
    const reading = provider === 'ndbc' ? observations(id, sources, report, now.getTime()) : predictions(id, sources, report, county, at.getTime(), now.getTime());
    const backups = [...new Set(sources.filter(s => matches(s, id)).map(s => sourceStation(s)?.backupFor).filter(Boolean))];
    const publisher = provider === 'coops' ? 'NOAA CO-OPS' : `NOAA NDBC${metadata?.owner ? ` · ${metadata.owner}` : ''}${metadata?.program ? ` · ${metadata.program}` : ''}`;
    return {key, location, stale: reading.stale, mark: {
      id: `station:${key}`, name: `${metadata?.name ?? id} · ${id}${backups.length ? ` (backup for ${backups.join(', ')})` : ''}`,
      kind: provider === 'ndbc' ? 'Observing buoy' : 'Tide prediction station', reading: reading.text,
      source: `${publisher}${location ? '' : ' · location unavailable'}`, basis: STATION_BASIS,
      provider: {href: provider === 'ndbc' ? ndbcStationURL(id) : tidePredictionURL(id), label: `${publisher} station ${id}`},
    }};
  });
}
export const stationGeoJSON = (pins: readonly StationPin[]) => ({type: 'FeatureCollection' as const, features: pins.filter(p => p.location).map(p => ({type: 'Feature' as const, properties: {id: p.key, stale: p.stale, kind: p.location!.provider}, geometry: {type: 'Point' as const, coordinates: [p.location!.longitude, p.location!.latitude]}}))});
