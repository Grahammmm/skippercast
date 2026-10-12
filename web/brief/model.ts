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
import type {ComfortLimits} from '../../packages/coast/src/limits.ts';
import {resolveReportBinding, type CoastReportContext} from '../../packages/coast/src/state/report-binding.ts';
import type {Alert, Area, ChlorophyllReading, County, ForecastHour, Observation, Report, SourceStatus, TideEvent} from '../../packages/coast/src/types.ts';
import {profileSemantics, type Profile} from '../profile.ts';
import {TIDE_UNAVAILABLE, tideTrend} from '../tides.ts';
import {ndbcStationURL, sourceStation, stationText, tidePredictionURL} from '../station-label.ts';
import {ageText} from '../confidence.ts';
import type {Brief, BriefBasis, BriefFleet, BriefNotice, BriefTile, LandingReport, SourceGap, RegionalDailyFeed, RegionalForecast, RegionalSource, TileId} from './types.ts';

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

function tile(id: TileId, label: string, value: number | null, unit: string, detail: string, source: Pick<SourceStatus, 'label' | 'url'> | null, at: string | null, limitMs: number, now: Date, lastGood = false): BriefTile {
  const clock = at === null ? NaN : Date.parse(at);
  const ageMs = Number.isFinite(clock) ? now.getTime() - clock : null;
  const state = value === null || ageMs === null ? 'unavailable' : lastGood || ageMs > limitMs || ageMs < -HOUR ? 'stale' : 'fresh';
  return {id, label, value: value === null ? null : round(value), unit, detail, source: source?.label ?? 'No source', sourceUrl: source?.url ?? null, at: ageMs === null ? null : at, ageMs, limitMs, state,
    ...(lastGood && state === 'stale' ? {lastGood: true} : {})};
}

function nearest<T extends {at: string}>(points: readonly T[], at: number): T | undefined {
  let best: T | undefined, gap = Infinity;
  for (const point of points) {
    const d = Math.abs(Date.parse(point.at) - at);
    if (Number.isFinite(d) && d < gap) {best = point; gap = d;}
  }
  return best;
}

export type BriefContext = {report: Report; county: County; area: Area; profile: Profile; now: Date; at?: string; reports?: readonly LandingReport[]; port?: string | readonly string[]; tideDatum?: string;
  /** The primary buoy's id when the regional feed's buoy reading came from a backup station (#554). */
  buoyBackupFor?: string | null;
  /** The feed sources behind the brief that are not ok (sourceGaps); none when absent. */
  gaps?: readonly SourceGap[]};

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
  // Shore adds the surf, wind side and tide phase of the selected hour (packages/coast shore-conditions.ts).
  const shoreHour = daily.shore && hour ? daily.shore.hours.find(item => item.at === hour.at) : undefined;
  // Boat at a regulated bar adds the hour's ebb and bar band to the tide tile (packages/coast bar-conditions.ts).
  const barHour = daily.bar && hour ? daily.bar.hours.find(item => item.at === hour.at) : undefined;
  const barText = barHour ? [barHour.tide.midEbb ? 'mid-ebb' : barHour.tide.stage, `${barHour.band === 'No bar flag' ? '' : 'bar '}${barHour.band.toLowerCase()} (estimate)`].filter(Boolean).join(' · ') : null;
  // Kayak adds the wind band and side, seas band, chop and launch surf of the selected hour (packages/coast kayak.ts).
  const kayakHour = daily.kayak && hour ? daily.kayak.hours.find(item => item.at === hour.at) : undefined;
  const kayakWind = kayakHour && kayakHour.wind.band !== 'Unknown' ? `${kayakHour.wind.band.toLowerCase()}${kayakHour.wind.side ? ` ${kayakHour.wind.side}` : ''}` : null;
  const wind = tile('wind', 'Wind', hour?.windKnots ?? null, 'kt',
    [finite(hour?.gustKnots) ? `gust ${round(hour.gustKnots)} kt` : 'gust unknown', direction ? `from ${direction}` : null, shoreHour?.wind.side ?? kayakWind].filter(Boolean).join(' · '),
    forecastSource, issued, TILE_LIMIT_MS.wind, now);

  let swell: BriefTile;
  if (profileSemantics(profile).swellTile === 'offshore') {
    const period = hour?.wavePeriodS ?? hour?.swellPeriodS ?? null;
    const kayakSeas = kayakHour && kayakHour.seas.band !== 'Unknown'
      ? ` · ${kayakHour.seas.band.toLowerCase()} seas${kayakHour.seas.chop ? ' · short-period chop' : ''}${kayakHour.launchCaution ? ` · surf at the launch${kayakHour.launch.basis === 'offshore' ? ' (offshore estimate)' : ''}` : ''}` : '';
    swell = tile('swell', 'Swell', hour?.waveFt ?? null, 'ft', (finite(period) ? `${period} s · offshore forecast` : 'offshore forecast') + kayakSeas, forecastSource, issued, TILE_LIMIT_MS.swell, now);
  } else {
    const site = (report.nearshore ?? []).filter(item => item.areaId === area.id && item.availability === 'available')
      .sort((a, b) => Date.parse(b.fetchedAt) - Date.parse(a.fetchedAt))[0];
    const point = site && nearest(site.hours.filter(item => finite(item.waveFt)), pivot);
    // Spear adds the surge band of the selected hour (packages/coast spear.ts).
    const surgeHour = daily.spear && hour ? daily.spear.hours.find(item => item.at === hour.at) : undefined;
    const surge = surgeHour && surgeHour.surge.band !== 'Unknown' ? ` · ${surgeHour.surge.band.toLowerCase()} surge` : '';
    const surf = shoreHour && shoreHour.surf.band !== 'Unknown'
      ? ` · ${shoreHour.surf.band.toLowerCase()} surf${shoreHour.surf.basis === 'offshore' ? ' (offshore estimate)' : ''}${shoreHour.surf.sneaker ? ' · long-period swell' : ''}` : '';
    swell = tile('swell', 'Swell', point?.waveFt ?? null, 'ft', (site ? `${finite(point?.periodS) ? `${point.periodS} s · ` : ''}${site.name}` : 'No nearshore model site') + surge + surf,
      site ? {label: site.name, url: site.url} : null, site?.fetchedAt ?? null, TILE_LIMIT_MS.nearshore, now);
  }

  const observation = report.observations.filter(item => item.stationId === county.temperatureStationId && finite(item.waterTempF))
    .sort((a, b) => Date.parse(b.observedAt) - Date.parse(a.observedAt))[0];
  const buoyName = observation ? stationText({id: observation.stationId, backupFor: context.buoyBackupFor ?? null}) : '';
  const water = tile('water', 'Water', observation?.waterTempF ?? null, '°F', observation ? `buoy ${buoyName}` : 'no fresh buoy',
    observation ? {label: `NDBC ${buoyName}`, url: observation.url} : null, observation?.observedAt ?? null, TILE_LIMIT_MS.water, now,
    !!observation && report.sources.some(item => item.kind === 'observation' && item.url === observation.url && item.outcome === 'error'));

  const tideSource = report.sources.find(item => item.kind === 'prediction') ?? null;
  const datum = context.tideDatum ?? 'MLLW';
  const curvePoint = nearest(daily.tides, pivot);
  const nextEvent: TideEvent | undefined = curvePoint ? undefined : [...report.tideEvents].sort((a, b) => Date.parse(a.at) - Date.parse(b.at)).find(item => Date.parse(item.at) >= pivot);
  const tide = tile('tide', 'Tide', curvePoint?.heightFt ?? nextEvent?.heightFt ?? null, 'ft',
    curvePoint ? [tideTrend(daily.tides, pivot), shoreHour?.tide.veryLow ? 'very low' : null, barText, county.tideStation.name, datum].filter(Boolean).join(' · ')
      : nextEvent ? [`next ${nextEvent.type === 'H' ? 'high' : 'low'}`, barText, county.tideStation.name, datum].filter(Boolean).join(' · ') : TIDE_UNAVAILABLE,
    tideSource, tideSource?.fetchedAt ?? null, TILE_LIMIT_MS.tide, now, tideSource?.outcome === 'error');

  return {
    basis, profile, date: daily.date, label: daily.label, provisional: daily.confidence.includes('provisional'),
    headline: daily.headline, deck: daily.summary, status: daily.status, confidence: daily.confidence,
    tiles: [wind, swell, water, tide], windows: daily.windows, caveat: profileSemantics(profile).caveat,
    notice: beachNotice(report, area, now), fleet: fleetLine(context.reports ?? [], context.port ?? [], county.timezone, now),
    localReport: basis === 'coast-report' ? {available: true, text: LOCAL_REPORT_LINE.available} : {available: false, text: LOCAL_REPORT_LINE.unavailable},
    spear: daily.spear, shore: daily.shore, bar: daily.bar, kayak: daily.kayak, limits: daily.limits, alerts: daily.alerts, missing: daily.missing, gaps: context.gaps ?? [], tides: daily.tides, tideEvents: daily.tideEvents, tideDatum: datum, sunrise: daily.sunrise, sunset: daily.sunset,
  };
}

/** The county beach-health source the notice reads (packages/coast enrichment). */
export const BEACH_HEALTH_SOURCE = 'slo-beach-water-quality';
/** A published status that is a notice; "Beach Open" is not. The v1 rule (packages/coast presentation.ts reportPanel, ui/briefing.ts). */
export const BEACH_NOTICE_STATUS = /advisory|closed|warning/i;
const BEACH_HEALTH_MAX_AGE_MS = 3 * HOUR, BEACH_HEALTH_SKEW_MS = 5 * 60_000;

/**
 * The area's first beach under an advisory, closure or warning, decided as v1 does: from the
 * status, and only while the county source fetched cleanly within 3 h. The advisory text is not
 * the test: the county writes one for open beaches too ("There are no advisory notes at this time.").
 */
export function beachNotice(report: Report, area: Area, now: Date): BriefNotice | null {
  const health = report.sources.find(item => item.id === BEACH_HEALTH_SOURCE);
  const age = health ? now.getTime() - Date.parse(health.fetchedAt) : NaN;
  if (health?.outcome !== 'ok' || !(age >= -BEACH_HEALTH_SKEW_MS && age < BEACH_HEALTH_MAX_AGE_MS)) return null;
  const notice = (report.waterQuality ?? []).find(item => item.areaId === area.id && BEACH_NOTICE_STATUS.test(item.status));
  return notice ? {name: notice.name, advisory: notice.advisory ?? notice.status, url: notice.url} : null;
}

/**
 * A trip's port is one of `names` when it equals a name or starts with it as whole words: the
 * region's landing names are short ("Avila") where the publisher's port is longer ("Avila Beach").
 */
const atPort = (port: unknown, names: readonly string[]): port is string =>
  typeof port === 'string' && names.some(name => port === name || port.startsWith(name + ' '));

/**
 * "3 boats reported from Morro Bay & Avila Beach in the last 7 days"; null when none is within the
 * window. `ports` is one port or the region's landing names (the daily feed's `landing_names`):
 * every region's feed carries the same publisher's trips, so only those at its own landings count.
 */
export function fleetLine(reports: readonly LandingReport[], ports: string | readonly string[], timezone: string, now: Date): BriefFleet | null {
  const names = (typeof ports === 'string' ? [ports] : ports).filter(Boolean);
  if (!names.length) return null;
  const today = dateKey(now, timezone), first = dateKey(new Date(now.getTime() - (FLEET_WINDOW_DAYS - 1) * DAY), timezone);
  const trips = reports.filter(item => atPort(item.port, names) && item.date >= first && item.date <= today && item.boat);
  const boats = new Set(trips.map(item => item.boat));
  if (!boats.size) return null;
  // The ports that reported, in the order of the region's landing names.
  const rank = (port: string) => names.findIndex(name => atPort(port, [name]));
  const port = [...new Set(trips.map(item => item.port))].sort((a, b) => rank(a) - rank(b)).join(' & ');
  return {count: boats.size, port, text: `${boats.size} boat${boats.size === 1 ? '' : 's'} reported from ${port} in the last ${FLEET_WINDOW_DAYS} days`, href: '/report'};
}

/**
 * Cells within this many degrees (about 15 km) of the place feed its chlorophyll reading.
 * The grid is about 4 km (0.0375°) and the satellite masks most cells against the
 * shore, so a tighter radius would often find none. The clarity estimate says the
 * value is an offshore area average that may read clearer than the shoreline.
 */
export const CHLOROPHYLL_RADIUS_DEG = 0.15;

/**
 * The daily feed's satellite chlorophyll near a point: the median of valid
 * cells within CHLOROPHYLL_RADIUS_DEG, or null when the grid is missing,
 * failed or has no valid cell nearby. Gaps stay gaps; nothing is filled.
 */
export function chlorophyllNear(daily: RegionalDailyFeed | null | undefined, lat: number, lon: number): ChlorophyllReading | null {
  const source = daily?.sources.chlorophyll;
  const data = source?.data;
  if (!source || !sourceOk(source) || !data || typeof data.sample_at !== 'string') return null;
  const values = ((data.samples as Record<string, unknown>[] | undefined) ?? [])
    .filter(row => finite(row.chlorophyll) && finite(row.latitude) && finite(row.longitude)
      && Math.hypot((row.latitude as number) - lat, ((row.longitude as number) - lon) * Math.cos(lat * Math.PI / 180)) <= CHLOROPHYLL_RADIUS_DEG)
    .map(row => row.chlorophyll as number).sort((a, b) => a - b);
  if (!values.length) return null;
  const mid = Math.floor(values.length / 2);
  const median = values.length % 2 ? values[mid]! : (values[mid - 1]! + values[mid]!) / 2;
  return {mgM3: median, sampleAt: data.sample_at, cells: values.length, label: source.name, url: source.url};
}

export type CoastBriefInput = {report: Report; county: County; areaId: string; profile: Profile; date: string; now: Date; at?: string; reports?: readonly LandingReport[]; port?: string | readonly string[];
  /** The region's daily feed, read for satellite chlorophyll near the area. */
  daily?: RegionalDailyFeed;
  /** The user's own comfort limits for the profile (web/limits.ts); the defaults when absent. */
  limits?: ComfortLimits | null};

/** The bound brief: buildDaily over the coast report (with the feed's chlorophyll near the area), mapped without change. */
export function buildCoastBrief(input: CoastBriefInput): Brief {
  const area = input.county.areas.find(item => item.id === input.areaId);
  if (!area) throw new RangeError(`No coast area ${input.areaId}`);
  const chlorophyll = chlorophyllNear(input.daily, area.lat, area.lon);
  const report = chlorophyll ? {...input.report, chlorophyll} : input.report;
  const daily = buildDaily(report, input.county, area, input.profile, input.date, input.now, input.limits);
  return briefFromDaily(daily, 'coast-report', {...input, report, area, gaps: reportGaps(report, input.now)});
}

export type RegionalPlace = {id: string; name: string; lat: number; lon: number; timezone: string; port?: string};

const M_TO_FT = 3.280839895, MS_TO_KT = 1.943844492;
const num = (value: unknown, scale = 1): number | null => finite(value) ? value * scale : null;
// Only ok is ok: a retained source is last good data after a failed check, so it reads as an error
// whose clock is that last good fetch.
const sourceOk = (source: RegionalSource | undefined) => source?.status === 'ok';
const sourceClock = (source: RegionalSource) => source.status === 'retained' ? source.data_retrieved_at ?? source.last_success_at ?? source.checked_at : source.checked_at;

/** Convert SkipperCast's regional feeds to the coast Report shape so buildDaily runs unchanged. */
export function regionalReport(daily: RegionalDailyFeed, forecast: RegionalForecast | null, place: RegionalPlace): {report: Report; county: County; area: Area; tideDatum: string; buoyBackupFor: string | null} {
  const entries = Object.values(daily.sources).filter((item): item is RegionalSource => !!item);
  const buoy = entries.find(item => item.kind === 'observation' && typeof item.data?.station === 'string');
  const tides = daily.sources.tides;
  const advisories = entries.filter(item => item.kind === 'advisory');
  // A backup (#554) is named by its own station, "backup for" the primary, and links to its own official page;
  // without the fields, names and links stay as the feed gave them.
  const buoyStation = sourceStation(buoy, buoy?.data?.station as string | undefined);
  const station = buoyStation?.backupFor ? buoyStation.id : (buoy?.data?.station as string | undefined) ?? '';
  const buoyUrl = buoyStation?.backupFor ? ndbcStationURL(buoyStation.id) : buoy?.url ?? '';
  const tideStation = sourceStation(tides, tides?.data?.station as string | undefined);
  const tideBackup = tideStation?.backupFor ? tideStation : null;
  const tideName = tideBackup ? `NOAA ${stationText(tideBackup)}` : tides?.name;
  const tideUrl = tideBackup ? tidePredictionURL(tideBackup.id) : tides?.url;
  const observations: Observation[] = ((buoy?.data?.observations as Record<string, unknown>[] | undefined) ?? []).map(row => ({
    stationId: station, observedAt: String(row.time), url: buoyUrl,
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
  if (buoy) sources.push({id: buoy.id, label: buoyStation?.backupFor ? `NDBC ${stationText(buoyStation)}` : buoy.name, url: buoyUrl, kind: 'observation', outcome: sourceOk(buoy) ? 'ok' : 'error', fetchedAt: sourceClock(buoy)});
  if (tides) sources.push({id: tides.id, label: tideName ?? tides.name, url: tideUrl ?? tides.url, kind: 'prediction', outcome: sourceOk(tides) ? 'ok' : 'error', fetchedAt: sourceClock(tides)});
  // The oldest advisory check stands for all: buildDaily withholds windows unless it is fresh.
  if (alertCheck) sources.push({id: 'nws-alerts', label: alertCheck.name, url: alertCheck.url, kind: 'forecast', outcome: advisories.every(sourceOk) ? 'ok' : 'error', fetchedAt: alertCheck.checked_at});
  const area: Area = {id: place.id, name: place.name, coast: place.name, mapLabel: place.name, lat: place.lat, lon: place.lon, landLat: place.lat, landLon: place.lon,
    modes: ['boat', 'shore', 'spear'], exposure: '', accessNote: '', targets: {boat: [], shore: [], spear: []}, waterQualityUrl: ''};
  const county: County = {id: daily.region_id, name: place.name, shortName: place.name, brand: 'SkipperCast', brandPrefix: '', defaultAreaId: place.id,
    temperatureStationId: station, domain: '', timezone: place.timezone, center: [place.lon, place.lat], bounds: [[place.lon, place.lat], [place.lon, place.lat]], areas: [area],
    tideStation: {id: String(tides?.data?.station ?? ''), name: tideName ?? 'Tide station', url: tideUrl ?? '', note: String(tides?.data?.note ?? '')},
    buoys: [], ruleLinks: [], catchLinks: []};
  const report: Report = {schemaVersion: 1, countyId: daily.region_id, generatedAt: forecast?.fetchedAt ?? alertCheck?.checked_at ?? new Date(0).toISOString(),
    forecasts: forecast ? [{id: place.id, hours: [...forecast.hours], sourceId: 'regional-forecast', issuedAt: forecast.issuedAt}] : [],
    observations, tides: [], tideEvents, alerts, sources, catches: [], catchStatus: 'unavailable',
    visibility: {status: 'unknown', feet: null, observedAt: null, sourceUrl: null}, habitatStatus: 'unavailable', chlorophyll: chlorophyllNear(daily, place.lat, place.lon)};
  return {report, county, area, tideDatum: String(tides?.data?.datum ?? 'MLLW'), buoyBackupFor: buoyStation?.backupFor ?? null};
}

export type RegionalBriefInput = {daily: RegionalDailyFeed; forecast: RegionalForecast | null; place: RegionalPlace; profile: Profile; date: string; now: Date; at?: string; limits?: ComfortLimits | null};

/** The regional brief: buildDaily over the converted regional feeds; the local-report line is unavailable. */
export function buildRegionalBrief(input: RegionalBriefInput): Brief {
  const {report, county, area, tideDatum, buoyBackupFor} = regionalReport(input.daily, input.forecast, input.place);
  const daily = buildDaily(report, county, area, input.profile, input.date, input.now, input.limits);
  return briefFromDaily(daily, 'regional', {report, county, area, profile: input.profile, now: input.now, at: input.at, reports: input.daily.reports ?? [], port: input.daily.landing_names ?? input.place.port, tideDatum, buoyBackupFor,
    gaps: sourceGaps(input.daily, input.now)});
}

/** The station a feed source reads: its configured station, its data's, else the NDBC file its URL names. */
function stationOf(source: RegionalSource): string {
  const data = typeof source.data?.station === 'string' ? source.data.station : null;
  return source.station ?? data ?? source.url.match(/\/([A-Za-z0-9]+)\.(?:txt|spec)$/)?.[1] ?? source.id;
}

/**
 * The data's own clock, as failover.py data_age reads it: a buoy's newest row, the data's sample or
 * issue time, or a prediction's coverage end. Retrieval time only when the data carries no clock,
 * and then said as such.
 */
function dataClock(source: RegionalSource): {at: string; what: 'reading' | 'issued' | 'ended' | 'retrieved'} | null {
  const data = source.data ?? {};
  const rows = data.observations;
  const times = Array.isArray(rows) ? rows.map(row => Date.parse(String((row as {time?: unknown})?.time))).filter(Number.isFinite) : [];
  if (times.length) return {at: new Date(Math.max(...times)).toISOString(), what: 'reading'};
  if (typeof data.sample_at === 'string') return {at: data.sample_at, what: 'reading'};
  if (typeof data.issued_at === 'string') return {at: data.issued_at, what: 'issued'};
  if (typeof data.coverage_end === 'string') return {at: data.coverage_end, what: 'ended'};
  const retrieved = source.data_retrieved_at ?? source.last_success_at;
  return retrieved ? {at: retrieved, what: 'retrieved'} : null;
}

function clockText(source: RegionalSource, now: Date): string | null {
  const clock = dataClock(source);
  const ms = clock ? now.getTime() - Date.parse(clock.at) : NaN;
  if (!clock || !Number.isFinite(ms)) return null;
  if (clock.what === 'ended') return ms >= 0 ? `coverage ended ${ageText(ms)} ago` : `coverage runs ${ageText(-ms)} more`;
  return clock.what === 'reading' ? `newest reading ${ageText(ms)} old` : `${clock.what} ${ageText(ms)} ago`;
}

function feedGap(source: RegionalSource, now: Date): SourceGap {
  const station = sourceStation(source);
  const label = station?.backupFor ? `${source.kind === 'prediction' ? 'NOAA' : 'NDBC'} ${stationText(station)}` : source.name;
  const clock = clockText(source, now);
  const text = source.status === 'stale' ? `stale${clock ? `, ${clock}` : ''}`
    : source.status === 'retained' ? `latest check failed; showing the last good data${clock ? `, ${clock}` : ''}`
    : source.status === 'failed' ? 'latest check failed; nothing earlier on hand'
    : source.status === 'missing' ? 'not published in this feed'
    : source.status;
  return {id: source.id, label, status: source.status, text: `${label}: ${text}.`};
}

/**
 * The regional brief's sources that are not ok, one line per station, named by the station it
 * describes and why: stale or retained with the data's own age, failed with nothing on hand, or
 * missing from the feed. Only what the tiles and windows read: the water buoy (the feed's first
 * observation source, as regionalReport picks it, with its spectrum and the daily copy folded into
 * the same station), the tide predictions and the marine alert checks. A station any copy of
 * which is ok is no gap, and a backup serving ok is none either; its tile already names it.
 */
export function sourceGaps(feed: RegionalDailyFeed, now: Date): SourceGap[] {
  const entries = Object.values(feed.sources).filter((item): item is RegionalSource => !!item);
  const first = entries.find(item => item.kind === 'observation');
  const buoyStation = first ? stationOf(first) : null;
  const read = entries.filter(item => (item.kind === 'observation' && stationOf(item) === buoyStation) || item === feed.sources.tides || item.kind === 'advisory');
  const groups = new Map<string, RegionalSource[]>();
  for (const item of read) {
    const key = item.kind === 'advisory' ? `advisory:${item.url || item.id}` : `${item.kind}:${stationOf(item)}`;
    groups.set(key, [...(groups.get(key) ?? []), item]);
  }
  return [...groups.values()].filter(copies => copies.every(item => item.status !== 'ok')).map(copies => feedGap(copies[0]!, now));
}

/**
 * The coast report's sources whose latest check failed. The report keeps no stale or retained
 * status, only the outcome and when it was fetched, so the line says exactly that.
 */
export function reportGaps(report: Report, now: Date): SourceGap[] {
  return report.sources.filter(item => item.outcome === 'error').map(item => {
    const ms = now.getTime() - Date.parse(item.fetchedAt);
    const when = Number.isFinite(ms) ? `; last fetched ${ageText(ms)} ago` : '';
    return {id: item.id, label: item.label, status: 'failed', text: `${item.label}: latest check failed${when}.`};
  });
}

export type BriefInput = {
  /** The place context (web/overview-context.ts overviewReportContext). */
  context: CoastReportContext;
  /** The admitted coast report (web/coast-data.ts), or null when none is loaded. */
  coast: {report: Report; county: County} | null;
  regional: {daily: RegionalDailyFeed; forecast: RegionalForecast | null; place: RegionalPlace};
  profile: Profile; date: string; now: Date; at?: string;
  limits?: ComfortLimits | null;
};

/** The coast report only where resolveReportBinding binds the place and a report is loaded; the regional brief elsewhere. */
export function buildBrief(input: BriefInput): Brief {
  const {profile, date, now, at, regional, limits} = input;
  const binding = input.coast ? resolveReportBinding(input.context) : null;
  if (input.coast && binding) return buildCoastBrief({...input.coast, areaId: binding.areaId, profile, date, now, at, reports: regional.daily.reports ?? [], port: regional.daily.landing_names ?? regional.place.port, daily: regional.daily, limits});
  return buildRegionalBrief({...regional, profile, date, now, at, limits});
}
