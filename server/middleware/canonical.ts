// www.skippercast.com is attached to the Worker only to send visitors to the
// one canonical host (cookies, passkeys and caches are per host).
import type {MiddlewareHandler} from 'hono';
import type {AppEnv} from '../env.ts';

export function canonicalRedirect(url: URL): Response | null {
  if (!url.hostname.startsWith('www.')) return null;
  const target = new URL(url); target.hostname = url.hostname.slice(4); target.hash = '';
  return new Response(null, {status: 301, headers: {Location: target.href, 'Cache-Control': 'public, max-age=3600'}});
}

export const canonical: MiddlewareHandler<AppEnv> = async (c, next) => {
  const redirect = canonicalRedirect(new URL(c.req.url));
  if (redirect) return redirect;
  await next();
};
