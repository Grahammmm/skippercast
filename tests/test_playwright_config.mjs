// SC1938-11: a local e2e run reuses a running server only when E2E_REUSE is exactly '1'; CI never does.
import test from 'node:test';
import assert from 'node:assert/strict';

let n = 0;
async function load(env) {
  const keys = ['CI', 'E2E_REUSE', 'E2E_PORT'];
  const saved = Object.fromEntries(keys.map(k => [k, process.env[k]]));
  for (const k of keys) delete process.env[k];
  Object.assign(process.env, env);
  try {
    return (await import(`../playwright.config.ts?case=${n++}`)).default;
  } finally {
    for (const k of keys) saved[k] === undefined ? delete process.env[k] : (process.env[k] = saved[k]);
  }
}

test('reuseExistingServer is true only for a local run with E2E_REUSE=1', async () => {
  const cases = [[{CI: '1'}, false], [{}, false], [{E2E_REUSE: '1'}, true], [{CI: '1', E2E_REUSE: '1'}, false],
    [{E2E_REUSE: 'true'}, false], [{E2E_REUSE: 'yes'}, false], [{E2E_REUSE: '0'}, false], [{E2E_REUSE: ''}, false]];
  for (const [env, want] of cases) assert.equal((await load(env)).webServer.reuseExistingServer, want, JSON.stringify(env));
});

test('port, projects and retries are unchanged', async () => {
  const c = await load({E2E_PORT: '9000'});
  assert.equal(c.use.baseURL, 'http://localhost:9000');
  assert.equal(c.webServer.url, 'http://localhost:9000/api/health');
  assert.deepEqual(c.projects.map(p => p.name), ['phone', 'laptop']);
  assert.equal(c.retries, 0);
  assert.equal((await load({CI: '1'})).retries, 1);
  assert.equal((await load({})).use.baseURL, 'http://localhost:8787');
});
