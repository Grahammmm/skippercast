// Adaptive contours never go finer than 1.5x the grid spacing (packages/coast/src/coast3d/shading.ts).
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {contourInterval,shadingReadout,SPACING_FACTOR,CONTOUR_STEPS_FT} from '../packages/coast/src/coast3d/shading.ts';

const FOOT=.3048,LARGEST=CONTOUR_STEPS_FT.at(-1)*FOOT;
const wholeFoot=(m)=>Math.abs(m/FOOT-Math.round(m/FOOT))<1e-9;

test('coarse_grid_never_uses_a_subfloor_preset',()=>{
  for(const [spacing,floor] of [[200,300],[1000,1500]]){
    const {minor}=contourInterval(10,spacing);
    assert.ok(minor>=floor,`${spacing} m: ${minor} < ${floor}`);
    assert.ok(minor-floor<FOOT+1e-9,`${spacing} m: rounded up by at most a foot`);
    assert.ok(wholeFoot(minor),'whole international foot');
  }
  assert.equal(contourInterval(10,1000).minor,Math.ceil(1500/FOOT)*FOOT);
});

test('preset_floor_boundary_is_inclusive',()=>{
  const spacing=LARGEST/SPACING_FACTOR;
  assert.equal(contourInterval(10,spacing).minor,LARGEST);
  for(const bump of [1e-6,.01,1]){
    const s=spacing+bump,{minor}=contourInterval(10,s);
    assert.ok(minor>=s*SPACING_FACTOR,`+${bump}: ${minor}`);
    assert.ok(minor>LARGEST,'uses the fallback beyond the preset');
  }
});

test('ordinary_presets_and_fallbacks_unchanged',()=>{
  assert.equal(contourInterval(10,2).minor,10*FOOT);
  assert.equal(contourInterval(10,30).minor,250*FOOT);
  for(const bad of [0,-5,NaN,Infinity]) assert.equal(contourInterval(10,bad).minor,10*FOOT,`spacing ${bad}`);
  assert.equal(contourInterval(NaN,NaN).minor,10*FOOT);
  assert.equal(shadingReadout({min:18.6,max:43.3},false,{minor:3.048,index:15.24}),'Ramp 61–142 ft in view · contours 10 ft where the source allows, index 50 ft');
});

test('index_remains_every_fifth_contour',()=>{
  for(const spacing of [0,2,30,200,1000]){
    const {minor,index}=contourInterval(10,spacing);
    assert.ok(Math.abs(index-minor*5)<1e-9,`${spacing}`);
  }
});
