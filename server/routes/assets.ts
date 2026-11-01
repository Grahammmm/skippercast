// The static site. Browsers and caches can retain a previously deployed asset at
// a stable URL, so scripts, styles and pages are published under content-hashed
// names (scripts/fingerprint.mjs). Stable page paths resolve here, uncached.
import {Hono} from 'hono';
import type {Context, Handler} from 'hono';
import type {AppEnv} from '../env.ts';

// The v2 pages. FE-61 removed the v1 shell and the front-end switch (`?ui=` too): `/`
// is the landing, or the app when the link names an area, and `/map` is the app.
export const V2_SHELLS = Object.freeze({landing: '/landing.html', app: '/app.html'});
/**
 * Parameters that name an area: with one of them `/` serves the app, so every shared
 * v1 link keeps working (design § 7), as do Fish links (`place`, `mode`, `species`,
 * translated by web/fish-links.ts) and v1 coast links (FE-78, design § 3A.3).
 */
export const AREA_PARAMS: readonly string[] = Object.freeze(['region', 'coast', 'view', 'spot', 'target', 'focus', 'place', 'mode', 'species', 'presentation', 'habitat', 'current']);

/**
 * FE-78: `/coast` is the app at the 3D terrain presentation. The old standalone
 * page's link (also bookmarked as `/coast.html`) (query kept, so Fish keys carry over) moves to `/map` with
 * `presentation=3d` unless the link names one.
 */
export function coastRedirect(search: URLSearchParams): string {
  const query = new URLSearchParams(search);
  if (!query.has('presentation')) query.set('presentation', '3d');
  return `/map?${query}`;
}

/**
 * The SHELLS key that answers `path`, if it is a page path: `/` (and the old v1
 * shell's `/index.html`) is the landing, or the app when an area parameter is
 * present, and `/map` is the app. `undefined`: not a page path this function decides.
 */
export function shellFor(path: string, search: URLSearchParams): string | undefined {
  if(path === '/privacy') return '/privacy.html'; // Fish compatibility uses the complete existing notice.
  if(path === '/sources') return '/sources.html'; // #475: the canonical sources page (open-questions Q16).
  if(path === '/status') return '/status.html'; // SC-LAUNCH-5: per-source data freshness.
  if (path === '/' || path === '/index.html') return AREA_PARAMS.some(name => search.has(name)) ? V2_SHELLS.app : V2_SHELLS.landing;
  if (path === '/map') return V2_SHELLS.app;
  return path === V2_SHELLS.landing || path === V2_SHELLS.app ? path : undefined;
}

export const serveAsset: Handler<AppEnv> = async c => {
  const request = c.req.raw, assets = c.env?.ASSETS;
  if (!assets) return new Response('Not found', {status: 404});
  if (c.var.path === '/sw.js') {
    // Stable service-worker URL (see scripts/fingerprint.mjs STABLE): revalidate on every check.
    const response = await assets.fetch(request), fresh = new Response(response.body, response);
    fresh.headers.set('Cache-Control', 'no-cache'); return fresh;
  }
  const search = new URL(request.url).searchParams;
  if (c.var.path === '/coast' || c.var.path === '/coast.html') return new Response(null, {status: 302, headers: {Location: coastRedirect(search), 'Cache-Control': 'no-store'}});
  // #475: the page's links are relative, so /sources/ moves to /sources rather than serving the shell there.
  if (c.var.path === '/sources/') return new Response(null, {status: 301, headers: {Location: `/sources${new URL(request.url).search}`, 'Cache-Control': 'no-store'}});
  const page = shellFor(c.var.path, search);
  // A page path stays no-store even if the build's SHELLS lacks it: fetch the page itself.
  const current = SHELLS[page ?? c.var.path] ?? page;
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
