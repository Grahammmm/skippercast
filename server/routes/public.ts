// Anonymous read endpoints: liveness and the regional feeds, edge-cached.
import {Hono} from 'hono';
import type {Context} from 'hono';
import {readFeed} from '../feeds.ts';
import {cached, cacheKey, clientIP, overLimit, tooManyRequests} from '../edge-cache.ts';
import {regionById, build, PUBLIC_TTL} from '../config.ts';
import {json} from '../http.ts';
import {waitUntil} from './util.ts';
import type {AppEnv} from '../env.ts';
import type {ExternalJSON} from '../types.ts';

export const publicApi = new Hono<AppEnv>();

// Public liveness only: which bindings and secrets exist is not published.
// Feed storage shows per response in X-Feed-Source on /feeds/.
publicApi.all('/api/health', () => json({service: 'SkipperCast', version: '0.6.0', build: BUILD_ID}));

publicApi.get('/api/habitat', async c => {
  const url = new URL(c.req.url), region = regionById(url.searchParams.get('region'));
  if (!region?.habitat_feed) return json({error: 'Unknown region'}, 404);
  const feedUrl = region.habitat_feed;
  return cached(cacheKey(url, {params: ['region'], build: build()}), waitUntil(c), async () => {
    const feed = await readFeed(feedUrl); if (feed.region_id !== region.id || feed.schema_version !== 1) throw Error('region mismatch');
    const response = json(feed); response.headers.set('Cache-Control', PUBLIC_TTL); return {response};
  });
});

publicApi.get('/api/intelligence', c => regionalFeed(c));
// Edge-cache hits are free; only a miss, which reads and parses the ~1.4 MB
// feed, counts against a per-IP limit (60/min on PUBLIC_LIMITER, prefix
// "daily"). One map load asks for two or three parts, so limiting hits would
// refuse shared addresses (carrier NAT, a boat club's Wi-Fi) for no saving.
publicApi.get('/api/daily', c => dailyPart(c));

// Parts of the daily feed the map reads at startup (P4-05). The whole feed is
// ~1.4 MB; the regulations badge needs its rule checks (~45 KB), and the MPA
// screen needs one record only when the live boundary query fails.
export const DAILY_PARTS = ['regulations', 'mpa-boundaries', 'additional-closures'] as const;
type DailyPart = typeof DAILY_PARTS[number];

/** The checks the app applies to the whole daily feed (dist/bite-evidence.js validFeed, dist/region.js acceptsFeed). */
export function validDailyFeed(feed: ExternalJSON, regionId: string): boolean {
  return (feed?.region_id === regionId || (!feed?.region_id && regionId === 'morro-bay')) &&
    feed.schema_version === 1 && Number.isFinite(Date.parse(feed.generated_at)) &&
    !!feed.sources && typeof feed.sources === 'object' && !Array.isArray(feed.sources) && Array.isArray(feed.reports) &&
    !!feed.health && feed.catch_probability === null && feed.bite_score === null;
}

/** One part of a valid daily feed, with the header fields a reader checks. */
export function dailyPartOf(feed: ExternalJSON, part: DailyPart): ExternalJSON {
  const head = {schema_version: feed.schema_version, region_id: feed.region_id, generated_at: feed.generated_at,
    catch_probability: null, bite_score: null, part};
  if (part === 'regulations') return {...head, regulations: feed.regulations ?? null};
  return {...head, sources: part in feed.sources ? {[part]: feed.sources[part]} : {}};
}

async function dailyPart(c: Context<AppEnv>): Promise<Response> {
  const url = new URL(c.req.url), region = regionById(url.searchParams.get('region'));
  const part = DAILY_PARTS.find(p => p === url.searchParams.get('part'));
  if (!region) return json({error: 'Unknown region'}, 404);
  if (!part) return json({error: 'Unknown part'}, 400);
  const key = (p: DailyPart) => cacheKey(new URL(`/api/daily?region=${encodeURIComponent(region.id)}&part=${p}`, url), {params: ['region', 'part'], build: build()});
  return cached(key(part), waitUntil(c), async () => {
    // One read of the feed answers every part; the siblings are cached too.
    const feed = await readFeed(region.daily_feed);
    if (!validDailyFeed(feed, region.id)) throw Error('daily feed failed validation');
    const respond = (p: DailyPart) => { const r = json(dailyPartOf(feed, p)); r.headers.set('Cache-Control', PUBLIC_TTL); return r; };
    return {response: respond(part), extra: DAILY_PARTS.filter(p => p !== part).map(p => [key(p), respond(p)] as [Request, Response])};
  }, async () => (await overLimit(c.env?.PUBLIC_LIMITER, 'daily:' + clientIP(c.req.raw)) ? tooManyRequests() : null));
}
publicApi.get('/api/forecast', c => regionalFeed(c));

async function regionalFeed(c: Context<AppEnv>): Promise<Response> {
  const url = new URL(c.req.url), path = c.var.path, region = regionById(url.searchParams.get('region'));
  if (!region) return json({error: 'Unknown region'}, 404);
  const key = (p: string) => cacheKey(new URL(p + '?region=' + encodeURIComponent(region.id), url), {params: ['region'], build: build()});
  return cached(key(path), waitUntil(c), async () => {
    // One read and parse of the regional feed answers both endpoints; the
    // sibling response is cached too, so the feed is decoded once per TTL.
    const feed = await readFeed(region.intelligence_feed); if (feed.region_id !== region.id) throw Error('region mismatch');
    const forecast = json(feed.forecast); forecast.headers.set('Cache-Control', PUBLIC_TTL);
    const intelligence = json({...feed, forecast: undefined, sources: Object.fromEntries(Object.entries(feed.sources as Record<string, ExternalJSON>).map(([k, v]) => [k, k.startsWith('model-') || k.startsWith('verify-') ? {name: v.name, status: v.status, issue: v.issue, url: v.url, checked_at: v.checked_at} : v]))});
    // Live conditions refresh often: one minute, matching intelligence.json on /feeds/.
    intelligence.headers.set('Cache-Control', 'public, max-age=60, s-maxage=60');
    return path === '/api/forecast' ? {response: forecast, extra: [[key('/api/intelligence'), intelligence]]} : {response: intelligence, extra: [[key('/api/forecast'), forecast]]};
  });
}
