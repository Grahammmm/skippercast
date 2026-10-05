// GET /api/admin/fleet/ais/health?region= — the AIS listener's health for the admin
// (docs/plans/charter-fleet/design.md § 10, § 11, § 13 AIS health, US-O3; CF-35). Read from D1:
//
//   job_state fleet.ais.<region>.heartbeat   the listener's heartbeat (src/skippercast/fleet/ais/listener.py)
//                                            as the processor pushes it (CF-45): last_message_at, written_at,
//                                            connected, messages_per_min, watched_messages_per_min, watch_size,
//                                            source, git_sha are read; updated_at is the push time.
//                                            Ages are whole seconds, floored (as fleet/activity.ts)
//   job_state fleet.ais.<region>.processed   set by each processor run ({at, run_id, counts}); its
//                                            updated_at is the last run
//   fleet_ais_hours                          counters per region and UTC hour; the hour stamp
//                                            ('2026-10-05T09:00:00.000Z' or '2026-10-05T09') is cut to the hour
//   fleet_ais_watch                          the watch list (watched and candidate MMSIs)
//
// Windows are whole UTC hours ending at the start of the current hour. An hour is up when its
// counters show at least one message; a missing hour is down (the listener reported nothing).
// Uptime is up hours over the window's hours. Gaps are up hours whose longest silence (max_gap_s)
// exceeds 10 minutes, over the last 7 days; down hours are listed as outages (runs of hours) instead.
// Without ?region= every region with counters, a heartbeat or a watch list is reported.

const REGION = /^[A-Za-z0-9](?:[A-Za-z0-9-]{0,62}[A-Za-z0-9])?$/;
const HOUR_MS = 3_600_000;
export const GAP_S = 600;            // gaps over 10 minutes
export const STALE_S = 3 * 3600;     // the fleet-health threshold (CF-45): no message for 3 h
const GAP_DAYS = 7;
const MAX_REGIONS = 20;

export interface HourRow {hour: string; messages: number; watched_messages: number; vessels: number; reconnects: number; max_gap_s: number; dropped: number}
export interface Uptime {pct: number | null; up_hours: number; hours: number}
export interface RegionHealth {
  region: string;
  heartbeat: {written_at: string | null; pushed_at: string; age_s: number | null; connected: boolean | null; source: string | null; git_sha: string | null} | null;
  heartbeat_unreadable: boolean;
  last_message_at: string | null; last_message_age_s: number | null; stale: boolean;
  messages_per_min: number | null; watched_messages_per_min: number | null;
  last_24h: {messages: number; reconnects: number; dropped: number; hours_reported: number};
  hours_24: (HourRow & {missing: boolean})[];
  gaps: {hour: string; max_gap_s: number}[];
  outages: {from: string; to: string; hours: number}[];
  uptime: {d7: Uptime; d30: Uptime};
  processor: {last_run_at: string; age_s: number} | null;
  watch: {watched: number; candidates: number; listener: number | null};
}
export interface AisHealthReport {checked_at: string; gap_s: number; stale_s: number; regions: RegionHealth[]}

/** Parse ?region=; an error string for an invalid one. */
export function healthQuery(region: string | undefined): {region: string | null} | {error: string} {
  if (region && !REGION.test(region)) return {error: 'invalid region'};
  return {region: region || null};
}

/** The UTC hour key ('YYYY-MM-DDTHH') of an epoch ms. */
export const hourKey = (ms: number): string => new Date(ms).toISOString().slice(0, 13);
const ageS = (iso: unknown, now: number): number | null => {
  if (typeof iso !== 'string') return null;
  const t = Date.parse(iso);
  return Number.isFinite(t) ? Math.max(0, Math.floor((now - t) / 1000)) : null;
};
const num = (v: unknown): number | null => typeof v === 'number' && Number.isFinite(v) ? v : null;
const str = (v: unknown): string | null => typeof v === 'string' ? v : null;
const uptime = (up: Set<string>, start: number, hours: number): Uptime => {
  let n = 0;
  for (let i = 0; i < hours; i++) if (up.has(hourKey(start + i * HOUR_MS))) n++;
  return {pct: hours ? Math.round(1000 * n / hours) / 10 : null, up_hours: n, hours};
};

async function regionHealth(db: D1Database, region: string, now: number): Promise<RegionHealth> {
  const end = Math.floor(now / HOUR_MS) * HOUR_MS;                     // start of the current hour (excluded)
  const from30 = end - 30 * 24 * HOUR_MS, from7 = end - GAP_DAYS * 24 * HOUR_MS, from24 = end - 24 * HOUR_MS;
  const [rows, beat, processed, watch] = await Promise.all([
    db.prepare(`SELECT substr(hour,1,13) AS hour,messages,watched_messages,vessels,reconnects,max_gap_s,dropped FROM fleet_ais_hours
      WHERE region=? AND substr(hour,1,13)>=? AND substr(hour,1,13)<? ORDER BY hour`).bind(region, hourKey(from30), hourKey(end)).all<HourRow>(),
    db.prepare('SELECT value,updated_at FROM job_state WHERE key=?').bind(`fleet.ais.${region}.heartbeat`).first<{value: string; updated_at: string}>(),
    db.prepare('SELECT updated_at FROM job_state WHERE key=?').bind(`fleet.ais.${region}.processed`).first<{updated_at: string}>(),
    db.prepare("SELECT SUM(status='watched') AS watched,SUM(status='candidate') AS candidates FROM fleet_ais_watch WHERE region=?").bind(region)
      .first<{watched: number | null; candidates: number | null}>(),
  ]);
  const hours = new Map<string, HourRow>();
  for (const r of rows.results) {
    const prior = hours.get(r.hour);   // two stamps cut to the same hour: add the counters, keep the longest gap
    hours.set(r.hour, prior ? {...prior, messages: prior.messages + r.messages, watched_messages: prior.watched_messages + r.watched_messages,
      vessels: Math.max(prior.vessels, r.vessels), reconnects: prior.reconnects + r.reconnects, dropped: prior.dropped + r.dropped,
      max_gap_s: Math.max(prior.max_gap_s, r.max_gap_s)} : {...r});
  }
  const up = new Set([...hours.values()].filter(r => r.messages > 0).map(r => r.hour));

  let doc: Record<string, unknown> | null = null, unreadable = false;
  if (beat) {
    try { const v = JSON.parse(beat.value); if (v && typeof v === 'object' && !Array.isArray(v)) doc = v; else unreadable = true; }
    catch { unreadable = true; }
  }
  const lastMessage = str(doc?.last_message_at), lastAge = ageS(lastMessage, now);

  const hours24 = Array.from({length: 24}, (_, i) => {
    const key = hourKey(from24 + i * HOUR_MS), r = hours.get(key);
    return r ? {...r, missing: false} : {hour: key, messages: 0, watched_messages: 0, vessels: 0, reconnects: 0, max_gap_s: 0, dropped: 0, missing: true};
  });
  const outages: RegionHealth['outages'] = [];
  for (let t = from7; t < end; t += HOUR_MS) {
    const key = hourKey(t);
    if (up.has(key)) continue;
    const last = outages[outages.length - 1];
    if (last && hourKey(t - HOUR_MS) === last.to) { last.to = key; last.hours++; } else outages.push({from: key, to: key, hours: 1});
  }

  return {
    region,
    heartbeat: beat && doc ? {written_at: str(doc.written_at), pushed_at: beat.updated_at, age_s: ageS(doc.written_at, now),
      connected: typeof doc.connected === 'boolean' ? doc.connected : null, source: str(doc.source), git_sha: str(doc.git_sha)} : null,
    heartbeat_unreadable: unreadable,
    last_message_at: lastMessage, last_message_age_s: lastAge, stale: lastAge === null || lastAge > STALE_S,
    messages_per_min: num(doc?.messages_per_min), watched_messages_per_min: num(doc?.watched_messages_per_min),
    last_24h: hours24.reduce((s, r) => ({messages: s.messages + r.messages, reconnects: s.reconnects + r.reconnects, dropped: s.dropped + r.dropped,
      hours_reported: s.hours_reported + (r.missing ? 0 : 1)}), {messages: 0, reconnects: 0, dropped: 0, hours_reported: 0}),
    hours_24: hours24,
    gaps: [...hours.values()].filter(r => r.hour >= hourKey(from7) && r.messages > 0 && r.max_gap_s > GAP_S).sort((a, b) => b.hour.localeCompare(a.hour))
      .map(r => ({hour: r.hour, max_gap_s: r.max_gap_s})),
    outages: outages.reverse(),
    uptime: {d7: uptime(up, from7, GAP_DAYS * 24), d30: uptime(up, from30, 30 * 24)},
    processor: processed ? {last_run_at: processed.updated_at, age_s: ageS(processed.updated_at, now) ?? 0} : null,
    watch: {watched: Number(watch?.watched) || 0, candidates: Number(watch?.candidates) || 0, listener: num(doc?.watch_size)},
  };
}

/** AIS health for one region, or every region with any AIS state, as of `now`. */
export async function aisHealth(db: D1Database, region: string | null, now: Date): Promise<AisHealthReport> {
  let regions = region ? [region] : [];
  if (!region) {
    const found = (await db.prepare(`SELECT region FROM fleet_ais_hours UNION SELECT region FROM fleet_ais_watch
      UNION SELECT substr(key,11,length(key)-20) FROM job_state WHERE key LIKE 'fleet.ais.%.heartbeat' ORDER BY 1 LIMIT ?`).bind(MAX_REGIONS)
      .all<{region: string}>()).results;
    regions = found.map(r => Object.values(r)[0] as string).filter(r => typeof r === 'string' && REGION.test(r));
  }
  const t = now.getTime();
  return {checked_at: now.toISOString(), gap_s: GAP_S, stale_s: STALE_S, regions: await Promise.all(regions.map(r => regionHealth(db, r, t)))};
}
