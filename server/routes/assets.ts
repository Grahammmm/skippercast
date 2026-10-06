// The static site. Browsers and caches can retain a previously deployed asset at
// a stable URL, so scripts, styles and pages are published under content-hashed
// names (scripts/fingerprint.mjs). Stable page paths resolve here, uncached.
import {Hono} from 'hono';
import type {Context, Handler} from 'hono';
import {deployment} from '../config.ts';
import type {AppEnv, Env} from '../env.ts';

// FE-01: the front-end rebuild's pages, served only behind the UI_V2 switch
// (docs/plans/front-end/design.md § 14) until FE-60 turns it on by default.
export const V2_SHELLS = Object.freeze({landing: '/landing.html', app: '/app.html'});
/** Parameters that name an area: with one of them `/` serves the app, so every shared v1 link keeps working (design § 7). */
export const AREA_PARAMS: readonly string[] = Object.freeze(['region', 'coast', 'view', 'spot', 'target', 'focus']);

/**
 * Whether the request gets the v2 shell. `?ui=v2` and `?ui=v1` win (a shareable
 * preview; never a cookie, so the choice never persists silently), then the
 * UI_V2 Worker var ("true" or "false", any case; anything else keeps the
 * default, like the fleet flags), then deployments/production.json `ui_v2` (off).
 */
export function uiV2(env: Pick<Env, 'UI_V2'>, search: URLSearchParams): boolean {
  const choice = search.get('ui');
  if (choice === 'v2') return true;
  if (choice === 'v1') return false;
  const v = typeof env.UI_V2 === 'string' ? env.UI_V2.trim().toLowerCase() : '';
  return v === 'true' ? true : v === 'false' ? false : deployment.ui_v2 === true;
}

/**
 * The SHELLS key that answers `path`, if it is a page path: with v2 off, `/` is
 * the v1 shell exactly as before and the v2-only paths answer `null` (404);
 * with v2 on, `/` is the landing, or the app when an area parameter is present,
 * and `/map` is the app. `undefined`: not a page path this function decides.
 */
export function shellFor(path: string, search: URLSearchParams, env: Pick<Env, 'UI_V2'>): string | null | undefined {
  const v2Only = path === '/map' || path === V2_SHELLS.landing || path === V2_SHELLS.app;
  if (path !== '/' && !v2Only) return undefined;
  if (!uiV2(env, search)) return v2Only ? null : '/';
  if (path === '/') return AREA_PARAMS.some(name => search.has(name)) ? V2_SHELLS.app : V2_SHELLS.landing;
  return path === '/map' ? V2_SHELLS.app : path;
}

export const serveAsset: Handler<AppEnv> = async c => {
  const request = c.req.raw, assets = c.env?.ASSETS;
  if (!assets) return new Response('Not found', {status: 404});
  if (c.var.path === '/sw.js') {
    // Stable service-worker URL (see scripts/fingerprint.mjs STABLE): revalidate on every check.
    const response = await assets.fetch(request), fresh = new Response(response.body, response);
    fresh.headers.set('Cache-Control', 'no-cache'); return fresh;
  }
  const page = shellFor(c.var.path, new URL(request.url).searchParams, c.env ?? {});
  if (page === null) return new Response('Not found', {status: 404});
  const current = SHELLS[page ?? c.var.path];
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
