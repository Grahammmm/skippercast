// Request id: one per request, echoed in X-Request-Id on every response and as
// `request_id` in every JSON error body, and logged with request failures, so a
// person's report can be matched to the Worker's logs. A well-formed incoming
// X-Request-Id (e.g. from a proxy) is kept; anything else is replaced.
import type {MiddlewareHandler} from 'hono';
import type {AppEnv} from '../env.ts';

const VALID = /^[A-Za-z0-9_-]{8,64}$/;

export const requestId: MiddlewareHandler<AppEnv> = async (c, next) => {
  const incoming = c.req.header('X-Request-Id');
  const id = incoming && VALID.test(incoming) ? incoming : crypto.randomUUID();
  c.set('requestId', id);
  await next();
  let response = c.res;
  if (response.status >= 400 && response.headers.get('Content-Type') === 'application/json') response = await withRequestId(response, id);
  try { response.headers.set('X-Request-Id', id); }
  catch { response = new Response(response.body, response); response.headers.set('X-Request-Id', id); }
  if (response !== c.res) c.res = response;
};

/** The JSON error response with `request_id` added (unchanged when it is not a JSON error object). */
async function withRequestId(response: Response, id: string): Promise<Response> {
  let data: unknown;
  try { data = await response.clone().json(); } catch { return response; }
  if (!data || typeof data !== 'object' || Array.isArray(data) || !('error' in data) || 'request_id' in data) return response;
  const headers = new Headers(response.headers);
  headers.delete('Content-Length');
  return new Response(JSON.stringify({...data, request_id: id}), {status: response.status, statusText: response.statusText, headers});
}
