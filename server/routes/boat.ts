// POST /api/boat/lookup: AI spec lookup for the boat profile. Signed-in only,
// 20 per person per day, a global daily ceiling, a kill switch, cached by query.
import {Hono} from 'hono';
import {lookupBoat, lookupSettings, validQuery} from '../boat-lookup.ts';
import type {LookupResult, LookupUsage} from '../boat-lookup.ts';
import {json, body, db, hash} from '../http.ts';
import {ClientError} from '../errors.ts';
import type {AppEnv, Env} from '../env.ts';

// One structured line per boat lookup (billed tokens and searches, never the
// query or owner), mirrored to Workers Analytics Engine when ANALYTICS is bound.
function recordLookupUsage(env: Env, usage: LookupUsage, outcome: string): void {
  const line = {event: 'boat_lookup', outcome, model: usage.model || null, turns: usage.turns || 0, input_tokens: usage.input_tokens || 0, output_tokens: usage.output_tokens || 0, web_search_requests: usage.web_search_requests || 0};
  console.log(JSON.stringify(line));
  try { env.ANALYTICS?.writeDataPoint({indexes: ['boat_lookup'], blobs: [line.event, line.outcome, line.model || ''], doubles: [line.input_tokens, line.output_tokens, line.web_search_requests, line.turns]}); } catch {}
}

export const boat = new Hono<AppEnv>();
boat.post('/api/boat/lookup', async c => {
  const env = c.env, owner = c.var.owner;
  const settings = lookupSettings(env);
  if (!settings.enabled) return json({error: 'AI boat lookup is switched off for now; enter your boat details by hand.'}, 503);
  if (!env.ANTHROPIC_API_KEY) return json({error: 'AI boat lookup is not configured yet; enter your boat details by hand.'}, 503);
  const query = validQuery((await body(c.req.raw)).query); if (!query) throw new ClientError('invalid boat name');
  const key = new Request('https://skippercast.com/boat-lookup/' + await hash(query.toLowerCase()));
  let cache: Cache | null | undefined = null;
  try { cache = await (globalThis as {caches?: CacheStorage}).caches?.open('skippercast-boat-lookups-v1'); const hit = await cache?.match(key); if (hit) return json({...await hit.json<object>(), cached: true}); } catch { cache = null; }
  const day = Math.floor(Date.now() / 86400000), id = await hash(owner + ':boat:' + day);
  const count = async (id: string) => (await db(env).prepare('INSERT INTO request_limits(id,count,expires_at) VALUES(?,1,?) ON CONFLICT(id) DO UPDATE SET count=count+1 RETURNING count').bind(id, (day + 2) * 86400).first<{count: number}>())!.count;
  if (await count(id) > 20) return json({error: 'Daily boat lookup limit reached; try again tomorrow or enter details by hand.'}, 429);
  if (await count('global:boat:' + day) > settings.globalDailyLimit) {
    console.warn(JSON.stringify({event: 'boat_lookup_global_cap', day, limit: settings.globalDailyLimit}));
    return json({error: 'AI boat lookup is busy today; try again tomorrow or enter details by hand.'}, 429);
  }
  let result: LookupResult | undefined, outcome = 'ok'; const usage: LookupUsage = {};
  try { result = await lookupBoat(query, {apiKey: env.ANTHROPIC_API_KEY, model: settings.model, usage}); }
  catch (error) { outcome = 'error'; console.error('Boat lookup failed', {reason: String((error as Error).message).slice(0, 200)}); }
  finally { recordLookupUsage(env, usage, outcome); }
  if (outcome !== 'ok') return json({error: 'Could not look up that boat. Check the name or enter details by hand.'}, 502);
  const payload = {query, ...result, looked_up_at: new Date().toISOString()};
  if (cache) try { await cache.put(key, new Response(JSON.stringify(payload), {headers: {'Content-Type': 'application/json', 'Cache-Control': 'public,max-age=2592000'}})); } catch {}
  return json(payload);
});
