// Small request/response helpers shared by the routes.
import {ClientError, RateLimited} from './errors.ts';
import {origins} from './config.ts';
import type {Env} from './env.ts';
import type {ExternalJSON} from './types.ts';

export const json = (data: unknown, status = 200): Response => new Response(JSON.stringify(data), {status, headers: {'Content-Type': 'application/json', 'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff', 'Referrer-Policy': 'strict-origin-when-cross-origin'}});
export const hash = async (text: string): Promise<string> => Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text))), b => b.toString(16).padStart(2, '0')).join('');
export const db = (env: Env): D1Database => { if (!env.DB) throw Error('storage unavailable'); return env.DB; };

/** A JSON object body, read as a stream and capped at `max` bytes (default 8 KiB). */
export type Body = Record<string, ExternalJSON>;
export async function body(request: Request, max = 8192): Promise<Body> {
  if (Number(request.headers.get('content-length')) > max) throw new ClientError('body too large');
  const reader = request.body?.getReader(); if (!reader) throw new ClientError('invalid empty body');
  const chunks: Uint8Array[] = []; let size = 0;
  for (;;) { const {done, value} = await reader.read(); if (done) break; size += value.length; if (size > max) { await reader.cancel(); throw new ClientError('body too large'); } chunks.push(value); }
  const bytes = new Uint8Array(size); let offset = 0; for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.length; }
  try { const value = JSON.parse(new TextDecoder().decode(bytes)); if (!value || typeof value !== 'object' || Array.isArray(value)) throw Error(); return value; } catch { throw new ClientError('invalid JSON body'); }
}

export function requireOrigin(request: Request, extraOrigins: Set<string>): void {
  const origin = request.headers.get('Origin');
  if (!origin || !(origins.has(origin) || extraOrigins.has(origin))) throw new ClientError('origin rejected');
}

/** D1-backed counter: more than `limit` calls a minute for this owner (or IP key) throws RateLimited. */
export async function budget(env: Env, owner: string, limit = 30): Promise<void> {
  const minute = Math.floor(Date.now() / 60000), id = await hash(owner + ':' + minute);
  const row = await db(env).prepare('INSERT INTO request_limits(id,count,expires_at) VALUES(?,1,?) ON CONFLICT(id) DO UPDATE SET count=count+1 RETURNING count').bind(id, minute * 60 + 120).first<{count: number}>();
  if (row!.count > limit) throw new RateLimited('rate limited');
}
