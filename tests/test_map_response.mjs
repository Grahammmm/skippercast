import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {mappedPackageAt,revisionCache,habitatGroups} from '../dist/map-response.js';
import {pointInGeometry} from '../dist/geo-screen.js';
import {coastURL} from '../dist/coasts.js';
const read=p=>JSON.parse(fs.readFileSync(new URL(p,import.meta.url)));
test('Central selector opens real grounds; panning a guide into a mapped area resumes its package',()=>{
  const catalog=read('../dist/data/coasts.json'),central=catalog.regions.find(r=>r.id==='central');
  assert.equal(coastURL('https://skippercast.com/?coast=central',central,{target:'reef'}).search,'?region=morro-bay&target=reef');
  const packages=read('../dist/regions/index.json').regions.filter(r=>central.packages.includes(r.id));
  assert.equal(mappedPackageAt({latitude:35.4,longitude:-121},packages,10).id,'morro-bay');
  assert.equal(mappedPackageAt({latitude:35.6,longitude:-121.15},packages,10).id,'cambria-san-simeon');
  assert.equal(mappedPackageAt({latitude:35.4,longitude:-121},packages,7),null);
  assert.equal(mappedPackageAt({latitude:36.5,longitude:-122},packages,10).id,'monterey-point-sur');
});
test('closure cache reuses identical geometry but invalidates on changed data or freshness',()=>{
  let revision='fresh-1',calls=0,allowed=true;const cached=revisionCache(()=>revision,()=>{calls++;return allowed;});const polygon={};
  assert.equal(cached(polygon),true);assert.equal(cached(polygon),true);assert.equal(calls,1);
  revision='fresh-2';allowed=false;assert.equal(cached(polygon),false);assert.equal(calls,2);
  revision='stale';assert.equal(cached(polygon),false);assert.equal(calls,3);
});
test('fast point rejection preserves holes and boundary exclusion semantics',()=>{
  const polygon={type:'Polygon',coordinates:[[[0,0],[10,0],[10,10],[0,10],[0,0]],[[3,3],[7,3],[7,7],[3,7],[3,3]]]};
  assert.equal(pointInGeometry([-1,2],polygon),false);assert.equal(pointInGeometry([1,2],polygon),true);
  assert.equal(pointInGeometry([5,5],polygon),false);assert.equal(pointInGeometry([3,5],polygon),true);assert.equal(pointInGeometry([0,5],polygon),true);
});
test('overview clusters group habitat bounds without inventing fishing records',()=>{
  const entries=[[5,5],[10,8],[200,200]].map(([x,y])=>({bounds:{getCenter:()=>({x,y})}}));
  const groups=habitatGroups(entries,p=>p);assert.deepEqual(groups.map(g=>g.length),[2,1]);assert.equal(groups.flat().length,entries.length);
});
