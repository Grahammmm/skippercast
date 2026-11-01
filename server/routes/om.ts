// SkipperCast's own NOAA/ECMWF forecast service, answering Open-Meteo-style
// queries (server/model-api.js), edge-cached on the normalised query.
import {Hono} from 'hono';
import type {Context} from 'hono';
import {answer as modelAnswer, meta as modelMeta, MODELS as FORECAST_MODELS, QueryError} from '../model-api.js';
import type {TileStore} from '../model-api.js';
import {createFeedReader} from '../feeds.ts';
import {cached, cacheKey, overLimit, clientIP, tooManyRequests} from '../edge-cache.ts';
import {deployment, build, PUBLIC_TTL} from '../config.ts';
import {json} from '../http.ts';
import {waitUntil} from './util.ts';
import type {AppEnv} from '../env.ts';

const base = deployment.forecast_feed;
function tileStore(): TileStore {
  const readFeed = createFeedReader();
  return {
    manifest: model => FORECAST_MODELS[model] ? readFeed(`${base}/${model}/manifest.json`) : null,
    tile: (model, key) => FORECAST_MODELS[model] && /^-?\d{1,3}_-?\d{1,3}$/.test(key) ? readFeed(`${base}/${model}/tiles/${key}.json`) : null};
}

function respond(c: Context<AppEnv>, compute: () => Promise<unknown>): Promise<Response> {
  const url = new URL(c.req.url);
  // Keyed on the normalised query (parameter order does not split the cache).
  // The per-IP limit counts cache misses only (as /api/daily), so carrier NAT and club Wi-Fi are not refused cached answers.
  return cached(cacheKey(url, {build: build()}), waitUntil(c), async () => {
    try {
      const response = json(await compute()); response.headers.set('Cache-Control', PUBLIC_TTL); return {response};
    } catch (error) { if (error instanceof QueryError) return {response: json({error: true, reason: error.message}, 400)}; throw error; }
  }, async () => (await overLimit(c.env?.PUBLIC_LIMITER, 'om:' + clientIP(c.req.raw)) ? tooManyRequests() : null));
}

export const om = new Hono<AppEnv>();
for (const kind of ['forecast', 'marine']) om.get(`/api/om/v1/${kind}`, c => respond(c, () => modelAnswer(kind, new URL(c.req.url).searchParams, tileStore())));
om.get('/api/om/data/:model{[a-z0-9_]+}/static/meta.json', c => respond(c, () => modelMeta(c.req.param('model'), tileStore())));
