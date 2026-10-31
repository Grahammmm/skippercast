import test from 'node:test';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {existsSync, mkdtempSync, mkdirSync, readFileSync, writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {dirname, join, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {capture, heldRequestPlan, inspectionState, outsideRepo, parseArgs} from '../skills/skippercast-region-review/scripts/phone_capture.mjs';

const REPO = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const PREVIEW = join(REPO, 'skills/skippercast-region-review/scripts/held-preview.html');
const scratch = () => mkdtempSync(join(tmpdir(), 'phone-capture-'));
const sha = bytes => createHash('sha256').update(bytes).digest('hex');

async function chromiumPresent() {
  try { return existsSync((await import('@playwright/test')).chromium.executablePath()); } catch { return false; }
}
const hasChromium = await chromiumPresent();
const LIVE = ['.app-top-card .app-location', '.app-sheet-head', '.maplibregl-canvas', '.maplibregl-ctrl-attrib'];

function heldRun() {
  const run = scratch();
  mkdirSync(join(run, 'held'));
  writeFileSync(join(run, 'held', 'a.geojson'), JSON.stringify({
    type: 'FeatureCollection',
    provenance: {region_id: 'fixture-region', sources: [{name: 'Fixture survey', survey_date: '2019', vertical_datum: 'unverified source datum'}], held_sources: [{source_id: 'fx', review_status: 'candidate'}]},
    features: [
      {type: 'Feature', properties: {kind: 'contour', depth_ft: 30, index: false}, geometry: {type: 'MultiLineString', coordinates: [[[-122.5, 37.5], [-122.49, 37.51]], [[-122.5, 37.52], [-122.48, 37.53]]]}},
    ],
  }));
  return run;
}

test('pure helpers: request plan, repo containment, inspection state', () => {
  const run = '/run';
  assert.equal(heldRequestPlan('http://held.localhost/held/../x.geojson', run).action, 'block');
  assert.equal(heldRequestPlan('http://held.localhost/held/A.GEOJSON', run).action, 'block');
  assert.equal(heldRequestPlan('https://tiles.example.invalid/x.png', run).action, 'block');
  assert.deepEqual(heldRequestPlan('http://held.localhost/held/a.geojson', run), {action: 'fulfil', file: '/run/held/a.geojson'});
  assert.equal(outsideRepo(join(REPO, 'phone')), false);
  assert.equal(outsideRepo(scratch()), true);
  assert.throws(() => parseArgs(['--mode', 'held', '--run', '/run', '--out', join(REPO, 'phone')]), /outside the repo/);
  const receipt = {viewports: [{screenshot: 'held-390x844.png', screenshotSha256: 'a'.repeat(64)}, {screenshot: 'held-360x800.png', screenshotSha256: 'b'.repeat(64)}]};
  const review = `Looked at held-390x844.png (${'a'.repeat(64)}) and held-360x800.png without a hash.`;
  assert.deepEqual(inspectionState(receipt, review), {'held-390x844.png': 'cited-in-review', 'held-360x800.png': 'not-visually-inspected'});
});

test('repo-contained dot-dot-prefixed output directories are refused', () => {
  const out = join(REPO, '..phone');
  assert.equal(outsideRepo(out), false);
  assert.throws(() => parseArgs(['--mode', 'held', '--run', '/run', '--out', out]), /outside the repo/);
});

test('live capture of a fixture page records sizes, url, requests and card text', {skip: !hasChromium && 'chromium not installed'}, async () => {
  const out = scratch();
  const page = '<title>Fixture</title><div class="app-top-card"><span class="app-location">MORRO BAY 35.34N 120.97W</span></div><div class="app-sheet-head">Today</div><canvas class="maplibregl-canvas"></canvas><div class="maplibregl-ctrl-attrib">© OSM</div>';
  const receipt = await capture({mode: 'live', origin: 'https://fixture.invalid', region: 'r1', out,
    fulfil: {'https://fixture.invalid/map?region=r1&presentation=chart&ui=v2': {status: 200, contentType: 'text/html', body: page}}});
  assert.equal(receipt.url, 'https://fixture.invalid/map?region=r1&presentation=chart&ui=v2');
  assert.deepEqual(receipt.viewports.map(v => [v.width, v.height, v.visualInspection]), [[390, 844, 'not-visually-inspected'], [360, 800, 'not-visually-inspected']]);
  for (const v of receipt.viewports) assert.equal(v.screenshotSha256, sha(readFileSync(join(out, v.screenshot))));
  assert.ok(receipt.requests.some(r => r.url === receipt.url && r.outcome === 'fulfilled'));
  for (const sel of LIVE) assert.equal(receipt.textChecks.find(c => c.viewport === '390x844' && c.selector === sel).count, 1, sel);
  assert.equal(receipt.textChecks.find(c => c.viewport === '390x844' && c.selector === '.app-top-card .app-location').text, 'MORRO BAY 35.34N 120.97W');
  assert.deepEqual(receipt.failedResponses, []);
  assert.deepEqual(receipt.consoleErrors, []);
  assert.equal(JSON.parse(readFileSync(join(out, 'capture-receipt.json'), 'utf8')).schema, 'region-phone-capture-v1');
  await assert.rejects(capture({mode: 'live', origin: 'https://fixture.invalid', region: 'r1', out, fulfil: {}}), /overwrite/);
});

test('live capture of a broken page finds no live selectors and lists the console error and 404', {skip: !hasChromium && 'chromium not installed'}, async () => {
  const body = '<title>Broken</title><script>console.error(\'boom\')</script><img src="https://fixture.invalid/missing.png">';
  const receipt = await capture({mode: 'live', origin: 'https://fixture.invalid', region: 'r2', out: scratch(), fulfil: {
    'https://fixture.invalid/map?region=r2&presentation=chart&ui=v2': {status: 200, contentType: 'text/html', body},
    'https://fixture.invalid/missing.png': {status: 404, body: 'nf'}}});
  for (const sel of LIVE) assert.equal(receipt.textChecks.find(c => c.viewport === '390x844' && c.selector === sel).count, 0, sel);
  assert.ok(receipt.consoleErrors.some(e => e.viewport === '390x844' && e.text === 'boom'));
  assert.ok(receipt.failedResponses.some(r => r.viewport === '390x844' && r.url === 'https://fixture.invalid/missing.png' && r.status === 404));
});

test('held capture shows banner and datum, and blocks a non-local image', {skip: !hasChromium && 'chromium not installed'}, async () => {
  const run = heldRun();
  const html = readFileSync(PREVIEW, 'utf8').replace('</body>', '<img src="https://tiles.example.invalid/x.png"></body>');
  const receipt = await capture({mode: 'held', run, out: join(scratch(), 'phone'), fulfil: {'http://held.localhost/': {status: 200, contentType: 'text/html', body: html}}});
  const text = selector => receipt.textChecks.find(c => c.viewport === '390x844' && c.selector === selector).text;
  assert.equal(text('#held-banner'), 'Held, not published, not for navigation');
  assert.match(text('.contour-card'), /vertical_datum: unverified source datum/);
  assert.deepEqual(receipt.pageErrors, []);
  assert.ok(Array.isArray(receipt.failedResponses));
  // The deliberately blocked image is the only console error (Chromium logs the aborted load).
  assert.ok(receipt.consoleErrors.length > 0 && receipt.consoleErrors.every(e => /ERR_BLOCKED_BY_CLIENT/.test(e.text)));
  assert.ok(receipt.blockedRequests.includes('https://tiles.example.invalid/x.png'));
});

test('clean held preview has no console errors or failed responses', {skip: !hasChromium && 'chromium not installed'}, async () => {
  const receipt = await capture({mode: 'held', run: heldRun(), out: join(scratch(), 'phone')});
  assert.deepEqual(receipt.consoleErrors, []);
  assert.deepEqual(receipt.failedResponses, []);
});

function candidateRun() {
  const run = heldRun(); // keeps a planted held/a.geojson that candidate mode must never request
  mkdirSync(join(run, 'candidate'));
  writeFileSync(join(run, 'candidate', 'x.geojson'), readFileSync(join(run, 'held', 'a.geojson')));
  return run;
}

test('candidate mode: arguments and request plan serve only candidate/', () => {
  const R = '/run', u = 'http://held.localhost';
  assert.equal(parseArgs(['--mode', 'candidate', '--run', R]).out, join(R, 'REVIEW-PACKET', 'phone-candidate'));
  assert.equal(parseArgs(['--mode', 'held', '--run', R]).out, join(R, 'REVIEW-PACKET', 'phone'));
  assert.throws(() => parseArgs(['--mode', 'candidate']), /^Error: candidate mode needs --run$/);
  assert.throws(() => parseArgs(['--mode', 'candidate', '--run', R, '--out', join(REPO, 'phone')]), /outside the repo/);
  for (const mode of ['Candidate', 'published', 'candidate ']) assert.throws(() => parseArgs(['--mode', mode, '--run', R]), /^Error: --mode must be live, held or candidate$/, mode);
  assert.deepEqual(heldRequestPlan(`${u}/candidate/a.geojson`, R, 'candidate'), {action: 'fulfil', file: '/run/candidate/a.geojson'});
  assert.equal(heldRequestPlan(`${u}/?dir=candidate&files=a.geojson`, R, 'candidate').action, 'fulfil');
  for (const p of ['/held/a.geojson', '/candidate/../held/a.geojson', '/candidate/A B.geojson', '/candidate/a.geojson/../../x.geojson'])
    assert.deepEqual(heldRequestPlan(u + p, R, 'candidate'), {action: 'block', status: 404}, p);
  assert.deepEqual(heldRequestPlan(`${u}/candidate/a.geojson`, R), {action: 'block', status: 404});
  assert.deepEqual(heldRequestPlan('https://example.com/x', R, 'candidate'), {action: 'block'});
  assert.throws(() => heldRequestPlan(`${u}/x/a.geojson`, R, 'x'), /dir must be held or candidate/);
});

test('candidate capture refuses a missing, empty or non-geojson candidate/ before launching or creating --out', async () => {
  for (const files of [null, [], ['A.GEOJSON', 'notes.txt']]) {
    const run = heldRun();
    if (files) { mkdirSync(join(run, 'candidate')); for (const f of files) writeFileSync(join(run, 'candidate', f), '{}'); }
    const out = join(scratch(), 'phone-candidate');
    await assert.rejects(capture({mode: 'candidate', run, out}), {message: `candidate mode needs ${join(run, 'candidate')} with at least one .geojson`});
    assert.equal(existsSync(out), false);
  }
});

test('candidate capture renders candidate/ at both sizes under the candidate banner', {skip: !hasChromium && 'chromium not installed'}, async () => {
  const run = candidateRun(), out = join(scratch(), 'phone-candidate');
  const receipt = await capture({mode: 'candidate', run, out});
  assert.equal(receipt.mode, 'candidate');
  assert.equal(receipt.schema, 'region-phone-capture-v1');
  assert.equal(receipt.url, 'http://held.localhost/?dir=candidate&files=x.geojson');
  assert.deepEqual(receipt.viewports.map(v => [v.screenshot, v.width, v.height]), [['candidate-390x844.png', 390, 844], ['candidate-360x800.png', 360, 800]]);
  for (const v of receipt.viewports) assert.equal(v.screenshotSha256, sha(readFileSync(join(out, v.screenshot))));
  for (const vp of ['390x844', '360x800']) {
    const check = selector => receipt.textChecks.find(c => c.viewport === vp && c.selector === selector);
    assert.equal(check('#held-banner').text, 'Candidate, not yet published, not for navigation');
    assert.equal(check('.contour-card').count, 1);
    assert.match(check('.contour-card').text, /x\.geojson/);
  }
  assert.deepEqual([receipt.pageErrors, receipt.failedResponses, receipt.consoleErrors], [[], [], []]);
  assert.ok(receipt.requests.some(r => r.url === 'http://held.localhost/candidate/x.geojson' && r.outcome === 'fulfilled'));
  assert.ok(!receipt.requests.some(r => new URL(r.url).pathname.startsWith('/held/')));
  await assert.rejects(capture({mode: 'candidate', run, out}), /refusing to overwrite/);
});
