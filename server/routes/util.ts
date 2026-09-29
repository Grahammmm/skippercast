import type {Context} from 'hono';
import type {WaitUntil} from '../edge-cache.ts';
import type {AppEnv} from '../env.ts';

/** The ExecutionContext when the runtime gave one (direct test calls do not). */
export function waitUntil(c: Context<AppEnv>): WaitUntil {
  try { return c.executionCtx; } catch { return undefined; }
}
