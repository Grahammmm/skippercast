// The static site. Browsers and caches can retain a previously deployed asset at
// a stable URL, so scripts, styles and pages are published under content-hashed
// names (scripts/fingerprint.mjs). Stable page paths resolve here, uncached.
import {Hono} from 'hono';
import type {Context, Handler} from 'hono';
import type {AppEnv} from '../env.ts';

export const serveAsset: Handler<AppEnv> = async c => {
  const request = c.req.raw, assets = c.env?.ASSETS;
  if (!assets) return new Response('Not found', {status: 404});
  if (c.var.path === '/sw.js') {
    // Stable service-worker URL (see scripts/fingerprint.mjs STABLE): revalidate on every check.
    const response = await assets.fetch(request), fresh = new Response(response.body, response);
    fresh.headers.set('Cache-Control', 'no-cache'); return fresh;
  }
  const current = SHELLS[c.var.path];
  if (!current) return assets.fetch(request);
  const assetUrl = new URL(request.url); assetUrl.pathname = current.replace(/\.html$/, ''); assetUrl.search = ''; // hosts serve pages without .html
  const response = await assets.fetch(new Request(assetUrl, request));
  const fresh = new Response(response.body, response);
  fresh.headers.set('Cache-Control', 'no-store');
  return fresh;
};

/**
 * TA-C4: the built page shell for a stable page path (a SHELLS key such as
 * '/upload.html'), fetched from ASSETS, for routes that serve a page at another
 * path (the upload link /u/<token>). 404 when the page or ASSETS is missing.
 */
export async function shellResponse(c: Context<AppEnv>, page: string): Promise<Response> {
  const assets = c.env?.ASSETS, current = SHELLS[page];
  if (!assets || !current) return new Response('Not found', {status: 404});
  const assetUrl = new URL(c.req.url); assetUrl.pathname = current.replace(/\.html$/, ''); assetUrl.search = '';
  return assets.fetch(new Request(assetUrl, {method: 'GET'}));
}

/** Every path outside /api/ and /feeds/ (registered last). */
export const assets = new Hono<AppEnv>();
assets.all('*', serveAsset);
