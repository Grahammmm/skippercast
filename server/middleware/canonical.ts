// www.skippercast.com is attached to the Worker only to send visitors to the
// one canonical host (cookies, passkeys and caches are per host).
// One trailing host dot (skippercast.com.) is folded too, in the same single 301.
import type {MiddlewareHandler} from 'hono';
import type {AppEnv} from '../env.ts';

export function canonicalRedirect(url: URL): Response | null {
  let host = url.hostname; if (host.length > 1 && host.endsWith('.')) host = host.slice(0, -1);
  if (host.startsWith('www.') && host.length > 4) host = host.slice(4);
  if (host === url.hostname) return null;
  const target = new URL(url); target.hostname = host; target.hash = '';
  return new Response(null, {status: 301, headers: {Location: target.href, 'Cache-Control': 'public, max-age=3600'}});
}

export const canonical: MiddlewareHandler<AppEnv> = async (c, next) => {
  const redirect = canonicalRedirect(new URL(c.req.url));
  if (redirect) return redirect;
  await next();
};
