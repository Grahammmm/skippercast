// Every response, including shells, assets, feeds and errors, carries the
// security headers (server/security-headers.ts). A session renewed while
// answering carries its refreshed cookie, unless the route set a cookie itself.
import type {MiddlewareHandler} from 'hono';
import {secure} from '../security-headers.ts';
import type {AppEnv} from '../env.ts';

export const securityHeaders: MiddlewareHandler<AppEnv> = async (c, next) => {
  await next();
  let response = c.res;
  const renewed = c.get('user')?.renewed;
  if (renewed && !response.headers.has('Set-Cookie')) {
    try { response.headers.append('Set-Cookie', renewed); }
    catch { response = new Response(response.body, response); response.headers.append('Set-Cookie', renewed); }
  }
  response = secure(response);
  if (response !== c.res) c.res = response;
};
