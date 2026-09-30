// Client telemetry (P4-11): an uncaught error on the map page is reported once
// by web/telemetry.ts, through navigator.sendBeacon to /api/telemetry, with the
// page's build id; the Worker accepts it (204, a no-op without Analytics Engine).
import {test, expect, openMap} from './fixtures.ts';

const MESSAGE = 'e2e injected telemetry error';

test('an injected uncaught error produces one beacon; the map view is a funnel step', async ({page, pageErrors}) => {
  const beacons: string[] = [], statuses: number[] = [];
  page.on('request', request => { if (new URL(request.url()).pathname === '/api/telemetry') beacons.push(request.postData() || ''); });
  page.on('response', response => { if (new URL(response.url()).pathname === '/api/telemetry') statuses.push(response.status()); });
  await openMap(page);
  // The same error twice: the client deduplicates it.
  await page.evaluate(message => { for (let i = 0; i < 2; i++) setTimeout(() => { throw new Error(message); }); }, MESSAGE);
  await expect.poll(() => pageErrors.length).toBe(2);
  pageErrors.splice(0);   // expected here; the fixture fails on any other uncaught error
  // Hiding the page flushes the batch, as leaving it would.
  await page.evaluate(() => dispatchEvent(new PageTransitionEvent('pagehide')));
  await expect.poll(() => beacons.filter(body => body.includes(MESSAGE)).length).toBe(1);
  const body = JSON.parse(beacons.find(b => b.includes(MESSAGE))!);
  expect(body.build).toMatch(/^[0-9a-f]{10}$/);
  const errors = body.events.filter((e: {type: string}) => e.type === 'error');
  expect(errors).toEqual([expect.objectContaining({type: 'error', kind: 'error', message: MESSAGE})]);
  expect(Object.keys(body).sort()).toEqual(['build', 'events']);
  // The map view is a funnel step, sent in this or an earlier batch.
  const steps = beacons.flatMap(b => JSON.parse(b).events).filter((e: {type: string}) => e.type === 'funnel');
  expect(steps).toContainEqual({type: 'funnel', name: 'map_viewed', region: 'morro-bay'});
  await expect.poll(() => statuses.length).toBeGreaterThan(0);
  expect(new Set(statuses)).toEqual(new Set([204]));
  // A second flush has nothing new to send for that error.
  await page.evaluate(() => dispatchEvent(new PageTransitionEvent('pagehide')));
  await page.waitForTimeout(300);
  expect(beacons.filter(b => b.includes(MESSAGE))).toHaveLength(1);
});

test('Global Privacy Control sends nothing', async ({page, pageErrors}) => {
  await page.addInitScript(() => Object.defineProperty(Navigator.prototype, 'globalPrivacyControl', {get: () => true}));
  const beacons: string[] = [];
  page.on('request', request => { if (new URL(request.url()).pathname === '/api/telemetry') beacons.push(request.postData() || ''); });
  await openMap(page);
  await page.evaluate(message => setTimeout(() => { throw new Error(message); }), MESSAGE);
  await expect.poll(() => pageErrors.length).toBe(1);
  pageErrors.splice(0);
  await page.evaluate(() => dispatchEvent(new PageTransitionEvent('pagehide')));
  await page.waitForTimeout(500);
  expect(beacons).toEqual([]);
});
