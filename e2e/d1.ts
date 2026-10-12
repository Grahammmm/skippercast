// Shared by the admin specs: run SQL against the local D1 the Playwright dev server uses.
import {execFileSync} from 'node:child_process';
import {resolve} from 'node:path';

const ROOT = resolve(import.meta.dirname, '..');
const WRANGLER = ['--yes', 'wrangler@4.142.0'];   // the pin e2e/serve.mjs uses
const CONFIG = resolve(ROOT, 'wrangler.e2e.local.jsonc'), STATE = resolve(ROOT, '.wrangler/e2e-state');
const ATTEMPTS = 5;

const LOCKED = /SQLITE_BUSY|database is locked/i;
const text = (v: unknown): string => (v == null ? '' : String(v));

/** True when a failed `wrangler d1 execute` was the SQLite file being held by the running Worker (workerd). Wrangler can report the error only in its stdout JSON. */
export const isBusy = (e: unknown): boolean => {
  const x = e as {stderr?: unknown; stdout?: unknown; message?: unknown};
  return LOCKED.test(`${text(x.stderr)}\n${text(x.stdout)}\n${text(x.message)}`);
};

/**
 * Run SQL against the local D1 the dev server uses; the parsed rows of the last statement.
 * The running Worker (and a parallel project's test) holds the same SQLite file, so a busy or
 * locked database is retried up to five times with a growing pause (500 ms, 1 s, ...); any other failure is rethrown unchanged.
 */
export function d1(sql: string): Record<string, unknown>[] {
  for (let attempt = 1; ; attempt++) {
    try {
      const out = execFileSync('npx', [...WRANGLER, 'd1', 'execute', 'skippercast', '--local', '--persist-to', STATE, '--config', CONFIG, '--json', '--command', sql],
        {cwd: ROOT, encoding: 'utf8', env: {...process.env, WRANGLER_SEND_METRICS: 'false'}, stdio: ['ignore', 'pipe', 'pipe']});
      const parsed = JSON.parse(out) as {results: Record<string, unknown>[]}[];
      return parsed.at(-1)?.results ?? [];
    } catch (e) {
      if (!isBusy(e)) throw e;
      if (attempt >= ATTEMPTS) {
        const x = e as Error & {stdout?: unknown};
        if (x instanceof Error && text(x.stdout)) x.message += `\nwrangler stdout: ${text(x.stdout).trim().slice(0, 2000)}`;
        throw e;
      }
      Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 500 * attempt);
    }
  }
}
