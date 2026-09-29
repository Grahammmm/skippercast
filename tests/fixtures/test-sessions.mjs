// Test-side sign-in for private-route tests that are not about sign-in itself:
// a request marked with an `x-test-owner` header is rewritten, before it
// reaches the Worker, into one carrying a real session cookie for that owner
// (a users row and a sessions row holding sha256 of the token). The Worker
// never sees the marker; it authenticates through its normal session path.
import {createHash} from 'node:crypto';

const COOKIE = '__Host-sc_session';
export function withSessions(worker) {
  async function signIn(request, env) {
    const owner = request.headers.get('x-test-owner');
    if (!owner) return request;
    const token = createHash('sha256').update('test-session:' + owner).digest('base64url');
    try {
      await env.DB.prepare('INSERT OR IGNORE INTO users(id,created_at) VALUES(?,?)').bind(owner, new Date().toISOString()).run();
      await env.DB.prepare('INSERT OR IGNORE INTO sessions(id,user_id,created_at,expires_at) VALUES(?,?,?,?)')
        .bind(createHash('sha256').update(token).digest('hex'), owner, new Date().toISOString(), Math.floor(Date.now() / 1000) + 30 * 86400).run();
    } catch { /* a deliberately failing test database: the Worker reports it */ }
    const headers = new Headers(request.headers);
    headers.delete('x-test-owner');
    headers.set('Cookie', `${COOKIE}=${token}`);
    const body = ['GET', 'HEAD'].includes(request.method) ? undefined : await request.text();
    return new Request(request.url, {method: request.method, headers, body});
  }
  return {
    async fetch(request, env = {}, ctx) {
      const withProvider = {IDENTITY_PROVIDER: 'skippercast', ...env};
      return worker.fetch(withProvider.DB ? await signIn(request, withProvider) : request, withProvider, ctx);
    },
    scheduled: worker.scheduled,
  };
}
