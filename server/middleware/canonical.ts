// www.skippercast.com is attached to the Worker only to send visitors to the
// one canonical host (cookies, passkeys and caches are per host).
// One trailing host dot (skippercast.com.) is folded too, in the same single 301.
// Plain http:// on the production host goes to https:// in that same 301: HSTS
// cannot help a first visit, because browsers ignore it on an http reply.
// Local development and the workers.dev staging address keep their scheme.
import type {MiddlewareHandler} from 'hono';
import type {AppEnv} from '../env.ts';

const SITE = 'skippercast.com';

export function canonicalRedirect(url: URL): Response | null {
  let host = url.hostname; if (host.length > 1 && host.endsWith('.')) host = host.slice(0, -1);
  if (host.startsWith('www.') && host.length > 4) host = host.slice(4);
  const secure = url.protocol === 'http:' && (host === SITE || host.endsWith('.' + SITE));
  if (host === url.hostname && !secure) return null;
  const target = new URL(url); target.hostname = host; target.hash = '';
  if (secure) target.protocol = 'https:';
  return new Response(null, {status: 301, headers: {Location: target.href, 'Cache-Control': 'public, max-age=3600'}});
}

export const canonical: MiddlewareHandler<AppEnv> = async (c, next) => {
  const redirect = canonicalRedirect(new URL(c.req.url));
  if (redirect) return redirect;
  await next();
};
