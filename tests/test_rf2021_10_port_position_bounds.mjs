// RF2021-10: a device position outside latitude -90..90 / longitude -180..180 never matches a port
// (periodic trigonometry used to map 360 degrees onto a port at 0,0). Synthetic, in-memory only.
import assert from 'node:assert/strict';
import test from 'node:test';
import {closestPort, locatePort} from '../web/ports.ts';

const port = (id, match) => ({id, name: id, region: id, status: 'active', forecast_point: id, forecast_name: id, match});
const geo = (latitude, longitude) => ({getCurrentPosition: ok => ok({coords: {latitude, longitude}})});

test('out_of_globe_query_never_matches', () => {
  const ports = [port('origin', [0, 0])];
  for (const [lat, lon] of [[360, 0], [0, 360], [-360, 0], [0, -360], [90.0001, 0], [-90.0001, 0], [0, 180.0001], [0, -180.0001]]) {
    assert.equal(closestPort(ports, lat, lon), null, `${lat},${lon}`);
  }
});

test('query_coordinate_boundaries_inclusive', () => {
  for (const [lat, lon] of [[90, 0], [-90, 0], [0, 180], [0, -180]]) {
    const ports = [port('edge', [lat, lon])];
    assert.equal(closestPort(ports, lat, lon)?.id, 'edge', `${lat},${lon}`);
  }
});

test('healthy_nearest_port_and_location_control', async () => {
  const ports = [port('origin', [0, 0])];
  assert.equal(closestPort(ports, 0, 0)?.id, 'origin');
  assert.equal(closestPort(ports, NaN, 0), null);
  assert.equal(closestPort(ports, 0, Infinity), null);
  assert.equal(closestPort([], 0, 0), null);
  assert.deepEqual(await locatePort(ports, geo(360, 0)), {ok: false, reason: 'none'});
  assert.deepEqual(await locatePort(ports, geo(0, 360)), {ok: false, reason: 'none'});
  const located = await locatePort(ports, geo(0, 0));
  assert.ok(located.ok && located.port.id === 'origin');
});
