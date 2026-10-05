// The admin app's fleet routes (CF-31, web/admin/route.ts): parsing, the nav entry a route marks, and the flag gating.
import test from 'node:test';
import assert from 'node:assert/strict';

const {routeOf, navOf, visibleViews, shownRoute, VIEWS, FLEET_VIEWS} = await import('../web/admin/route.ts');
const ID = 'a'.repeat(32);

test('routeOf: fleet views with a valid region, vessel details by 32-hex id, anything else the queue', () => {
  assert.deepEqual(routeOf('#fleet-review'), {view: 'fleet-review', arg: ''});
  assert.deepEqual(routeOf('#fleet-vessels?region=CA'), {view: 'fleet-vessels', arg: 'CA'});
  assert.deepEqual(routeOf('#fleet-review?region=%3Cx%3E'), {view: 'fleet-review', arg: ''});
  assert.deepEqual(routeOf(`#fleet-vessel/${ID}`), {view: 'fleet-vessel', arg: ID});
  for (const hash of ['#fleet-vessel/abc', `#fleet-vessel/${ID}/x`, '#fleet-vessel/', '#fleet-review/x', '#constructor/x'])
    assert.equal(routeOf(hash).view, 'queue', hash);
});

test('navOf marks a contact as Skippers and a vessel as Vessels', () => {
  assert.equal(navOf('contact'), 'skippers');
  assert.equal(navOf('fleet-vessel'), 'fleet-vessels');
  assert.equal(navOf('fleet-review'), 'fleet-review');
});

test('visibleViews and shownRoute hide the fleet while its flag is off', () => {
  assert.deepEqual(visibleViews({advisor: true, fleet: false}), [...VIEWS]);
  assert.deepEqual(visibleViews({advisor: false, fleet: true}), [...FLEET_VIEWS]);
  assert.deepEqual(shownRoute(routeOf(`#fleet-vessel/${ID}`), {advisor: true, fleet: false}), {view: 'queue', arg: ''});
  assert.deepEqual(shownRoute(routeOf('#health'), {advisor: false, fleet: true}), {view: 'fleet-review', arg: ''});
  assert.equal(shownRoute(routeOf('#queue'), {advisor: false, fleet: false}), null);
});
