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
//
// TA-S7, `social` (D1): posts published in the window with the latest insights
// of each (advisor_post_stats, social/insights.ts) summed per surface and per
// post kind, the chats those posts' links started (advisor_contacts.source_post_id)
// and every contact who came from Instagram (sources ig, igdm, igcomment). Site
// visits per post are not counted: page telemetry carries the visit source
// (`s=ig`, in `analytics.pages`) but not a post id.
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
  social: SocialFunnel;   // TA-S7
  analytics: {available: boolean; reason: 'not-configured' | 'no-data' | 'error' | null;
    llm: {feature: string; calls: number; input_tokens: number; output_tokens: number}[];
    turns: {count: number; p50_ms: number | null; p95_ms: number | null};
    pages: {event: string; source: string; count: number}[]};
}

/** TA-S7: the social rows (D1). Totals are the latest reading of each post published in the window. */
export const SOCIAL_COLUMNS = ['views', 'reach', 'likes', 'comments', 'saved', 'shares', 'follows', 'profile_visits'] as const;
export type SocialTotals = Record<typeof SOCIAL_COLUMNS[number], number>;
export const INSTAGRAM_SOURCES = ['ig', 'igdm', 'igcomment'] as const;
export interface SocialFunnel {
  posts: number; instagram: SocialTotals; facebook: SocialTotals;
  by_kind: ({kind: string; posts: number; chats: number} & SocialTotals)[];
  chats_from_posts: number; chats_from_instagram: number; site_visits_per_post: null;
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
    social: await socialPart(db, since),
  };
}

const zeros = (): SocialTotals => Object.fromEntries(SOCIAL_COLUMNS.map(c => [c, 0])) as SocialTotals;

/** TA-S7: posts published since `since`, their latest numbers per surface and the chats they started. */
async function socialPart(db: D1Database, since: string): Promise<SocialFunnel> {
  const posts = (await db.prepare(`SELECT id,kind,ig_media_id FROM advisor_posts WHERE status IN ('posted','partial') AND posted_at>=?`).bind(since)
    .all<{id: string; kind: string; ig_media_id: string | null}>()).results;
  // The latest row of each (post, surface) for those posts.
  const latest = (await db.prepare(`SELECT s.* FROM advisor_post_stats s JOIN (SELECT post_id, platform, MAX(day) AS day FROM advisor_post_stats GROUP BY post_id, platform) m
      ON m.post_id=s.post_id AND m.platform=s.platform AND m.day=s.day JOIN advisor_posts p ON p.id=s.post_id
      WHERE p.status IN ('posted','partial') AND p.posted_at>=?`).bind(since).all<Record<string, unknown>>()).results;
  // Chats by the post they came from (its id, or its Instagram media id in the link).
  const chats = (await db.prepare(`SELECT p.id AS post_id, COUNT(c.id) AS n FROM advisor_posts p JOIN advisor_contacts c ON c.source_post_id=p.id OR (p.ig_media_id IS NOT NULL AND c.source_post_id=p.ig_media_id)
      WHERE p.status IN ('posted','partial') AND p.posted_at>=? GROUP BY p.id`).bind(since).all<{post_id: string; n: number}>()).results;
  const kindOf = new Map(posts.map(p => [p.id, label(p.kind)]));
  const totals: Record<'instagram' | 'facebook', SocialTotals> = {instagram: zeros(), facebook: zeros()};
  const kinds = new Map<string, {kind: string; posts: number; chats: number} & SocialTotals>();
  const kindRow = (kind: string) => { let row = kinds.get(kind); if (!row) { row = {kind, posts: 0, chats: 0, ...zeros()}; kinds.set(kind, row); } return row; };
  for (const p of posts) kindRow(label(p.kind)).posts++;
  for (const row of latest) {
    const platform = row.platform === 'facebook' ? 'facebook' : row.platform === 'instagram' ? 'instagram' : null;
    const kind = kindOf.get(String(row.post_id));
    if (!platform || !kind) continue;
    for (const c of SOCIAL_COLUMNS) { totals[platform][c] += num(row[c]); kindRow(kind)[c] += num(row[c]); }
  }
  let fromPosts = 0;
  for (const c of chats) { const kind = kindOf.get(c.post_id); if (kind) { kindRow(kind).chats += num(c.n); fromPosts += num(c.n); } }
  const fromInstagram = await count(db, `SELECT COUNT(*) AS n FROM advisor_contacts WHERE created_at>=? AND source IN (${INSTAGRAM_SOURCES.map(() => '?').join(',')})`, since, ...INSTAGRAM_SOURCES);
  return {posts: posts.length, instagram: totals.instagram, facebook: totals.facebook, by_kind: [...kinds.values()].sort((a, b) => b.posts - a.posts || a.kind.localeCompare(b.kind)),
    chats_from_posts: fromPosts, chats_from_instagram: fromInstagram, site_visits_per_post: null};
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
