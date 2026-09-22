import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import {pointInGeometry,geometryIntersects,circleGeometry} from "../dist/geo-screen.js";
import {makeDriftGuide} from "../dist/drift-guides.js";
import {validMPAs} from "../dist/protected-areas.js";
import {atlasExportAllowed} from "../dist/export-screen.js";
const box=(x,y,w)=>({type:"Polygon",coordinates:[[[x,y],[x+w,y],[x+w,y+w],[x,y+w],[x,y]]]});
test("MPA screen includes boundary touches, crossing segments, containment and polygon holes",()=>{
  const a=box(0,0,4);a.coordinates.push([[1,1],[1,3],[3,3],[3,1],[1,1]]);
  assert.equal(pointInGeometry([0,2],a),true);
  assert.equal(pointInGeometry([2,2],a),false);
  assert.equal(pointInGeometry([1,2],a),true);
  assert.equal(geometryIntersects(box(1.2,1.2,.5),a),false);
  assert.equal(geometryIntersects({type:"LineString",coordinates:[[-1,2],[5,2]]},a),true);
  assert.equal(geometryIntersects(box(-1,-1,6),a),true);
  assert.equal(geometryIntersects(box(5,5,1),a),false);
  assert.equal(geometryIntersects(circleGeometry(2,4,.1),a),true);
});
test("current guides start upstream, rotate with direction and do not substitute absent data",()=>{
  const target={latitude:35.36,longitude:-120.96};
  const north=makeDriftGuide(target,1,0),east=makeDriftGuide(target,1,90);
  assert.ok(north.coordinates[0][1]<target.latitude && north.coordinates[2][1]>target.latitude);
  assert.ok(east.coordinates[0][0]<target.longitude && east.coordinates[2][0]>target.longitude);
  assert.deepEqual(north.coordinates[1],[-120.96,35.36]);
  assert.equal(makeDriftGuide(target,null,0),null);
  assert.equal(makeDriftGuide(target,0,0),null);
  assert.equal(makeDriftGuide(target,1,360),null);
  const restriction=box(-120.961,35.3605,.002);
  assert.equal(geometryIntersects(north,restriction),true);
});
test("official local MPA snapshot is complete and published reef targets stay outside",()=>{
  const data=JSON.parse(fs.readFileSync(new URL("../dist/data/protected-areas.geojson",import.meta.url)));
  assert.equal(validMPAs(data),true);
  assert.equal(validMPAs({...data,features:[]}),false);
  const atlas=JSON.parse(fs.readFileSync(new URL("../dist/data/atlas.json",import.meta.url)));
  for(const t of atlas.targets) assert.ok(!data.features.some(f=>pointInGeometry([t.longitude,t.latitude],f.geometry)),t.id);
  for(const g of [...atlas.areas,...atlas.drifts]) assert.ok(!data.features.some(f=>geometryIntersects(g.geometry,f.geometry)),g.id);
});
test("GPX is withheld when any included point or footprint fails the current MPA screen",()=>{
  const atlas={targets:[{id:"a",area_ids:['area']},{id:"b",area_ids:[]}],areas:[{id:'area',target_ids:["a"],geometry:{blocked:true}}],drifts:[]};
  const screen={ready:()=>true,pointAllowed:()=>true,geometryAllowed:g=>!g.blocked};
  assert.equal(atlasExportAllowed(atlas,screen),false);
  assert.equal(atlasExportAllowed(atlas,screen,"a"),false);
  assert.equal(atlasExportAllowed(atlas,screen,"b"),true);
  assert.equal(atlasExportAllowed(atlas,{...screen,ready:()=>false},"b"),false);
  assert.equal(atlasExportAllowed(atlas,{...screen,pointAllowed:()=>false},"b"),false);
});
