// scripts/smoke_test.sh gates every Cloudflare deploy: a false failure rolls
// the release back. These tests run it against a local stand-in site.
import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import { execFile, spawnSync } from 'node:child_process';

const haveTools = ['bash', 'curl', 'python3'].every(
  (tool) => spawnSync('sh', ['-c', `command -v ${tool}`]).status === 0,
);

// The deployed home page arrives over the network in pieces. When <title> is in
// an early piece, `curl | grep -q` let grep exit before curl finished writing,
// curl failed with error 23 and pipefail failed the check (rolling back good
// deploys). The stand-in sends the head first (bigger than curl's output buffer,
// so curl passes it on at once) and the rest a moment later, which makes that
// race happen every time.
const homeHead = `<!doctype html>\n<html><head><title>SkipperCast</title>\n${
  '<meta name="pad" content="padding">\n'.repeat(4_000)
}</head>\n`;
const homeRest = `<body>\n${'<p>padding</p>\n'.repeat(5_000)}</body></html>\n`;

function site({ home = null, session = '{"signedIn":false}' } = {}) {
  return http.createServer((req, res) => {
    const send = (status, type, body, headers = {}) => {
      res.writeHead(status, { 'content-type': type, ...headers });
      res.end(body);
    };
    if (req.url === '/api/health') return send(200, 'application/json', '{"service":"SkipperCast","build":""}');
    if (req.url === '/' && home !== null) return send(200, 'text/html', home);
    if (req.url === '/') {
      res.writeHead(200, { 'content-type': 'text/html' });
      res.write(homeHead);
      setTimeout(() => res.end(homeRest), 300);
      return undefined;
    }
    if (req.url === '/sw.js') return send(200, 'text/javascript', '', { 'cache-control': 'public, max-age=0, must-revalidate' });
    if (req.url === '/feeds/conditions/latest.json') return send(200, 'application/json', '{"completed_at":"2026-09-29T00:00:00Z"}');
    if (req.url === '/api/session') return send(200, 'application/json', session);
    return send(404, 'text/plain', 'not found');
  });
}

async function runSmoke(options) {
  const server = site(options);
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  const url = `http://127.0.0.1:${server.address().port}`;
  try {
    return await new Promise((resolve) => {
      execFile('bash', ['scripts/smoke_test.sh', url, ''], { maxBuffer: 1 << 20 }, (error, stdout, stderr) => {
        resolve({ code: error ? error.code : 0, output: stdout + stderr });
      });
    });
  } finally {
    server.close();
  }
}

test('smoke test passes a healthy home page that arrives in pieces', { skip: !haveTools && 'needs bash, curl and python3' }, async () => {
  for (let run = 0; run < 3; run += 1) {
    const { code, output } = await runSmoke();
    assert.equal(code, 0, output);
    assert.match(output, /Smoke test passed/);
  }
});

test('smoke test still fails a home page without a title', { skip: !haveTools && 'needs bash, curl and python3' }, async () => {
  const { code, output } = await runSmoke({ home: '<html><body>no title</body></html>' });
  assert.notEqual(code, 0);
  assert.match(output, /home page has no <title>/);
});

test('smoke test still fails when a forged identity is accepted', { skip: !haveTools && 'needs bash, curl and python3' }, async () => {
  const { code, output } = await runSmoke({ session: '{"signedIn":true}' });
  assert.notEqual(code, 0);
  assert.match(output, /forged identity header was accepted/);
});
