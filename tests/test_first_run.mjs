import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

// first-run.js imports the ratings stack, which reads the region at load.
globalThis.REGIONS = undefined;
const { FIRST_RUN_KEY, PRESETS, pendingStep, startFirstRun, advance, finish, savePreset, answerHTML } = await import('../dist/first-run.js');
const { BOAT_KEY, boatFactors, savedBoat } = await import('../dist/boat-handling.js');
const { pacificEpoch } = await import('../dist/forecast.js');

function memory() {
  const data = new Map();
  return { getItem: (k) => (data.has(k) ? data.get(k) : null), setItem: (k, v) => data.set(k, String(v)), removeItem: (k) => data.delete(k), data };
}

test('the port chooser and first-run share one storage key', () => {
  const source = fs.readFileSync(new URL('../dist/home-port.js', import.meta.url), 'utf8');
  assert.match(source, new RegExp(`FIRST_RUN_KEY = '${FIRST_RUN_KEY}'`));
  assert.match(source, /localStorage\.setItem\(FIRST_RUN_KEY, 'boat'\)/);
});

test('steps run harbor → boat → answer, then stop; blocked storage never throws', () => {
  const s = memory();
  assert.equal(pendingStep(s), null);
  startFirstRun(s); assert.equal(pendingStep(s), 'boat');
  advance(s); assert.equal(pendingStep(s), 'answer');
  advance(s); assert.equal(pendingStep(s), null);
  s.setItem(FIRST_RUN_KEY, 'garbage'); assert.equal(pendingStep(s), null);
  startFirstRun(s); finish(s); assert.equal(pendingStep(s), null);
  const blocked = { getItem() { throw new Error('denied'); }, setItem() { throw new Error('denied'); }, removeItem() { throw new Error('denied'); } };
  assert.equal(pendingStep(blocked), null);
  assert.equal(startFirstRun(blocked), false);
  assert.equal(savePreset('skiff', blocked), false);
});

test('presets save a valid profile that scales ratings; smaller boats get lower thresholds', () => {
  const sizes = PRESETS.map((p) => {
    const s = memory();
    assert.equal(savePreset(p.id, s), true);
    const saved = JSON.parse(s.getItem(BOAT_KEY));
    assert.equal(saved.schema_version, 1);
    assert.equal(saved.preset, p.id);
    return boatFactors(saved.boat).sea;
  });
  for (let i = 1; i < sizes.length; i++) assert.ok(sizes[i] > sizes[i - 1], 'larger presets tolerate more sea');
  assert.equal(savePreset('yacht', memory()), false);
});

test('the answer leads with one word, keeps caveats behind Why? and escapes names', () => {
  const t = pacificEpoch('2026-09-30T05:00');
  const go = { verdict: 'go', departFrom: t, backBy: t + 6 * 3600, limit: { text: 'NW 18 kt after 11 a.m.' }, confidence: 'High', agreement: 'GFS and ECMWF agree', windows: [] };
  const html = answerHTML(go, { pointName: 'Estero <Bay>', boatName: 'Skiff "A"' });
  assert.match(html, /STEP 3 OF 3/);
  assert.match(html, />Go<\/h1>/);
  assert.match(html, /be back by 11 a\.m\./);
  assert.ok(html.includes('ESTERO &LT;BAY&GT;'));
  assert.ok(html.includes('Skiff &quot;A&quot;'));
  const [before] = html.split('<details class="first-run-why">');
  assert.doesNotMatch(before, /not a routed trip|safety certification/);
  assert.match(html, /<summary>Why\?<\/summary>.*not a routed trip/s);
  assert.match(answerHTML({ ...go, verdict: 'no-go', backBy: null }), /Limit: NW 18 kt after 11 a\.m\./);
  assert.match(answerHTML({ ...go, verdict: 'unknown' }), /No usable forecast yet/);
  assert.equal(answerHTML(null), '');
});
