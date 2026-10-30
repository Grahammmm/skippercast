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

test('live capture of a fixture page records sizes, url, requests and card text', {skip: !hasChromium && 'chromium not installed'}, async () => {
  const out = scratch();
  const page = '<title>Fixture</title><div class="app-mark"><h2>Fixture contour</h2></div><div class="app-legend"><span class="app-swatch" data-layer="depth-contours">Contours</span></div>';
  const receipt = await capture({mode: 'live', origin: 'https://fixture.invalid', region: 'r1', out,
    fulfil: {'https://fixture.invalid/map?region=r1&presentation=chart&ui=v2': {status: 200, contentType: 'text/html', body: page}}});
  assert.equal(receipt.url, 'https://fixture.invalid/map?region=r1&presentation=chart&ui=v2');
  assert.deepEqual(receipt.viewports.map(v => [v.width, v.height, v.visualInspection]), [[390, 844, 'not-visually-inspected'], [360, 800, 'not-visually-inspected']]);
  for (const v of receipt.viewports) assert.equal(v.screenshotSha256, sha(readFileSync(join(out, v.screenshot))));
  assert.ok(receipt.requests.some(r => r.url === receipt.url && r.outcome === 'fulfilled'));
  assert.equal(receipt.textChecks.find(c => c.selector === '.app-mark').text, 'Fixture contour');
  assert.equal(JSON.parse(readFileSync(join(out, 'capture-receipt.json'), 'utf8')).schema, 'region-phone-capture-v1');
  await assert.rejects(capture({mode: 'live', origin: 'https://fixture.invalid', region: 'r1', out, fulfil: {}}), /overwrite/);
});

test('held capture shows banner and datum, and blocks a non-local image', {skip: !hasChromium && 'chromium not installed'}, async () => {
  const run = heldRun();
  const html = readFileSync(PREVIEW, 'utf8').replace('</body>', '<img src="https://tiles.example.invalid/x.png"></body>');
  const receipt = await capture({mode: 'held', run, out: join(scratch(), 'phone'), fulfil: {'http://held.localhost/': {status: 200, contentType: 'text/html', body: html}}});
  const text = selector => receipt.textChecks.find(c => c.viewport === '390x844' && c.selector === selector).text;
  assert.equal(text('#held-banner'), 'Held, not published, not for navigation');
  assert.match(text('.contour-card'), /vertical_datum: unverified source datum/);
  assert.deepEqual(receipt.pageErrors, []);
  assert.ok(receipt.blockedRequests.includes('https://tiles.example.invalid/x.png'));
});
