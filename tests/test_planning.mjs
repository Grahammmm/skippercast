import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import {pointInGeometry,geometryIntersects,circleGeometry} from "../dist/geo-screen.js";
import {validMPAs} from "../dist/protected-areas.js";
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
test("official local MPA snapshot is complete and published reef targets stay outside",()=>{
  const data=JSON.parse(fs.readFileSync(new URL("../dist/data/protected-areas.geojson",import.meta.url)));
  assert.equal(validMPAs(data),true);
  assert.equal(validMPAs({...data,features:[]}),false);
  const atlas=JSON.parse(fs.readFileSync(new URL("../dist/data/atlas.json",import.meta.url)));
  for(const t of atlas.targets) assert.ok(!data.features.some(f=>pointInGeometry([t.longitude,t.latitude],f.geometry)),t.id);
  for(const g of [...atlas.areas,...atlas.drifts]) assert.ok(!data.features.some(f=>geometryIntersects(g.geometry,f.geometry)),g.id);
});
