import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import {landWaterModel} from '../web/land-water.ts';
import {closureHits, geometryCoveredByBounds} from '../dist/geo-screen.js';
import {buildProtectedRoute} from '../web/protected-route.ts';
import {createPlanner} from '../web/planner.ts';

const coast = JSON.parse(readFileSync(new URL('./fixtures/land-water/coast.json', import.meta.url)));
const model = landWaterModel({...coast, bounds: [-12110000,3530000,-12075000,3555000], tiles: {'12/671/1616': 'w1024'}}, 'fixture');
const lon = x => (671 + x / 32) / 4096 * 360 - 180;
const lat = y => Math.atan(Math.sinh(Math.PI * (1 - 2 * (1616 + y / 32) / 4096))) * 180 / Math.PI;
const point = (x,y) => ({longitude: lon(x), latitude: lat(y)});
const polygon = (x0,y0,x1,y1) => ({type:'Polygon',coordinates:[[[lon(x0),lat(y0)],[lon(x1),lat(y0)],[lon(x1),lat(y1)],[lon(x0),lat(y1)],[lon(x0),lat(y0)]]]});
const now = new Date('2026-11-07T17:00:00Z'), checked = now.toISOString();
const bounds = [lon(0),lat(32),lon(32),lat(0)];
function screen(geometries = [polygon(13,8,19,24)]) {
  const features = geometries.map(geometry => ({geometry}));
  return {ready:()=>true, exportExclusions:()=>({checked_at:checked,features}),
    coversGeometry:g=>geometryCoveredByBounds(g,bounds),
    geometryAllowed:g=>geometryCoveredByBounds(g,bounds) && !closureHits([g],features).length};
}
const args = (s=screen()) => ({model,lines:null,screen:s,stops:[point(5,16),point(27,16)],title:'A & B <plan>',now});

test('detours around a polygon, keeps the 70 m margin on every full segment, exports a GPX route not a track', () => {
  const s=screen(), r=buildProtectedRoute(args(s));
  assert.ok(r.points.length>2);
  assert.deepEqual(r.points[0],point(5,16));
  assert.deepEqual(r.points.at(-1),point(27,16));
  for(let i=1;i<r.points.length;i++) assert.ok(s.geometryAllowed({type:'LineString',coordinates:[r.points[i-1],r.points[i]].map(p=>[p.longitude,p.latitude])}));
  assert.match(r.gpx,/<rte>/); assert.match(r.gpx,/<rtept lat=/); assert.doesNotMatch(r.gpx,/<trk/);
  assert.match(r.gpx,/A &amp; B &lt;plan&gt;/); assert.match(r.gpx,/NOT FOR NAVIGATION/);
  assert.match(r.gpx,/2026-11-07T17:00:00.000Z/); assert.match(r.gpx,/wildlife.ca.gov/); assert.match(r.gpx,/fisheries.noaa.gov/);
});

test('MultiPolygon barriers and polygon holes are screened, no straight-line fallback', () => {
  const s=screen([{type:'MultiPolygon',coordinates:[polygon(13,0,19,32).coordinates]}]);
  assert.throws(()=>buildProtectedRoute(args(s)),/route.*unavailable/i);
  const g=polygon(0,0,32,32); g.coordinates.push(polygon(3,3,29,29).coordinates[0]);
  assert.ok(buildProtectedRoute(args(screen([g]))).points.length>=2,'both stops in a large hole');
});

test('refuses blocked endpoints, stale/missing boundaries, out-of-envelope geometry, unavailable water and budgets', () => {
  const a=args();
  assert.throws(()=>buildProtectedRoute({...a,stops:[point(16,16),point(27,16)]}),/stop/i);
  assert.throws(()=>buildProtectedRoute({...a,screen:{...a.screen,ready:()=>false}}),/boundar/i);
  assert.throws(()=>buildProtectedRoute({...a,now:new Date('2026-11-09T17:00:00Z')}),/boundar/i);
  assert.throws(()=>buildProtectedRoute({...a,screen:{...a.screen,exportExclusions:()=>null}}),/boundar/i);
  assert.throws(()=>buildProtectedRoute({...a,stops:[point(-1,16),point(27,16)]}),/stop/i);
  assert.throws(()=>buildProtectedRoute({...a,model:null}),/route.*unavailable/i);
  assert.throws(()=>buildProtectedRoute({...a,maxNodes:1}),/route.*unavailable/i);
  for(const stops of [[point(5,16)],Array(13).fill(point(5,16)),[point(NaN,0),point(5,16)]]) assert.throws(()=>buildProtectedRoute({...a,stops}));
});

test('route includes intermediate stops in order; a changed screen does not reuse a prior clear route', () => {
  const stops=[point(5,5),point(27,5),point(27,27)], s=screen([]);
  const r=buildProtectedRoute({...args(s),stops});
  let at=-1;
  for(const p of stops) {const next=r.points.findIndex((q,i)=>i>at && q.longitude===p.longitude && q.latitude===p.latitude);assert.ok(next>at);at=next;}
  buildProtectedRoute(args(screen([])));
  assert.throws(()=>buildProtectedRoute(args(screen([polygon(13,0,19,32)]))),/route.*unavailable/i);
});


test('planner exports the real avoid-polygon route after the normal waypoint gates', async () => {
  const base=screen(), s={...base,pointAllowed:p=>base.geometryAllowed({type:'Point',coordinates:[p.longitude,p.latitude]})};
  const region={id:'fixture',timezone:'America/Los_Angeles',mpa:{bounds}};
  const targets=[point(5,16),point(27,16)].map((p,i)=>({...p,id:`user:p${i}`,name:`Stop ${i}`,category:'other'}));
  const raw=JSON.stringify({ids:targets.map(p=>p.id),userWaypoints:targets,name:'Detour',date:'2026-11-07'});
  const p=createPlanner({atlas:{targets:[],areas:[]},screen:s,region,now:()=>now,
    map:{getSize:()=>({x:512}),getBounds:()=>({getWest:()=>bounds[0],getSouth:()=>bounds[1],getEast:()=>bounds[2],getNorth:()=>bounds[3]})},
    getVisible:()=>[],storage:{getItem:()=>raw,setItem(){}},landWater:async()=>()=>({state:'water'}),
    routeContext:async()=>({model,lines:null}),loadPorts:async()=>null,emit(){},nav:{open(){},showMap(){},conditions(){}}});
  try {
    const file=await p.exportRouteFile();
    assert.equal(file.type,'application/gpx+xml');assert.match(file.name,/-planning-route.gpx$/);
    assert.match(await file.text(),/<rte>/);assert.match(p.routeStatus.value,/Boundary check: 2026-11-07/);
    const {launchPoints} = await import('../web/launches.ts');
    try {
      launchPoints.value = {region: 'fixture', points: [{id: 'ramp', name: 'Ramp', ...point(5,5)}]};
      p.setLaunch(true);
      assert.equal(p.moveStop('user:p1', 'up'), true);
      const gpx = await (await p.exportRouteFile()).text();
      const positions = [...gpx.matchAll(/<rtept lat="([^"]+)" lon="([^"]+)"/g)].map(m => ({latitude: Number(m[1]), longitude: Number(m[2])}));
      assert.ok(positions[0].latitude === point(5,5).latitude && positions[0].longitude === point(5,5).longitude, 'planning route starts at launch');
      const middle = positions.findIndex(q => q.latitude === targets[1].latitude && q.longitude === targets[1].longitude);
      assert.ok(middle > 0 && middle < positions.length - 1, 'moved stop follows launch');
      assert.ok(positions.at(-1).latitude === targets[0].latitude && positions.at(-1).longitude === targets[0].longitude, 'remaining ids retain moved order');
    } finally { p.setLaunch(false); launchPoints.value = null; }
    s.ready=()=>false;
    await assert.rejects(p.exportRouteFile(),/Protected-area checks/);
  } finally {p.dispose();}
});
