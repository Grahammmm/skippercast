import test from 'node:test';
import assert from 'node:assert/strict';
import {createServer} from 'node:http';
import {execFile} from 'node:child_process';

// Runs scripts/smoke_test.sh against a local fake site. The home page is large
// so a "curl | grep -q" pipeline would hit SIGPIPE under pipefail (the bug that
// rolled back every deploy after #26).
function site({forgedSignedIn=false, swCache='public, max-age=0, must-revalidate'}={}) {
  const page = '<!doctype html>\n<html><head><title>SkipperCast</title></head>\n<body>\n' + 'x'.repeat(400000) + '</body></html>';
  return createServer((req, res) => {
    const json = body => { res.writeHead(200, {'Content-Type': 'application/json'}); res.end(JSON.stringify(body)); };
    if (req.url === '/api/health') return json({service: 'SkipperCast', version: '0.3.0', build: 'abcdef0123'});
    if (req.url === '/api/session') return json({signedIn: forgedSignedIn && !!req.headers['oai-authenticated-user-id'], signIn: null});
    if (req.url === '/feeds/conditions/latest.json') return json({completed_at: new Date().toISOString()});
    if (req.url === '/sw.js') { res.writeHead(200, {'Content-Type': 'text/javascript', 'Cache-Control': swCache}); return res.end('self.x=1'); }
    if (req.url === '/') {
      // Stream like a real edge: the <title> arrives first, the rest later.
      res.writeHead(200, {'Content-Type': 'text/html'});
      res.write(page.slice(0, 80));
      return setTimeout(() => res.end(page.slice(80)), 150);
    }
    res.writeHead(404); res.end();
  });
}
async function smoke(options) {
  const server = site(options);
  await new Promise(r => server.listen(0, '127.0.0.1', r));
  const url = `http://127.0.0.1:${server.address().port}`;
  try {
    return await new Promise(resolve => execFile('bash', ['scripts/smoke_test.sh', url, 'abcdef0123'], {env: {...process.env, HTTPS_PROXY: '', https_proxy: '', HTTP_PROXY: '', http_proxy: '', NO_PROXY: '*'}},
      (error, stdout, stderr) => resolve({code: error ? error.code : 0, out: stdout + stderr})));
  } finally { server.close(); }
}

test('smoke test passes a healthy site with a large home page', async () => {
  const {code, out} = await smoke();
  assert.equal(code, 0, out);
  assert.match(out, /Smoke test passed/);
});

test('smoke test fails when forged identity headers are accepted', async () => {
  const {code, out} = await smoke({forgedSignedIn: true});
  assert.notEqual(code, 0);
  assert.match(out, /forged identity header was accepted/);
});

test('smoke test fails when the service worker is cached', async () => {
  const {code, out} = await smoke({swCache: 'public, max-age=14400'});
  assert.notEqual(code, 0);
  assert.match(out, /sw\.js must be revalidated/);
});
