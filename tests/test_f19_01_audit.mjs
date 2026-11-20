import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {existsSync, mkdtempSync, readFileSync, rmSync, statSync, symlinkSync, writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import test from 'node:test';
import {fileURLToPath} from 'node:url';

const SENTINEL = 'F19-01.TEST-ONLY.PAGE-CREDENTIAL';
const cli = new URL('../scripts/advisor/meta-token.mjs', import.meta.url);

if (process.argv[2] === '--fixture') {
  const [scenario, ...args] = process.argv.slice(3);
  const json = (body, status = 200) => new Response(JSON.stringify(body), {status});
  let exchanges = 0;
  // Every call stays in this child, including errors from the shared Graph client.
  globalThis.fetch = async url => {
    const {pathname} = new URL(url);
    if (pathname.endsWith('/oauth/access_token')) return json({access_token: `synthetic-user-${++exchanges}`});
    if (pathname.endsWith('/me/accounts')) return json({data: [{id: '101', access_token: SENTINEL, instagram_business_account: {id: '202'}}]});
    if (pathname.endsWith('/202')) return json({account_type: scenario === 'creator' ? 'MEDIA_CREATOR' : 'BUSINESS'});
    if (pathname.endsWith('/content_publishing_limit')) {
      return scenario === 'api-error' ? json({error: {code: 190, message: SENTINEL}}, 400) : json({data: [{quota_usage: 0}]});
    }
    if (pathname.endsWith('/debug_token')) return json({data: {expires_at: 0}});
    throw new Error('unexpected synthetic request path');
  };
  process.argv = [process.execPath, fileURLToPath(cli), ...args];
  await import(cli.href);
} else {
  function run(scenario, args) {
    const result = spawnSync(process.execPath, [fileURLToPath(import.meta.url), '--fixture', scenario, ...args], {
      input: 'SYNTHETIC_AUTHORIZATION_CODE\n', encoding: 'utf8', timeout: 5000,
      env: {META_APP_ID: '303', META_APP_SECRET: 'synthetic-app-secret'},
    });
    assert.ifError(result.error);
    assert.equal(result.signal, null);
    assert.ok(!result.stdout.includes(SENTINEL), 'stdout must not contain the Page credential');
    assert.ok(!result.stderr.includes(SENTINEL), 'stderr must not contain the Page credential');
    return result;
  }

  function destination(t) {
    const dir = mkdtempSync(join(tmpdir(), 'f19-01-'));
    t.after(() => rmSync(dir, {recursive: true, force: true}));
    return join(dir, 'page-token');
  }

  test('missing destination fails before interactive setup with no credential on either stream', () => {
    const result = run('business', []);
    assert.equal(result.status, 1);
    assert.match(result.stderr, /--token-file/);
    assert.equal(result.stdout, '');
  });

  test('successful setup writes the exact credential only to a new owner-only file', t => {
    const path = destination(t);
    const result = run('business', ['--token-file', path]);
    assert.equal(result.status, 0, result.stderr);
    assert.match(result.stdout, /META_PAGE_ID\s+101/);
    assert.match(result.stdout, /META_IG_USER_ID\s+202/);
    assert.equal(result.stderr, '');
    const info = statSync(path);
    assert.ok(info.isFile());
    assert.equal(info.mode & 0o777, 0o600);
    assert.equal(readFileSync(path, 'utf8'), SENTINEL);
  });

  for (const [scenario, diagnostic] of [['creator', /not BUSINESS/], ['api-error', /HTTP 400 code 190/]]) {
    test(`${scenario} failure leaves no credential file or stream output containing it`, t => {
      const path = destination(t);
      const result = run(scenario, ['--token-file', path]);
      assert.equal(result.status, 1);
      assert.match(result.stdout + result.stderr, diagnostic);
      assert.equal(existsSync(path), false);
    });
  }

  test('setup never overwrites a file or follows a symlink at the destination', t => {
    const path = destination(t);
    writeFileSync(path, 'existing bytes');
    const link = `${path}.link`;
    symlinkSync(path, link);
    for (const output of [path, link]) {
      const result = run('business', ['--token-file', output]);
      assert.equal(result.status, 1);
      assert.match(result.stderr, /new owner-only file/);
      assert.equal(readFileSync(path, 'utf8'), 'existing bytes');
    }
  });
}
