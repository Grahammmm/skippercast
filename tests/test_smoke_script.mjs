import test from 'node:test';
import assert from 'node:assert/strict';
import {createServer} from 'node:http';
import {execFile} from 'node:child_process';
import {mkdtempSync, mkdirSync, writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {fileURLToPath} from 'node:url';

// Runs scripts/smoke_test.sh against a local fake site. The home page is large
// so a "curl | grep -q" pipeline would hit SIGPIPE under pipefail (the bug that
// rolled back every deploy after #26).
// FE-60: `v2` (the default) serves the landing at /, the app at /map and redirects /coast to it; `v1` is
// UI_V2=false or a rolled-back Worker: / is the v1 shell, /map answers only with ?ui=v2, /coast is its own page.
function site({forgedSignedIn=false, swCache='public, max-age=0, must-revalidate', publicKey='B'.repeat(87), shell='v2', broken=''}={}) {
  const body = shell === 'v2' ? '<body class="landing-body">\n' : '<body class="atlas-app">\n';
  const page = '<!doctype html>\n<html><head><title>SkipperCast</title></head>\n' + body + 'x'.repeat(400000) + '</body></html>';
  const small = title => `<!doctype html><html><head><title>${title}</title></head><body></body></html>`;
  return createServer((req, res) => {
    const json = body => { res.writeHead(200, {'Content-Type': 'application/json'}); res.end(JSON.stringify(body)); };
    if (req.url === '/api/health') return json({service: 'SkipperCast', version: '0.3.0', build: 'abcdef0123'});
    if (req.url === '/api/session') return json({signedIn: forgedSignedIn && !!req.headers['oai-authenticated-user-id'], publicKey, signIn: null});
    if (req.url === '/feeds/conditions/latest.json') return json({completed_at: new Date().toISOString()});
    if (req.url === '/sw.js') { res.writeHead(200, {'Content-Type': 'text/javascript', 'Cache-Control': swCache}); return res.end('self.x=1'); }
    const html = text => { res.writeHead(200, {'Content-Type': 'text/html'}); res.end(text); };
    if (req.url.split('?')[0] === broken) { res.writeHead(500); return res.end(); }
    if (shell === 'v2' && req.url === '/map') return html(small('SkipperCast · Map'));
    if (req.url === '/map?ui=v2' || req.url === '/map?presentation=3d') return html(small('SkipperCast · Map'));
    if (req.url === '/coast') {
      if (shell === 'v2') { res.writeHead(302, {Location: '/map?presentation=3d'}); return res.end(); }
      return html(small('Central Coast Explorer · SkipperCast'));
    }
    if (req.url === '/') {
      // Stream like a real edge: the <title> arrives first, the rest later.
      res.writeHead(200, {'Content-Type': 'text/html'});
      res.write(page.slice(0, 80));
      return setTimeout(() => res.end(page.slice(80)), 150);
    }
    res.writeHead(404); res.end();
  });
}
async function smoke(options, {args = ['abcdef0123'], cwd} = {}) {
  const server = site(options);
  await new Promise(r => server.listen(0, '127.0.0.1', r));
  const url = `http://127.0.0.1:${server.address().port}`;
  try {
    return await new Promise(resolve => execFile('bash', [fileURLToPath(new URL('../scripts/smoke_test.sh', import.meta.url)), url, ...args], {cwd, env: {...process.env, HTTPS_PROXY: '', https_proxy: '', HTTP_PROXY: '', http_proxy: '', NO_PROXY: '*'}},
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

test('smoke test fails when the Web Push public key is not deployed', async () => {
  const {code, out} = await smoke({publicKey: null});
  assert.notEqual(code, 0);
  assert.match(out, /no Web Push public key/);
});

test('smoke test fails when the service worker is cached', async () => {
  const {code, out} = await smoke({swCache: 'public, max-age=14400'});
  assert.notEqual(code, 0);
  assert.match(out, /sw\.js must be revalidated/);
});

test('smoke test checks /map and /coast with the v2 shell on (FE-60): /coast follows its redirect to the app', async () => {
  const {code, out} = await smoke();
  assert.equal(code, 0, out);
  assert.match(out, /map page ok \(\/map\)/);
  assert.match(out, /coast page ok/);
});

test('smoke test still passes with UI_V2=false or a rolled-back Worker: /map is checked through ?ui=v2', async () => {
  const {code, out} = await smoke({shell: 'v1'});
  assert.equal(code, 0, out);
  assert.match(out, /map page ok \(\/map\?ui=v2\)/);
});

for (const broken of ['/map', '/coast']) test(`smoke test fails when ${broken} is not served`, async () => {
  const {code, out} = await smoke({broken});
  assert.notEqual(code, 0);
  assert.match(out, new RegExp(`${broken}.* not served`));
});

test('the smoke test tells the shells apart by the landing body class, which only dist/landing.html carries', async () => {
  const {readFileSync} = await import('node:fs');
  assert.match(readFileSync('dist/landing.html', 'utf8'), /<body class="landing-body">/);
  for (const page of ['dist/app.html']) assert.doesNotMatch(readFileSync(page, 'utf8'), /class="landing-body"/, page);
});

// FE-61 removed index.html: the default build id comes from any stamped page, and no dist/client
// must not abort the script (the ls-under-pipefail exit 2 that failed the dabb9c24 deploy).
test('smoke test reads the build id from a stamped page when none is passed', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'smoke-'));
  mkdirSync(join(dir, 'dist/client'), {recursive: true});
  writeFileSync(join(dir, 'dist/client/app.abcdef0123.html'), '');
  writeFileSync(join(dir, 'dist/client/landing.abcdef0123.html'), '');
  const {code, out} = await smoke({}, {args: [], cwd: dir});
  assert.equal(code, 0, out);
  assert.match(out, /health ok \(build abcdef0123\)/);
});

test('smoke test without a build id or dist/client skips the build match instead of exiting', async () => {
  const {code, out} = await smoke({}, {args: [], cwd: mkdtempSync(join(tmpdir(), 'smoke-'))});
  assert.equal(code, 0, out);
  assert.match(out, /Smoke test passed/);
});
