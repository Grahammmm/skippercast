// The admin Funnel view's data (docs/plans/text-advisor/08-website.md § Admin,
// Funnel; OP-5; TA-W4): GET /api/admin/funnel?days=7|30. Numbers only: counts,
// rates, and the bounded labels they are grouped by (source, intent, feature,
// event); never a contact, message, boat or user id.
//
//   D1               new contacts per UTC day by first-touch source, inbound messages
//                    by intent, replies per contact, the return rate (contacts active
//                    on two or more days of those active), boats verified, published
//                    reports per reporting boat, photos submitted and approved, the
//                    photo-consent rate
//   Analytics Engine LLM calls and tokens by feature (`llm`), advisor turn latency
//                    p50/p95 (`advisor_turn`), advisor page views and CTA clicks by
//                    visit source (`client_event`), read through the same SQL API
//                    scripts/ops_report.py uses, with CF_ANALYTICS_TOKEN (Account
//                    Analytics: Read) and CLOUDFLARE_ACCOUNT_ID. The Worker only reads.
//
// Without the token or the account id the D1 part still answers and
// `analytics.available` is false. The SQL fetcher is injected for tests.
import {advisorLog} from '../log.ts';
import {DATASET} from '../../analytics.ts';
import type {Env} from '../../env.ts';

export const FUNNEL_DAYS = [7, 30] as const;
export type FunnelDays = typeof FUNNEL_DAYS[number];
export const SQL_API = 'https://api.cloudflare.com/client/v4/accounts/{account}/analytics_engine/sql';
export const SQL_TIMEOUT_MS = 10000;
export const TOP_INTENTS = 20;
/** The advisor page events (web/advisor/pages.ts; server/telemetry.ts FUNNEL_EVENTS). */
export const PAGE_EVENTS = ['advisor_port_view', 'advisor_species_view', 'advisor_boat_view', 'advisor_cta'] as const;
/** Visit sources (server/telemetry.ts): '' when the page URL had none. */
export const VISIT_SOURCES = ['txt', 'ig', 'fb', 'qr', ''] as const;
const DAY = 86400000;

/** Runs one Analytics Engine SQL statement; the rows as the API returns them. */
export type SqlFetcher = (sql: string) => Promise<Record<string, unknown>[]>;

export class AnalyticsError extends Error {
  status: number; noData: boolean;
  constructor(status: number, noData: boolean) { super(`analytics engine sql http ${status}`); this.status = status; this.noData = noData; }
}

/**
 * The SQL API reader, or null when CF_ANALYTICS_TOKEN or CLOUDFLARE_ACCOUNT_ID
 * is missing. A dataset never written answers 4xx naming it: that is `noData`.
 */
export function analyticsSql(env: Pick<Env, 'CF_ANALYTICS_TOKEN' | 'CLOUDFLARE_ACCOUNT_ID'>, fetcher: typeof fetch = fetch): SqlFetcher | null {
  const token = (env.CF_ANALYTICS_TOKEN ?? '').trim(), account = (env.CLOUDFLARE_ACCOUNT_ID ?? '').trim();
  if (!token || !/^[0-9a-f]{32}$/i.test(account)) return null;
  return async sql => {
    const response = await fetcher(SQL_API.replace('{account}', account), {method: 'POST', body: sql, signal: AbortSignal.timeout(SQL_TIMEOUT_MS),
      headers: {Authorization: `Bearer ${token}`, 'Content-Type': 'text/plain', 'User-Agent': 'SkipperCast-admin-funnel/1'}});
    if (!response.ok) {
      const text = (await response.text().catch(() => '')).slice(0, 500).toLowerCase();
      throw new AnalyticsError(response.status, (response.status === 400 || response.status === 404) && text.includes(DATASET) && /not found|does not exist|unknown table/.test(text));
    }
    const data = await response.json() as {data?: unknown};
    return Array.isArray(data?.data) ? data.data as Record<string, unknown>[] : [];
  };
}

const within = (days: FunnelDays): string => `timestamp > NOW() - INTERVAL '${days}' DAY`;
/** The three statements, by key (columns per kind: server/analytics.ts). `days` is 7 or 30, never caller text. */
export function funnelQueries(days: FunnelDays): Record<'llm' | 'turns' | 'pages', string> {
  if (!FUNNEL_DAYS.includes(days)) throw Error('days must be 7 or 30');
  return {
    llm: `SELECT blob2 AS feature, SUM(_sample_interval) AS calls, SUM(_sample_interval * double1) AS input_tokens, SUM(_sample_interval * double2) AS output_tokens
FROM ${DATASET} WHERE index1 = 'llm' AND ${within(days)}
GROUP BY feature ORDER BY calls DESC LIMIT 30`,
    turns: `SELECT SUM(_sample_interval) AS turns, quantileExactWeighted(0.5)(double1, _sample_interval) AS p50_ms,
  quantileExactWeighted(0.95)(double1, _sample_interval) AS p95_ms
FROM ${DATASET} WHERE index1 = 'advisor_turn' AND ${within(days)}`,
    pages: `SELECT blob2 AS event, blob5 AS source, SUM(_sample_interval) AS events
FROM ${DATASET} WHERE index1 = 'client_event' AND blob2 IN (${PAGE_EVENTS.map(e => `'${e}'`).join(', ')}) AND ${within(days)}
GROUP BY event, source ORDER BY events DESC LIMIT 50`,
  };
}

export interface Funnel {
  days: FunnelDays; since: string; generated_at: string;
  contacts: {new: number; sources: string[]; by_day: {day: string; total: number; by_source: Record<string, number>}[]};
  messages: {inbound: number; by_intent: {intent: string; count: number}[]};
  replies: {outbound: number; contacts: number; per_contact: number | null};
  return_rate: {active: number; returning: number; rate: number | null};
  boats: {verified: number; verified_total: number; pending: number; reports_published: number; boats_reporting: number; reports_per_boat: number | null};
  photos: {submitted: number; approved: number};
  consent: {boats: number; given: number; rate: number | null};
  analytics: {available: boolean; reason: 'not-configured' | 'no-data' | 'error' | null;
    llm: {feature: string; calls: number; input_tokens: number; output_tokens: number}[];
    turns: {count: number; p50_ms: number | null; p95_ms: number | null};
    pages: {event: string; source: string; count: number}[]};
}

const num = (v: unknown): number => { const n = Number(v); return Number.isFinite(n) ? n : 0; };
const ratio = (a: number, b: number): number | null => (b > 0 ? Math.round((a / b) * 1000) / 1000 : null);
const label = (v: unknown, max = 64): string => { const s = String(v ?? ''); return /^[\w:.-]{1,64}$/.test(s) ? s.slice(0, max) : 'other'; };
const count = async (db: D1Database, sql: string, ...args: unknown[]): Promise<number> => num((await db.prepare(sql).bind(...args).first<{n: number}>())?.n);

/** The UTC days from `since` through `now`, oldest first. */
export function daysBetween(since: number, now: number): string[] {
  const out: string[] = [];
  for (let d = Math.floor(since / DAY); d <= Math.floor(now / DAY); d++) out.push(new Date(d * DAY).toISOString().slice(0, 10));
  return out;
}

async function d1Part(db: D1Database, days: FunnelDays, now: number): Promise<Omit<Funnel, 'analytics' | 'generated_at'>> {
  const start = now - days * DAY, since = new Date(start).toISOString();

  const perDay = (await db.prepare(`SELECT substr(created_at,1,10) AS day, COALESCE(source,'unknown') AS source, COUNT(*) AS n FROM advisor_contacts
      WHERE created_at>=? GROUP BY day, source`).bind(since).all<{day: string; source: string; n: number}>()).results;
  const sources = [...new Set(perDay.map(r => label(r.source)))].sort();
  const byDay = daysBetween(start, now).map(day => {
    const rows = perDay.filter(r => r.day === day), by_source: Record<string, number> = {};
    for (const r of rows) by_source[label(r.source)] = (by_source[label(r.source)] ?? 0) + num(r.n);
    return {day, total: rows.reduce((s, r) => s + num(r.n), 0), by_source};
  });

  const intents = (await db.prepare(`SELECT COALESCE(intent,'none') AS intent, COUNT(*) AS n FROM advisor_messages WHERE direction='in' AND created_at>=?
      GROUP BY intent ORDER BY n DESC, intent`).bind(since).all<{intent: string; n: number}>()).results;
  const top = intents.slice(0, TOP_INTENTS).map(r => ({intent: label(r.intent), count: num(r.n)}));
  const rest = intents.slice(TOP_INTENTS).reduce((s, r) => s + num(r.n), 0);
  if (rest) top.push({intent: 'other', count: rest});
  const inbound = intents.reduce((s, r) => s + num(r.n), 0);

  const out = await db.prepare(`SELECT COUNT(*) AS n, COUNT(DISTINCT contact_id) AS contacts FROM advisor_messages WHERE direction='out' AND status<>'failed' AND created_at>=?`)
    .bind(since).first<{n: number; contacts: number}>();
  const active = await db.prepare(`SELECT COUNT(*) AS active, SUM(CASE WHEN days>=2 THEN 1 ELSE 0 END) AS back FROM
      (SELECT contact_id, COUNT(DISTINCT substr(created_at,1,10)) AS days FROM advisor_messages WHERE direction='in' AND created_at>=? GROUP BY contact_id)`)
    .bind(since).first<{active: number; back: number | null}>();

  const reports = await db.prepare(`SELECT COUNT(*) AS n, COUNT(DISTINCT boat_id) AS boats FROM advisor_reports WHERE status='published' AND published_at>=?`)
    .bind(since).first<{n: number; boats: number}>();
  const consent = await db.prepare(`SELECT COUNT(*) AS boats, SUM(CASE WHEN consent_photos_at IS NOT NULL AND (consent_revoked_at IS NULL OR consent_revoked_at<consent_photos_at) THEN 1 ELSE 0 END) AS given
      FROM advisor_boats WHERE status<>'rejected'`).first<{boats: number; given: number | null}>();

  const outbound = num(out?.n), contacts = num(out?.contacts), actives = num(active?.active), returning = num(active?.back);
  const published = num(reports?.n), reporting = num(reports?.boats), boats = num(consent?.boats), given = num(consent?.given);
  return {
    days, since,
    contacts: {new: byDay.reduce((s, d) => s + d.total, 0), sources, by_day: byDay},
    messages: {inbound, by_intent: top},
    replies: {outbound, contacts, per_contact: ratio(outbound, contacts)},
    return_rate: {active: actives, returning, rate: ratio(returning, actives)},
    boats: {
      verified: await count(db, "SELECT COUNT(*) AS n FROM advisor_boats WHERE status='verified' AND verified_at>=?", since),
      verified_total: await count(db, "SELECT COUNT(*) AS n FROM advisor_boats WHERE status='verified'"),
      pending: await count(db, "SELECT COUNT(*) AS n FROM advisor_boats WHERE status='pending'"),
      reports_published: published, boats_reporting: reporting, reports_per_boat: ratio(published, reporting),
    },
    photos: {
      submitted: await count(db, "SELECT COUNT(*) AS n FROM advisor_media WHERE kind='image' AND created_at>=?", since),
      approved: await count(db, "SELECT COUNT(*) AS n FROM advisor_media WHERE kind='image' AND publish_state IN ('approved','posted') AND created_at>=?", since),
    },
    consent: {boats, given, rate: ratio(given, boats)},
  };
}

async function analyticsPart(sql: SqlFetcher | null, days: FunnelDays): Promise<Funnel['analytics']> {
  const empty: Funnel['analytics'] = {available: false, reason: 'not-configured', llm: [], turns: {count: 0, p50_ms: null, p95_ms: null}, pages: []};
  if (!sql) return empty;
  const q = funnelQueries(days);
  try {
    const [llm, turns, pages] = await Promise.all([sql(q.llm), sql(q.turns), sql(q.pages)]);
    const t = turns[0] ?? {}, n = num(t.turns);
    return {
      available: true, reason: null,
      llm: llm.map(r => ({feature: label(r.feature), calls: num(r.calls), input_tokens: num(r.input_tokens), output_tokens: num(r.output_tokens)})),
      turns: {count: n, p50_ms: n ? Math.round(num(t.p50_ms)) : null, p95_ms: n ? Math.round(num(t.p95_ms)) : null},
      pages: pages.filter(r => (PAGE_EVENTS as readonly string[]).includes(String(r.event)))
        .map(r => ({event: String(r.event), source: (VISIT_SOURCES as readonly string[]).includes(String(r.source ?? '')) ? String(r.source ?? '') : 'other', count: num(r.events)})),
    };
  } catch (error) {
    const e = error instanceof AnalyticsError ? error : null;
    advisorLog('warn', 'advisor_funnel_analytics_failed', {status: e?.status ?? 0, no_data: e?.noData ?? false});
    return {...empty, reason: e?.noData ? 'no-data' : 'error'};
  }
}

/** The funnel for the last `days` days. */
export async function adminFunnel(env: Env, days: FunnelDays, opts: {now?: number; sql?: SqlFetcher | null} = {}): Promise<Funnel> {
  const now = opts.now ?? Date.now();
  const sql = opts.sql !== undefined ? opts.sql : analyticsSql(env);
  const [d1, analytics] = await Promise.all([d1Part(env.DB!, days, now), analyticsPart(sql, days)]);
  return {...d1, generated_at: new Date(now).toISOString(), analytics};
}
