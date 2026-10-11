import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import { acceptsFeed, setRegion, getRegion, assetURL } from "../dist/region.js";
import { geometryIntersects } from "../dist/geo-screen.js";
const read=p=>JSON.parse(fs.readFileSync(new URL(p,import.meta.url),"utf8"));
const morro=read("../regions/morro-bay/region.json");
const north=read("../regions/cambria-san-simeon/region.json");

test("changing region cannot reuse Morro Bay's legacy catch or observation feed",()=>{
  setRegion(north);
  assert.equal(getRegion().id,"cambria-san-simeon");
  assert.equal(assetURL("charters"),null);
  assert.equal(acceptsFeed({schema_version:1}),false);
  assert.equal(acceptsFeed({region_id:"morro-bay"}),false);
  assert.equal(acceptsFeed({region_id:north.id}),true);
  setRegion(morro);assert.equal(acceptsFeed({schema_version:1}),true);
});

test("San Simeon geological outlines never claim qualified fishing depth and exclude MPAs",()=>{
  const geology=read("../dist/regions/cambria-san-simeon/geology.geojson");
  const mpas=read("../dist/data/protected-areas.geojson");
  assert.ok(geology.features.length>0);
  for(const f of geology.features){assert.equal(f.properties.depth_qualified,false);assert.equal(f.properties.fishing_target,false);assert.ok(mpas.features.every(m=>!geometryIntersects(f.geometry,m.geometry)));}
  const atlas=read("../dist/regions/cambria-san-simeon/atlas.json");assert.equal(atlas.targets.length,0);
});

test("published manifests match their real regional assets",()=>{
  for(const region of [morro,north]){
    const manifest=read(`../dist/regions/${region.id}/manifest.json`);
    assert.equal(manifest.region_id,region.id);
    for(const [key,asset] of Object.entries(manifest.assets))assert.equal(asset.path,region.assets[key]);
  }
});
