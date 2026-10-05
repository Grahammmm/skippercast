// Charter fleet trip labelling (CF-48; docs/plans/charter-fleet/design.md § 11 Validation, § 13 Labelling).
// The label functions run against the real migrations (tests/_advisor_d1.mjs); the admin routes go
// through the Worker with the test session helper and the job route with the fleet job verifier
// stubbed. Synthetic throughout: invented boats, 999xxxxxx MMSIs, made-up admin and agent ids.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {advisorDatabase, sqliteUnavailable} from './_advisor_d1.mjs';
import {withSessions} from './fixtures/test-sessions.mjs';

const read = p => JSON.parse(readFileSync(new URL(p, import.meta.url)));
globalThis.REGIONS = {'morro-bay': read('../regions/morro-bay/region.json')};
globalThis.DEPLOYMENT = read('../deployments/production.json');
globalThis.SHELLS = {'/': '/index.0123456789.html', '/admin.html': '/admin.0123456789.html'};
globalThis.BUILD_ID = 'build-test';
const {default: deployed} = await import('../server/index.ts');
const {fleetJobs} = await import('../server/routes/fleet.ts');
const labels = await import('../server/fleet/admin/labels.ts');
const {routeOf, navOf, FLEET_VIEWS, fleetTripHref} = await import('../web/admin/route.ts');
const worker = withSessions(deployed);

const skip = sqliteUnavailable ?? false;
const ORIGIN = 'https://skippercast.com', ADMIN = 'admin-fleet-48';
const ASSETS = {fetch: async () => new Response('asset', {status: 299})};
const ON = {FLEET_ENABLED: 'true'};
const T0 = '2026-10-05T09:00:00.000Z', NOW = '2026-10-05T18:00:00.000Z';
const at = min => new Date(Date.parse(T0) + min * 60000).toISOString();
const hex = c => c.repeat(32);
const V1 = hex('a'), V2 = hex('b'), TRIP = hex('1'), OPEN = hex('2'), OREGON = hex('3'), BARE = hex('4');

/** Google encoded polyline, precision 5, from [lon, lat] pairs. */
function encode(points) {
  let out = '', lat = 0, lon = 0;
  const one = v => { v = v < 0 ? ~(v << 1) : v << 1; while (v >= 0x20) { out += String.fromCharCode((0x20 | (v & 0x1f)) + 63); v >>= 5; } out += String.fromCharCode(v + 63); };
  for (const [x, y] of points) { const la = Math.round(y * 1e5), lo = Math.round(x * 1e5); one(la - lat); one(lo - lon); lat = la; lon = lo; }
  return out;
}

function seed(sql) {
  sql.prepare("INSERT INTO users(id,created_at,role) VALUES(?,?,'admin')").run(ADMIN, T0);
  const vessel = sql.prepare(`INSERT INTO fleet_vessels(id,region,slug,name,name_norm,port_id,vessel_class,first_seen_at,last_seen_at,created_at,updated_at)
    VALUES(?,?,?,?,?,?,?,?,?,?,?)`);
  vessel.run(V1, 'CA', 'test-boat-1', 'Test Boat 1', 'TESTBOAT1', 'port-a', 'six-pack', T0, T0, T0, T0);
  vessel.run(V2, 'OR', 'test-boat-2', 'Test Boat 2', 'TESTBOAT2', 'port-b', 'inspected-party', T0, T0, T0, T0);
  const trip = sql.prepare(`INSERT INTO fleet_trips(id,region,vessel_id,mmsi,depart_port_id,return_port_id,departed_at,returned_at,local_date,season,status,
    distance_nm,max_offshore_nm,fishing_min,positions_n,gap_min,source,rights,classifier_version,computed_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)`);
  trip.run(TRIP, 'CA', V1, '999000481', 'port-a', 'port-a', at(0), at(120), '2026-10-05', '2026', 'closed', 12.5, 4.2, 70, 120, 0, 'aisstream', 'internal-only', 'c1-test', NOW);
  trip.run(OPEN, 'CA', V1, '999000481', 'port-a', null, at(300), null, '2026-10-05', '2026', 'open', 3, 1.1, 0, 20, 0, 'aisstream', 'internal-only', 'c1-test', NOW);
  trip.run(OREGON, 'OR', V2, '999000482', 'port-b', 'port-b', at(-600), at(-400), '2026-10-04', '2026', 'closed', 8, 3, 40, 90, 0, 'marinecadastre', 'noaa-planning-only', 'c1-test', NOW);
  trip.run(BARE, 'CA', V1, '999000481', 'port-a', 'port-a', at(-1440), at(-1300), '2026-10-04', '2026', 'closed', 5, 2, 0, 50, 0, 'aisstream', 'internal-only', 'c1-test', NOW);
  const seg = sql.prepare(`INSERT INTO fleet_segments(id,trip_id,seq,kind,started_at,ended_at,geometry,points_n,mean_sog,straightness,heading_var) VALUES(?,?,?,?,?,?,?,?,?,?,?)`);
  seg.run(hex('5'), TRIP, 0, 'transit', at(0), at(30), encode([[-150, 10], [-149.9, 10.05]]), 30, 8.1, 0.95, 0.02);
  seg.run(hex('6'), TRIP, 1, 'fishing-drift', at(30), at(90), encode([[-149.9, 10.05], [-149.91, 10.06]]), 60, 0.6, 0.2, 0.7);
  seg.run(hex('7'), TRIP, 2, 'transit', at(90), at(120), null, 30, 7.9, 0.97, 0.01);
  seg.run(hex('8'), OPEN, 0, 'transit', at(300), at(340), null, 40, 7, 0.9, 0.05);
  const lab = sql.prepare('INSERT INTO fleet_segment_labels(id,trip_id,started_at,ended_at,label,labeller,basis,created_at) VALUES(?,?,?,?,?,?,?,?)');
  lab.run(hex('c'), OREGON, at(-590), at(-500), 'fishing-troll', 'agent:test', 'skipper log', NOW);
}
const database = () => { const d = advisorDatabase(); seed(d.sql); return d; };
const iso = (v, min) => ({started_at: at(v), ended_at: at(min)});

test('acceptance 2: a label records its labeller and basis; ranges stay inside the trip and never overlap', {skip}, async () => {
  const {sql, db} = database();
  const ok = await labels.addLabel(db, TRIP, {...iso(30, 90), label: 'fishing-drift', basis: '  track shape  '}, ADMIN, NOW);
  assert.equal(ok.status, 'ok');
  const stored = sql.prepare('SELECT * FROM fleet_segment_labels WHERE trip_id=?').get(TRIP);
  assert.deepEqual({...stored}, {id: ok.value.label.id, trip_id: TRIP, started_at: at(30), ended_at: at(90), label: 'fishing-drift',
    labeller: ADMIN, basis: 'track shape', created_at: NOW});
  assert.match(stored.id, /^[0-9a-f]{32}$/);
  // A second-precision time is normalised; an agent set carries agent:<name>.
  const agent = await labels.addLabel(db, TRIP, {started_at: '2026-10-05T09:00:00Z', ended_at: at(30), label: 'transit', basis: 'skipper log'}, 'agent:test', NOW);
  assert.equal(agent.status, 'ok');
  assert.deepEqual(agent.value.labels.map(l => [l.label, l.labeller, l.started_at]), [['transit', 'agent:test', at(0)], ['fishing-drift', ADMIN, at(30)]]);

  const bad = async (input, status = 'invalid', trip = TRIP) => {
    const r = await labels.addLabel(db, trip, input, ADMIN, NOW);
    assert.equal(r.status, status, JSON.stringify(input));
    return r;
  };
  await bad({...iso(90, 120), label: 'transit'});                                       // no basis
  await bad({...iso(90, 120), label: 'transit', basis: ' '});
  await bad({...iso(90, 120), label: 'transit', basis: 'x'.repeat(501)});
  await bad({...iso(90, 120), label: 'gap', basis: 'track shape'});                     // gap is the classifier's, not a label
  await bad({...iso(90, 120), label: 'fishing', basis: 'track shape'});
  await bad({...iso(100, 100.5), label: 'transit', basis: 'track shape'});              // under a minute
  await bad({...iso(110, 100), label: 'transit', basis: 'track shape'});
  await bad({...iso(100, 121), label: 'transit', basis: 'track shape'});                // past the return
  await bad({...iso(-1, 10), label: 'transit', basis: 'track shape'});                  // before the departure
  await bad({started_at: '2026-10-05 10:00', ended_at: at(100), label: 'transit', basis: 'track shape'});
  await bad({...iso(90, 120), label: 'transit', basis: 'track shape', labeller: 'someone-else'});   // the labeller is never the caller's to set
  const clash = await bad({...iso(80, 100), label: 'transit', basis: 'track shape'}, 'conflict');
  assert.match(clash.error, /overlaps the fishing-drift label/);
  assert.equal((await labels.addLabel(db, hex('9'), {...iso(90, 120), label: 'transit', basis: 'x y'}, ADMIN, NOW)).status, 'not-found');
  assert.equal((await labels.addLabel(db, TRIP, {...iso(90, 120), label: 'transit', basis: 'x y'}, '', NOW)).status, 'invalid');
  // An open trip is labelled up to its last segment's end.
  assert.equal((await labels.addLabel(db, OPEN, {...iso(300, 340), label: 'transit', basis: 'track shape'}, ADMIN, NOW)).status, 'ok');
  await bad({...iso(340, 350), label: 'transit', basis: 'track shape'}, 'invalid', OPEN);
  assert.equal(sql.prepare('SELECT count(*) n FROM fleet_segment_labels').get().n, 4);

  const removed = await labels.deleteLabel(db, ok.value.label.id);
  assert.equal(removed.status, 'ok');
  assert.deepEqual(removed.value.labels.map(l => l.label), ['transit']);
  assert.equal((await labels.deleteLabel(db, ok.value.label.id)).status, 'not-found');
});

test('the trip list, progress and detail: tracks decoded, every AIS-derived value marked inferred from movement', {skip}, async () => {
  const {db} = database();
  await labels.addLabel(db, TRIP, {...iso(30, 90), label: 'fishing-drift', basis: 'track shape'}, ADMIN, NOW);
  await labels.addLabel(db, TRIP, {...iso(90, 120), label: 'transit', basis: 'track shape'}, ADMIN, NOW);

  const all = await labels.listTrips(db, {});
  assert.deepEqual(all.trips.map(t => [t.id, t.labels]), [[OPEN, 0], [TRIP, 2], [OREGON, 1], [BARE, 0]]);
  assert.equal(all.trips[1].vessel_name, 'Test Boat 1');
  assert.deepEqual(all.progress, {trips: 2, labels: 3, by_labeller: {admin: 2, agent: 1}, ports: 2,
    minutes: {'in-port': 0, 'transit': 30, 'fishing-drift': 60, 'fishing-troll': 90}, target_trips: 30});
  const ca = await labels.listTrips(db, {region: 'CA', labelled: 'no'});
  assert.deepEqual(ca.trips.map(t => t.id), [OPEN, BARE]);
  assert.deepEqual(ca.progress.by_labeller, {admin: 2, agent: 0});
  assert.deepEqual((await labels.listTrips(db, {region: 'CA', labelled: 'yes'})).trips.map(t => t.id), [TRIP]);
  assert.deepEqual(await labels.listTrips(db, {labelled: 'maybe'}), {error: 'labelled must be all, yes or no'});
  assert.deepEqual(await labels.listTrips(db, {region: '../x'}), {error: 'invalid region'});
  assert.deepEqual(await labels.listTrips(db, {cursor: 'x'}), {error: 'invalid cursor'});
  // Paging: a cursor past the second trip.
  const rest = await labels.listTrips(db, {cursor: `${at(0)}~${TRIP}`});
  assert.deepEqual(rest.trips.map(t => t.id), [OREGON, BARE]);

  const detail = await labels.tripDetail(db, TRIP);
  assert.equal(detail.basis, 'inferred-from-movement');
  assert.deepEqual(detail.window, {from: at(0), to: at(120)});
  assert.deepEqual(detail.label_kinds, ['in-port', 'transit', 'fishing-drift', 'fishing-troll']);
  assert.deepEqual(detail.segments.map(s => [s.kind, s.mean_sog, s.coordinates]),
    [['transit', 8.1, [[-150, 10], [-149.9, 10.05]]], ['fishing-drift', 0.6, [[-149.9, 10.05], [-149.91, 10.06]]], ['transit', 7.9, []]]);
  assert.ok(!('geometry' in detail.segments[0]));
  assert.deepEqual(detail.labels.map(l => [l.label, l.labeller, l.basis]), [['fishing-drift', ADMIN, 'track shape'], ['transit', ADMIN, 'track shape']]);
  assert.deepEqual((await labels.tripDetail(db, OPEN)).window, {from: at(300), to: at(340)});
  assert.equal(await labels.tripDetail(db, 'nope'), null);

  const view = readFileSync(new URL('../web/admin/fleet-trip.tsx', import.meta.url), 'utf8');
  assert.match(view, /inferred: 'Inferred from movement'/);
  assert.match(view, /fishingMin: 'Fishing min \(inferred from movement\)'/);
  assert.match(view, /segmentsHeading: 'Segments \(inferred from movement\)'/);
  assert.match(view, /never confirmed fishing/);
  assert.doesNotMatch(view, /confirmed fishing'/);
});

test('acceptance 3 (Worker side): the job route lists labelled trips with their labels for the runner\'s copy', {skip}, async () => {
  const {sql, db} = database();
  await labels.addLabel(db, TRIP, {...iso(30, 90), label: 'fishing-drift', basis: 'track shape'}, ADMIN, NOW);
  const saved = fleetJobs.verify;
  fleetJobs.verify = async token => token === 'good' ? {jti: 'run-48'} : false;
  try {
    const call = (query, token = 'good', extra = ON) => worker.fetch(new Request(`${ORIGIN}/api/fleet/jobs/labels?${new URLSearchParams(query)}`,
      {headers: {Authorization: `Bearer ${token}`}}), {ASSETS, DB: db, ...extra});
    assert.equal((await call({region: 'CA'}, 'bad')).status, 401);
    assert.equal((await call({region: 'CA'}, 'good', {})).status, 404, 'fleet off');
    assert.equal((await call({region: '../x'})).status, 400);
    assert.equal((await call({region: 'CA', cursor: 'zz'})).status, 400);
    const ca = await (await call({region: 'CA'})).json();
    assert.deepEqual(ca.trips.map(t => [t.id, t.mmsi, t.source, t.departed_at, t.returned_at, t.labels.map(l => [l.label, l.labeller, l.basis])]),
      [[TRIP, '999000481', 'aisstream', at(0), at(120), [['fishing-drift', ADMIN, 'track shape']]]]);
    assert.equal(ca.next, null);
    const or = await (await call({region: 'OR'})).json();
    assert.deepEqual(or.trips.map(t => [t.id, t.source, t.labels[0].labeller]), [[OREGON, 'marinecadastre', 'agent:test']]);
    assert.deepEqual((await (await call({region: 'CA', cursor: TRIP})).json()).trips, []);
    assert.equal(or.trips[0].orphan, false);
    // A re-run replaced the trip under another id: its labels come back as an orphan on every region's pages.
    sql.prepare('DELETE FROM fleet_trips WHERE id=?').run(TRIP);
    for (const region of ['CA', 'OR']) {
      const page = await (await call({region})).json();
      const orphan = page.trips.find(t => t.id === TRIP);
      assert.deepEqual({...orphan, labels: orphan.labels.length}, {id: TRIP, mmsi: null, vessel_id: null, source: null, departed_at: null,
        returned_at: null, status: null, depart_port_id: null, orphan: true, labels: 1}, region);
    }
  } finally { fleetJobs.verify = saved; }
  // Paging across more than one page.
  const {sql: fresh, db: many} = advisorDatabase();
  seed(fresh);
  const trip = fresh.prepare(`INSERT INTO fleet_trips(id,region,vessel_id,mmsi,departed_at,local_date,season,status,source,rights,classifier_version,computed_at)
    VALUES(?,'CA',?,'999000481',?,'2026-10-01','2026','closed','aisstream','internal-only','c1-test',?)`);
  const lab = fresh.prepare("INSERT INTO fleet_segment_labels(id,trip_id,started_at,ended_at,label,labeller,basis,created_at) VALUES(?,?,?,?,'transit','agent:test','x',?)");
  for (let i = 0; i < labels.JOB_PAGE + 5; i++) {
    const id = i.toString(16).padStart(32, '0');
    trip.run(id, V1, at(-5000 + i), NOW);
    lab.run(id.replace(/^0/, 'e'), id, at(-5000 + i), at(-4999 + i), NOW);
  }
  const first = await labels.labelledTrips(many, 'CA', undefined);
  assert.equal(first.body.trips.length, labels.JOB_PAGE);
  assert.equal(first.body.next, first.body.trips.at(-1).id);
  const second = await labels.labelledTrips(many, 'CA', first.body.next);
  assert.equal(second.body.trips.length, 5);
  assert.equal(second.body.next, null);
});

test('the admin routes: 404 for non-admins and with the fleet off; the labeller is the signed-in admin', {skip}, async () => {
  const {sql, db} = database();
  const get = (path, owner = ADMIN, extra = ON) => worker.fetch(new Request(ORIGIN + path, {headers: owner ? {'x-test-owner': owner} : {}}), {ASSETS, DB: db, ...extra});
  const post = (path, payload, owner = ADMIN, extra = ON) => worker.fetch(new Request(ORIGIN + path, {method: 'POST',
    headers: {'Content-Type': 'application/json', Origin: ORIGIN, ...(owner ? {'x-test-owner': owner} : {})}, body: JSON.stringify(payload)}), {ASSETS, DB: db, ...extra});
  const body = {...iso(30, 90), label: 'fishing-drift', basis: 'track shape'};
  for (const [path, run] of [['/api/admin/fleet/trips', p => get(p)], [`/api/admin/fleet/trips/${TRIP}`, p => get(p)]]) {
    assert.equal((await get(path, 'someone-else')).status, 404, `non-admin ${path}`);
    assert.equal((await get(path, ADMIN, {})).status, 404, `fleet off ${path}`);
    assert.equal((await get(path, ADMIN, {TEXT_ADVISOR_ENABLED: 'true'})).status, 404, `advisor only ${path}`);
    const ok = await run(path);
    assert.equal(ok.status, 200, path);
    assert.equal(ok.headers.get('Cache-Control'), 'no-store');
  }
  assert.equal((await post(`/api/admin/fleet/trips/${TRIP}/labels`, body, 'someone-else')).status, 404);
  assert.equal((await post(`/api/admin/fleet/trips/${TRIP}/labels`, body, ADMIN, {})).status, 404);
  assert.equal(sql.prepare('SELECT count(*) n FROM fleet_segment_labels WHERE trip_id=?').get(TRIP).n, 0);
  const added = await post(`/api/admin/fleet/trips/${TRIP}/labels`, body);
  assert.equal(added.status, 200);
  const {label} = await added.json();
  assert.equal(label.labeller, ADMIN);
  assert.equal((await post(`/api/admin/fleet/trips/${TRIP}/labels`, body)).status, 409);
  assert.equal((await post(`/api/admin/fleet/trips/${TRIP}/labels`, {...body, basis: ''})).status, 400);
  assert.equal((await post(`/api/admin/fleet/trips/${hex('9')}/labels`, body)).status, 404);
  assert.equal((await get('/api/admin/fleet/trips?labelled=maybe')).status, 400);
  assert.equal((await get(`/api/admin/fleet/trips/${hex('9')}`)).status, 404);
  assert.equal((await post(`/api/admin/fleet/labels/${label.id}/delete`, {}, 'someone-else')).status, 404);
  const deleted = await post(`/api/admin/fleet/labels/${label.id}/delete`, {});
  assert.equal(deleted.status, 200);
  assert.deepEqual((await deleted.json()).labels, []);
});

test('the admin app routes #fleet-labels and #fleet-trip/<id>', () => {
  assert.ok(FLEET_VIEWS.includes('fleet-labels'));
  assert.deepEqual(routeOf(`#fleet-trip/${TRIP}`), {view: 'fleet-trip', arg: TRIP});
  assert.equal(navOf('fleet-trip'), 'fleet-labels');
  assert.deepEqual(routeOf('#fleet-trip/not-a-trip'), {view: 'queue', arg: ''});
  assert.deepEqual(routeOf('#fleet-labels?region=CA'), {view: 'fleet-labels', arg: 'CA'});
  assert.equal(fleetTripHref(TRIP), `#fleet-trip/${TRIP}`);
});
