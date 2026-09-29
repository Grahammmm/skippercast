// Anonymous read endpoints: liveness and the regional feeds, edge-cached.
import {Hono} from 'hono';
import type {Context} from 'hono';
import {readFeed} from '../feeds.ts';
import {cached, cacheKey} from '../edge-cache.ts';
import {regionById, build, PUBLIC_TTL} from '../config.ts';
import {json} from '../http.ts';
import {waitUntil} from './util.ts';
import type {AppEnv} from '../env.ts';
import type {ExternalJSON} from '../types.ts';

export const publicApi = new Hono<AppEnv>();

// Public liveness only: which bindings and secrets exist is not published.
// Feed storage shows per response in X-Feed-Source on /feeds/.
publicApi.all('/api/health', () => json({service: 'SkipperCast', version: '0.3.0', build: BUILD_ID}));

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
