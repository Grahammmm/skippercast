// SP-15-v1: independently authored synthetic integration tests, no planner imports.
import test, {after, mock} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import fsp from 'node:fs/promises';
import net from 'node:net';
import http from 'node:http';
import https from 'node:https';
import tls from 'node:tls';
import dns from 'node:dns';
import cp from 'node:child_process';
import {fileURLToPath} from 'node:url';
import path from 'node:path';

// Install before ANY product import. The dependency closure is pure: score,
// verdict, forecast-grid, surface-field and coast graders/nearshore helpers.
// No store/database client or bound I/O default is imported by that closure.
const denied = () => { throw new Error('SP1501_OFFLINE_SENTINEL'); };
const fixturePath = fileURLToPath(new URL('./fixtures/sp1501_chop_completeness/calm.json', import.meta.url));
const originalRead = fs.readFileSync.bind(fs);
const originalOpen = fs.openSync.bind(fs);
const originalAsyncRead = fsp.readFile.bind(fsp);
const repoRoot = fs.realpathSync(fileURLToPath(new URL('../', import.meta.url)));
// The clone's own node_modules may be a symlink to another checkout: its real
// directory is the only extra root admitted. Missing/unresolvable => no extra root.
const dependencyRoot = (() => {
  try { return fs.realpathSync(path.join(repoRoot, 'node_modules')); } catch { return null; }
})();
const inside = (root, target) => {
  const relative = path.relative(root, target);
  return relative !== '' && relative !== '..' && !relative.startsWith(`..${path.sep}`) && !path.isAbsolute(relative);
};
// Pure admission: lexical AND real path must each sit in the clone or the
// dependency root (independently), and the real path is a regular source file.
const admit = (roots, lexical, real, isFile) => {
  if (typeof lexical !== 'string' || typeof real !== 'string' || isFile !== true) return false;
  const within = target => roots.some(root => inside(root, target));
  return within(lexical) && within(real) && /\.(?:ts|js|mjs|json)$/.test(real);
};
const roots = [repoRoot, dependencyRoot].filter(Boolean);
// Node's ESM/type-stripping loader needs read-only source access.
const readable = value => {
  try {
    const name = value instanceof URL ? fileURLToPath(value) : value;
    if (typeof name !== 'string') return false;
    const lexical = path.resolve(name);
    if (!roots.some(root => inside(root, lexical))) return false;
    const real = fs.realpathSync(name);
    return admit(roots, lexical, real, fs.statSync(real).isFile());
  } catch {
    return false;
  }
};
const readOnlyOptions = options => !(options && typeof options === 'object' && options.flag !== undefined && options.flag !== 'r');
mock.method(fs, 'readFileSync', (path, ...args) => {
  if (!readable(path) || !readOnlyOptions(args[0])) return denied();
  return originalRead(path, ...args);
});
mock.method(fs, 'openSync', (path, flags, ...args) => {
  if (flags !== 'r' || !readable(path)) return denied();
  return originalOpen(path, flags, ...args);
});
mock.method(fsp, 'readFile', (path, ...args) => {
  if (!readable(path) || !readOnlyOptions(args[0])) return denied();
  return originalAsyncRead(path, ...args);
});
for (const name of ['writeFileSync', 'appendFileSync', 'mkdirSync', 'renameSync', 'unlinkSync', 'rmSync', 'createWriteStream', 'createReadStream', 'readFile', 'writeFile', 'open']) mock.method(fs, name, denied);
for (const name of ['writeFile', 'appendFile', 'open', 'mkdir', 'rename', 'unlink', 'rm']) mock.method(fsp, name, denied);
mock.method(globalThis, 'fetch', denied); // Includes network-backed model APIs.
for (const [object, names] of [[net, ['connect', 'createConnection']], [net.Socket.prototype, ['connect']], [http, ['request', 'get']], [https, ['request', 'get']], [tls, ['connect']], [dns, ['lookup', 'resolve']], [cp, ['spawn', 'spawnSync', 'exec', 'execSync', 'execFile', 'execFileSync', 'fork']]]) {
  for (const name of names) mock.method(object, name, denied);
}
after(() => mock.restoreAll());
const {rateComfort, comfortCosts, REFERENCE_BOAT, THRESHOLDS} = await import('../web/score.ts');
const {briefVerdict, feedReader, ALERT_CHECK_MISSING} = await import('../web/brief/verdict.ts');
const fixture = JSON.parse(fs.readFileSync(fixturePath, 'utf8'));
const calm = fixture.feed;
const now = new Date(fixture.clock.now);

function limited(period, over = {}) {
  const rating = rateComfort({...calm, ...over, chop_period: period});
  assert.ok(rating);
  assert.equal(rating.limited, true);
  assert.ok(rating.score <= 6.9);
  assert.equal(rating.chop, over.chop ?? calm.chop);
  assert.equal(rating.costs.short, 0);
  return rating;
}

// This IDENTICAL pair runs red on the unchanged module and green after repair.
test('primary regression', () => {
  const rating = rateComfort({...calm, chop_period: null});
  assert.deepEqual({limited: rating.limited, score: rating.score}, {limited: true, score: 6.9}, 'A1_MISSING_CHOP_PERIOD_MUST_USE_LIMITED_PATH');
});
test('healthy control', () => {
  const rating = rateComfort(calm);
  assert.deepEqual({score: rating.score, limited: rating.limited}, {score: 10, limited: false});
});

const focused = process.env.SP1501_SUITE === 'baseline' ? () => {} : test;
focused('A1-A2 missing and non-finite periods use the existing limited path', () => {
  assert.equal(THRESHOLDS.capLimited, 6.9);
  for (const period of [null, undefined, NaN, Infinity, -Infinity]) {
    assert.equal(limited(period).score, 6.9);
  }
  const omitted = {...calm};
  delete omitted.chop_period;
  assert.equal(rateComfort(omitted).limited, true);
  assert.equal(limited(null, {wind: 35, other_wind: 35, gust: 45, other_gust: 45}).score, 0);
});

focused('A3 appreciable chop retains valid full-rubric penalties, never invents a period', () => {
  // Independent numeric expectations: (1 - 0.4) * 0.9 = 0.54 chop
  // charge; short period adds 0.8. Rounded scores are 9.5 and 8.7.
  for (const [period, score, short] of [[8, 9.5, 0], [6, 8.7, 0.8], [4, 8.7, 0.8]]) {
    const r = rateComfort({...calm, chop: 1, chop_period: period});
    assert.deepEqual([r.limited, r.score, r.costs.short], [false, score, short]);
    assert.ok(Math.abs(r.costs.chop - 0.54) < 1e-12);
  }
  for (const period of [null, undefined, NaN, Infinity, -Infinity]) {
    const r = limited(period, {chop: 1});
    assert.deepEqual([r.score, r.uncapped, r.costs.chop, r.costs.short], [6.9, 9.5, 0.54, 0]);
    // The exported cost helper also must not call an absent/nonfinite period
    // a zero-second wave, even when a legacy caller invokes it directly.
    const c = {wind: 2, gust: 3, sea: {height: 1}, chop: {height: 1, period}, swell: {height: 1, from: 300}, secondary: {height: 0, from: 200}};
    assert.equal(comfortCosts(c, {wind: 2, sea: {height: 1}}, 3, REFERENCE_BOAT).costs.short, 0);
  }
});

function forecast(period, {oneMissing = false, chop = 0.1} = {}) {
  const times = Array.from({length: 48}, (_, i) => Date.parse(fixture.clock.start) / 1000 + i * 3600);
  const run = (id, fields) => ({id, issued: now.getTime() / 1000 - 4 * 3600, end: times.at(-1), data: {
    utc_offset_seconds: 0,
    hourly_units: {time: 'unixtime', ...Object.fromEntries(fields.map(([key, , unit]) => [key, unit]))},
    hourly: {time: times, ...Object.fromEntries(fields.map(([key, value]) => [key, times.map((_, i) => key === 'wind_wave_period' && oneMissing ? (i === 9 ? null : 8) : value)]))},
  }});
  return {region: 'synthetic-offline', retrieved: now.getTime(), point: {id: 'synthetic-offline', lat: 35, lon: -121}, models: {
    gfs_global: run('gfs_global', [['wind_speed_10m', 2, 'kn'], ['wind_gusts_10m', 3, 'kn'], ['wind_direction_10m', 315, '°']]),
    ecmwf_ifs025: run('ecmwf_ifs025', [['wind_speed_10m', 2, 'kn'], ['wind_gusts_10m', 3, 'kn']]),
    ncep_gfswave016: run('ncep_gfswave016', [['wave_height', 1, 'ft'], ['wave_period', 12, 's'], ['wind_wave_height', chop, 'ft'], ['wind_wave_period', period, 's'], ['swell_wave_height', 1, 'ft'], ['swell_wave_period', 12, 's'], ['swell_wave_direction', 300, '°'], ['secondary_swell_wave_height', 0, 'ft'], ['secondary_swell_wave_direction', 200, '°']]),
    ecmwf_wam: run('ecmwf_wam', [['wave_height', 1, 'ft']]),
  }};
}
function brief(over = {}) {
  return {profile: 'boat', date: fixture.clock.date, sunrise: fixture.clock.sunrise, sunset: fixture.clock.sunset, alerts: [], missing: [], bar: null, shore: null, spear: null, kayak: null, tiles: [], ...over};
}
const verdict = (f, over) => briefVerdict(brief(over), f, now, fixture.clock.timezone);

focused('A4 complete brief consumer exposes partial detail and preserves healthy output', () => {
  const healthy = verdict(forecast(8));
  assert.deepEqual([healthy.verdict, healthy.score, healthy.held, healthy.window], ['comfortable', 10, null, '8 am–noon']);
  for (const period of [null, NaN, Infinity, -Infinity]) {
    const f = forecast(period);
    const feed = feedReader(f, now);
    assert.equal(feed.read(Date.parse('2026-10-13T16:00:00Z')).chop_period, null);
    const v = verdict(f);
    assert.deepEqual([v.verdict, v.score, v.held], ['marginal', 6.9, 'Held at Marginal: forecast detail is partial.']);
    assert.doesNotMatch(v.limit, /short, steep/);
  }
  const mixed = verdict(forecast(8, {oneMissing: true}));
  assert.deepEqual([mixed.verdict, mixed.score, mixed.held], ['marginal', 6.9, 'Held at Marginal: forecast detail is partial.']);
  assert.equal(verdict(forecast(4, {chop: 1})).score, 8.7);
});

focused('A4 advisory and hazard precedence remain intact for complete and partial forecasts', () => {
  for (const period of [8, null]) {
    const f = forecast(period);
    const alert = verdict(f, {alerts: [{event: 'Small Craft Advisory'}]});
    assert.deepEqual([alert.verdict, alert.score, alert.held], ['rough', null, null]);
    assert.match(alert.limit, /^Small Craft Advisory in effect\./);
    const noCheck = verdict(f, {missing: [ALERT_CHECK_MISSING]});
    assert.equal(noCheck.verdict, 'marginal');
    assert.match(noCheck.held, /marine alert check is unavailable/);
    const bar = verdict(f, {bar: {hazardous: [{at: '2026-10-13T16:00:00Z'}]}});
    assert.equal(bar.verdict, 'marginal');
    assert.match(bar.held, /bar estimate reads hazardous at 9 am/);
  }
});

focused('offline network, model and live-store sentinels are active', () => {
  for (const invoke of [() => globalThis.fetch('https://synthetic.invalid'), () => net.connect(), () => cp.spawn('synthetic-only'), () => fs.readFileSync('synthetic-live-store'), () => fsp.writeFile('synthetic-live-store', '')]) {
    assert.throws(invoke, /SP1501_OFFLINE_SENTINEL/);
  }
  // own_dependency_alias_and_realpath_read
  const alias = path.join(repoRoot, 'node_modules', 'preact', 'package.json');
  const aliasText = fs.readFileSync(alias, 'utf8');
  assert.equal(aliasText, fs.readFileSync(fs.realpathSync(alias), 'utf8'));
  assert.equal(JSON.parse(aliasText).name, 'preact');
  assert.equal(JSON.parse(fs.readFileSync(fixturePath, 'utf8')).feed.chop_period, calm.chop_period);
  assert.equal(fs.readFileSync(fixturePath, {encoding: 'utf8', flag: 'r'}), fs.readFileSync(fixturePath, 'utf8'));
  // dependency_source_suffixes_only, path_escape_and_prefix_siblings_denied (pure, synthetic paths)
  const R = [path.resolve('/sp1501/clone'), path.resolve('/sp1501/deps-real')];
  const ok = (lexical, real = lexical, isFile = true) => admit(R, lexical, real, isFile);
  for (const accepted of ['/sp1501/clone/web/a.ts', '/sp1501/clone/x.js', '/sp1501/deps-real/p/i.mjs', '/sp1501/deps-real/p/package.json']) assert.equal(ok(accepted), true, accepted);
  assert.equal(ok('/sp1501/clone/node_modules/p/package.json', '/sp1501/deps-real/p/package.json'), true, 'clone alias into the dependency root');
  for (const refused of ['/sp1501/deps-real/.bin/x.sqlite', '/sp1501/clone/a.cjs', '/sp1501/clone/a.JSON', '/sp1501/clone/a.d.ts.map', '/sp1501/clone', '/sp1501/deps-real', '/sp1501/clone-evil/a.ts', '/sp1501/deps-real-evil/a.js', '/sp1501/clone/../elsewhere/a.ts', '/sp1501/other/a.json']) assert.equal(ok(path.resolve(refused)), false, refused);
  assert.equal(ok('/sp1501/clone/a.ts', '/sp1501/clone/a.ts', false), false, 'directory');
  assert.equal(ok('/sp1501/clone/link.ts', '/sp1501/outside/real.ts'), false, 'in-clone symlink escaping both roots');
  assert.equal(ok('/sp1501/outside/alias.ts', '/sp1501/clone/real.ts'), false, 'external alias pointing inward');
  assert.equal(ok('/sp1501/clone/a.ts', null), false, 'unresolved realpath');
  assert.equal(admit(R, 5, '/sp1501/clone/a.ts', true), false, 'fd');
  assert.equal(readable(path.join(repoRoot, 'no-such-sp1501-file.json')), false, 'missing file');
  assert.equal(readable(repoRoot), false, 'root directory');
  assert.equal(readable(Buffer.from(fixturePath)), false, 'buffer');
  assert.equal(readable(3), false, 'fd number');
  assert.equal(readable(new URL('http://synthetic.invalid/a.json')), false, 'non-file URL');
  assert.equal(readable(path.join(repoRoot, 'package-lock.json.bak')), false, 'suffix');
  // writes_cannot_hide_as_reads: refused before delegation (the fixture must stay untouched)
  assert.throws(() => fs.readFileSync(fixturePath, {flag: 'w'}), /SP1501_OFFLINE_SENTINEL/);
  assert.throws(() => fsp.readFile(fixturePath, {flag: 'a'}), /SP1501_OFFLINE_SENTINEL/);
  for (const flags of ['w', 'r+', 0, 1, 2]) assert.throws(() => fs.openSync(fixturePath, flags), /SP1501_OFFLINE_SENTINEL/);
  assert.equal(typeof fsp.readFile(fixturePath, 'utf8').then, 'function');
  for (const invoke of [() => dns.lookup('synthetic.invalid'), () => dns.resolve('synthetic.invalid'), () => http.request('http://synthetic.invalid'), () => https.get('https://synthetic.invalid'), () => tls.connect(443), () => cp.exec('synthetic-only'), () => fs.writeFileSync(fixturePath, ''), () => fs.rmSync(fixturePath), () => fsp.rm(fixturePath), () => fsp.mkdir('synthetic-live-store')]) {
    assert.throws(invoke, /SP1501_OFFLINE_SENTINEL/);
  }
});
