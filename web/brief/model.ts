// Daily brief adapter (FE-31, design § 10 over § 3A.2).
//
// The model is packages/coast `buildDaily`; nothing here re-derives its
// headline, deck, status, windows or missing list.
// - Where a coast report binds (resolveReportBinding: Morro Bay, Cambria),
//   buildCoastBrief maps buildDaily over that report.
// - Elsewhere regionalReport converts SkipperCast's regional feeds (the
//   sampled forecast, the daily feed's buoy, tide and advisory sources) into
//   the same Report shape and buildRegionalBrief runs buildDaily over it, with
//   the local-report line marked unavailable.
// - Tiles keep the latest reading with its clock; past its limit a tile is
//   stale (shown with its age), never silently replaced.
//
// Erasable syntax only: Node tests import this file by type stripping.
import {buildDaily, dateKey, type DailyBrief} from '../../packages/coast/src/daily.ts';
import {resolveReportBinding, type CoastReportContext} from '../../packages/coast/src/state/report-binding.ts';
import type {Alert, Area, County, ForecastHour, Observation, Report, SourceStatus, TideEvent} from '../../packages/coast/src/types.ts';
import {profileSemantics, type Profile} from '../profile.ts';
import {TIDE_UNAVAILABLE, tideTrend} from '../tides.ts';
import type {Brief, BriefBasis, BriefFleet, BriefNotice, BriefTile, LandingReport, RegionalDailyFeed, RegionalForecast, RegionalSource, TileId} from './types.ts';

const HOUR = 3_600_000;
const DAY = 24 * HOUR;
/**
 * How old each tile's clock may be before the tile reads stale. Basis:
 * forecast issue age 18 h (packages/coast freshForecast); nearshore fetch age
 * 3 h (presentation.ts freshNearshore); buoy observation 3 h
 * (freshObservation); tide predictions 36 h (the daily feed's tides
 * max_age_hours).
 */
export const TILE_LIMIT_MS: Readonly<Record<TileId | 'nearshore', number>> = {wind: 18 * HOUR, swell: 18 * HOUR, nearshore: 3 * HOUR, water: 3 * HOUR, tide: 36 * HOUR};
export const FLEET_WINDOW_DAYS = 7;
export const LOCAL_REPORT_LINE = {
  available: 'Local coast report for this area.',
  unavailable: 'Local coast report unavailable here; this brief uses SkipperCast regional feeds.',
} as const;

const finite = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value);
const round = (value: number, digits = 1) => Number(value.toFixed(digits));
const COMPASS = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE', 'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW'];
const compass = (deg: number | null | undefined) => finite(deg) ? COMPASS[Math.round((((deg % 360) + 360) % 360) / 22.5) % 16]! : null;

function tile(id: TileId, label: string, value: number | null, unit: string, detail: string, source: Pick<SourceStatus, 'label' | 'url'> | null, at: string | null, limitMs: number, now: Date): BriefTile {
  const clock = at === null ? NaN : Date.parse(at);
  const ageMs = Number.isFinite(clock) ? now.getTime() - clock : null;
  const state = value === null || ageMs === null ? 'unavailable' : ageMs > limitMs || ageMs < -HOUR ? 'stale' : 'fresh';
  return {id, label, value: value === null ? null : round(value), unit, detail, source: source?.label ?? 'No source', sourceUrl: source?.url ?? null, at: ageMs === null ? null : at, ageMs, limitMs, state};
}

function nearest<T extends {at: string}>(points: readonly T[], at: number): T | undefined {
  let best: T | undefined, gap = Infinity;
  for (const point of points) {
    const d = Math.abs(Date.parse(point.at) - at);
    if (Number.isFinite(d) && d < gap) {best = point; gap = d;}
  }
  return best;
}

export type BriefContext = {report: Report; county: County; area: Area; profile: Profile; now: Date; at?: string; reports?: readonly LandingReport[]; port?: string; tideDatum?: string};

/** Map buildDaily's output to the brief, adding tiles, caveat, notice and fleet line. */
export function briefFromDaily(daily: DailyBrief, basis: BriefBasis, context: BriefContext): Brief {
  const {report, county, area, profile, now} = context;
  const pivot = Date.parse(context.at ?? '') || now.getTime();
  const forecast = report.forecasts.find(item => item.id === area.id);
  const forecastSource = report.sources.find(item => item.id === forecast?.sourceId) ?? null;
  // buildDaily's hours are the fresh ones; a stale forecast still fills the tile so it can read stale.
  const hour: ForecastHour | undefined = daily.hours.find(item => item.at === context.at) ?? nearest(daily.hours, pivot)
    ?? nearest((forecast?.hours ?? []).filter(item => dateKey(item.at, county.timezone) === daily.date), pivot);
  const issued = forecastSource?.issuedAt ?? null;
  const direction = compass(hour?.windDirectionDeg);
  const wind = tile('wind', 'Wind', hour?.windKnots ?? null, 'kt',
    [finite(hour?.gustKnots) ? `gust ${round(hour.gustKnots)} kt` : 'gust unknown', direction ? `from ${direction}` : null].filter(Boolean).join(' · '),
    forecastSource, issued, TILE_LIMIT_MS.wind, now);

  let swell: BriefTile;
  if (profileSemantics(profile).swellTile === 'offshore') {
    const period = hour?.wavePeriodS ?? hour?.swellPeriodS ?? null;
    swell = tile('swell', 'Swell', hour?.waveFt ?? null, 'ft', finite(period) ? `${period} s · offshore forecast` : 'offshore forecast', forecastSource, issued, TILE_LIMIT_MS.swell, now);
  } else {
    const site = (report.nearshore ?? []).filter(item => item.areaId === area.id && item.availability === 'available')
      .sort((a, b) => Date.parse(b.fetchedAt) - Date.parse(a.fetchedAt))[0];
    const point = site && nearest(site.hours.filter(item => finite(item.waveFt)), pivot);
    swell = tile('swell', 'Swell', point?.waveFt ?? null, 'ft', site ? `${finite(point?.periodS) ? `${point.periodS} s · ` : ''}${site.name}` : 'No nearshore model site',
      site ? {label: site.name, url: site.url} : null, site?.fetchedAt ?? null, TILE_LIMIT_MS.nearshore, now);
  }

  const observation = report.observations.filter(item => item.stationId === county.temperatureStationId && finite(item.waterTempF))
    .sort((a, b) => Date.parse(b.observedAt) - Date.parse(a.observedAt))[0];
  const water = tile('water', 'Water', observation?.waterTempF ?? null, '°F', observation ? `buoy ${observation.stationId}` : 'no fresh buoy',
    observation ? {label: `NDBC ${observation.stationId}`, url: observation.url} : null, observation?.observedAt ?? null, TILE_LIMIT_MS.water, now);

  const tideSource = report.sources.find(item => item.kind === 'prediction') ?? null;
  const datum = context.tideDatum ?? 'MLLW';
  const curvePoint = nearest(daily.tides, pivot);
  const nextEvent: TideEvent | undefined = curvePoint ? undefined : [...report.tideEvents].sort((a, b) => Date.parse(a.at) - Date.parse(b.at)).find(item => Date.parse(item.at) >= pivot);
  const tide = tile('tide', 'Tide', curvePoint?.heightFt ?? nextEvent?.heightFt ?? null, 'ft',
    curvePoint ? [tideTrend(daily.tides, pivot), county.tideStation.name, datum].filter(Boolean).join(' · ')
      : nextEvent ? `next ${nextEvent.type === 'H' ? 'high' : 'low'} · ${county.tideStation.name} · ${datum}` : TIDE_UNAVAILABLE,
    tideSource, tideSource?.fetchedAt ?? null, TILE_LIMIT_MS.tide, now);

  return {
    basis, profile, date: daily.date, label: daily.label, provisional: daily.confidence.includes('provisional'),
    headline: daily.headline, deck: daily.summary, status: daily.status, confidence: daily.confidence,
    tiles: [wind, swell, water, tide], windows: daily.windows, caveat: profileSemantics(profile).caveat,
    notice: beachNotice(report, area), fleet: fleetLine(context.reports ?? [], context.port ?? '', county.timezone, now),
    localReport: basis === 'coast-report' ? {available: true, text: LOCAL_REPORT_LINE.available} : {available: false, text: LOCAL_REPORT_LINE.unavailable},
    alerts: daily.alerts, missing: daily.missing, tides: daily.tides, tideEvents: daily.tideEvents, tideDatum: datum, sunrise: daily.sunrise, sunset: daily.sunset,
  };
}

export function beachNotice(report: Report, area: Area): BriefNotice | null {
  const notice = (report.waterQuality ?? []).find(item => item.areaId === area.id && item.advisory);
  return notice?.advisory ? {name: notice.name, advisory: notice.advisory, url: notice.url} : null;
}

/** "3 boats reported from Morro Bay in the last 7 days"; null when none is within the window. */
export function fleetLine(reports: readonly LandingReport[], port: string, timezone: string, now: Date): BriefFleet | null {
  if (!port) return null;
  const today = dateKey(now, timezone), first = dateKey(new Date(now.getTime() - (FLEET_WINDOW_DAYS - 1) * DAY), timezone);
  const boats = new Set(reports.filter(item => item.port === port && item.date >= first && item.date <= today && item.boat).map(item => item.boat));
  if (!boats.size) return null;
  return {count: boats.size, port, text: `${boats.size} boat${boats.size === 1 ? '' : 's'} reported from ${port} in the last ${FLEET_WINDOW_DAYS} days`, href: '/report'};
}

export type CoastBriefInput = {report: Report; county: County; areaId: string; profile: Profile; date: string; now: Date; at?: string; reports?: readonly LandingReport[]; port?: string};

/** The bound brief: buildDaily over the coast report, mapped without change. */
export function buildCoastBrief(input: CoastBriefInput): Brief {
  const area = input.county.areas.find(item => item.id === input.areaId);
  if (!area) throw new RangeError(`No coast area ${input.areaId}`);
  const daily = buildDaily(input.report, input.county, area, input.profile, input.date, input.now);
  return briefFromDaily(daily, 'coast-report', {...input, area});
}

export type RegionalPlace = {id: string; name: string; lat: number; lon: number; timezone: string; port?: string};

const M_TO_FT = 3.280839895, MS_TO_KT = 1.943844492;
const num = (value: unknown, scale = 1): number | null => finite(value) ? value * scale : null;
const sourceOk = (source: RegionalSource | undefined) => source?.status === 'ok' || source?.status === 'retained';

/** Convert SkipperCast's regional feeds to the coast Report shape so buildDaily runs unchanged. */
export function regionalReport(daily: RegionalDailyFeed, forecast: RegionalForecast | null, place: RegionalPlace): {report: Report; county: County; area: Area; tideDatum: string} {
  const entries = Object.values(daily.sources).filter((item): item is RegionalSource => !!item);
  const buoy = entries.find(item => item.kind === 'observation' && typeof item.data?.station === 'string');
  const tides = daily.sources.tides;
  const advisories = entries.filter(item => item.kind === 'advisory');
  const station = (buoy?.data?.station as string | undefined) ?? '';
  const observations: Observation[] = ((buoy?.data?.observations as Record<string, unknown>[] | undefined) ?? []).map(row => ({
    stationId: station, observedAt: String(row.time), url: buoy!.url,
    waveFt: num(row.WVHT, M_TO_FT), wavePeriodS: num(row.DPD), waterTempF: finite(row.WTMP) ? row.WTMP * 9 / 5 + 32 : null,
    windKnots: num(row.WSPD, MS_TO_KT), gustKnots: num(row.GST, MS_TO_KT), directionDeg: num(row.MWD),
  }));
  const tideEvents: TideEvent[] = ((tides?.data?.predictions as Record<string, unknown>[] | undefined) ?? [])
    .filter(row => finite(row.height_ft) && (row.type === 'H' || row.type === 'L'))
    .map(row => ({at: String(row.time), heightFt: row.height_ft as number, type: row.type as 'H' | 'L'}));
  const alerts: Alert[] = advisories.flatMap(source => ((source.data?.alerts as Record<string, unknown>[] | undefined) ?? []).map(row => ({
    id: String(row.id), event: String(row.event), headline: String(row.headline ?? row.event), description: '',
    effective: typeof row.effective === 'string' ? row.effective : null, expires: typeof (row.ends ?? row.expires) === 'string' ? String(row.ends ?? row.expires) : null, url: source.url,
  })));
  const alertCheck = advisories.length ? advisories.reduce((a, b) => Date.parse(a.checked_at) <= Date.parse(b.checked_at) ? a : b) : undefined;
  const sources: SourceStatus[] = [];
  if (forecast) sources.push({id: 'regional-forecast', label: forecast.label, url: forecast.url, kind: 'forecast', outcome: 'ok', fetchedAt: forecast.fetchedAt, issuedAt: forecast.issuedAt});
  if (buoy) sources.push({id: buoy.id, label: buoy.name, url: buoy.url, kind: 'observation', outcome: sourceOk(buoy) ? 'ok' : 'error', fetchedAt: buoy.checked_at});
  if (tides) sources.push({id: tides.id, label: tides.name, url: tides.url, kind: 'prediction', outcome: sourceOk(tides) ? 'ok' : 'error', fetchedAt: tides.checked_at});
  // The oldest advisory check stands for all: buildDaily withholds windows unless it is fresh.
  if (alertCheck) sources.push({id: 'nws-alerts', label: alertCheck.name, url: alertCheck.url, kind: 'forecast', outcome: advisories.every(sourceOk) ? 'ok' : 'error', fetchedAt: alertCheck.checked_at});
  const area: Area = {id: place.id, name: place.name, coast: place.name, mapLabel: place.name, lat: place.lat, lon: place.lon, landLat: place.lat, landLon: place.lon,
    modes: ['boat', 'shore', 'spear'], exposure: '', accessNote: '', targets: {boat: [], shore: [], spear: []}, waterQualityUrl: ''};
  const county: County = {id: daily.region_id, name: place.name, shortName: place.name, brand: 'SkipperCast', brandPrefix: '', defaultAreaId: place.id,
    temperatureStationId: station, domain: '', timezone: place.timezone, center: [place.lon, place.lat], bounds: [[place.lon, place.lat], [place.lon, place.lat]], areas: [area],
    tideStation: {id: String(tides?.data?.station ?? ''), name: tides?.name ?? 'Tide station', url: tides?.url ?? '', note: String(tides?.data?.note ?? '')},
    buoys: [], ruleLinks: [], catchLinks: []};
  const report: Report = {schemaVersion: 1, countyId: daily.region_id, generatedAt: forecast?.fetchedAt ?? alertCheck?.checked_at ?? new Date(0).toISOString(),
    forecasts: forecast ? [{id: place.id, hours: [...forecast.hours], sourceId: 'regional-forecast', issuedAt: forecast.issuedAt}] : [],
    observations, tides: [], tideEvents, alerts, sources, catches: [], catchStatus: 'unavailable',
    visibility: {status: 'unknown', feet: null, observedAt: null, sourceUrl: null}, habitatStatus: 'unavailable'};
  return {report, county, area, tideDatum: String(tides?.data?.datum ?? 'MLLW')};
}

export type RegionalBriefInput = {daily: RegionalDailyFeed; forecast: RegionalForecast | null; place: RegionalPlace; profile: Profile; date: string; now: Date; at?: string};

/** The regional brief: buildDaily over the converted regional feeds; the local-report line is unavailable. */
export function buildRegionalBrief(input: RegionalBriefInput): Brief {
  const {report, county, area, tideDatum} = regionalReport(input.daily, input.forecast, input.place);
  const daily = buildDaily(report, county, area, input.profile, input.date, input.now);
  return briefFromDaily(daily, 'regional', {report, county, area, profile: input.profile, now: input.now, at: input.at, reports: input.daily.reports ?? [], port: input.place.port, tideDatum});
}

export type BriefInput = {
  /** The place context (web/overview-context.ts overviewReportContext). */
  context: CoastReportContext;
  /** The admitted coast report (web/coast-data.ts), or null when none is loaded. */
  coast: {report: Report; county: County} | null;
  regional: {daily: RegionalDailyFeed; forecast: RegionalForecast | null; place: RegionalPlace};
  profile: Profile; date: string; now: Date; at?: string;
};

/** The coast report only where resolveReportBinding binds the place and a report is loaded; the regional brief elsewhere. */
export function buildBrief(input: BriefInput): Brief {
  const {profile, date, now, at, regional} = input;
  const binding = input.coast ? resolveReportBinding(input.context) : null;
  if (input.coast && binding) return buildCoastBrief({...input.coast, areaId: binding.areaId, profile, date, now, at, reports: regional.daily.reports ?? [], port: regional.place.port});
  return buildRegionalBrief({...regional, profile, date, now, at});
}
