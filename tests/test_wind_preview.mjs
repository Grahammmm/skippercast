import test from 'node:test';
import assert from 'node:assert/strict';
import {advance,colour,fresh,sample,validate} from '../web/map/wind-layer.js';
const grid=()=>({schema_version:1,source_id:'noaa-gfs',units:'m/s',width:2,height:2,
  west:-122,north:36,resolution_degrees:.25,max_age_hours:18,
  run_time:'2026-11-07T12:00:00Z',data_time:'2026-11-07T18:00:00Z',
  u:[[0,2],[4,6]],v:[[6,4],[2,0]]});
test('preview bilinear east/north sampling never extrapolates outside crop',()=>{
  const g=validate(grid());
  assert.deepEqual(sample(g,-121.875,35.875),[3,3]);
  assert.deepEqual(sample(g,-121.75,35.75),[6,0]);
  assert.deepEqual(sample(g,-122,36),[0,6]);
  assert.equal(sample(g,-122.001,36),null);
  assert.equal(sample(g,-121.75,35.749),null);
});
test('preview malformed components fail closed, never calm-wind substitution',()=>{
  for(const bad of [null,NaN,Infinity,'1']) {
    const g=grid();g.u[0][0]=bad;assert.throws(()=>validate(g));
  }
  const g=grid();g.v.pop();assert.throws(()=>validate(g));
});
test('preview freshness uses model RUN; future valid and invalid times stay hidden',()=>{
  const g=grid();
  assert.equal(fresh(g,Date.parse('2026-11-07T20:00:00Z')),true);
  assert.equal(fresh(g,Date.parse('2026-11-08T06:00:00.001Z')),false);
  assert.equal(fresh(g,Date.parse('2026-11-07T17:59:59Z')),false);
  assert.equal(fresh({...g,run_time:'bad'},Date.now()),false);
  assert.equal(fresh({...g,data_time:'2026-11-07T11:00:00Z'},Date.parse(g.data_time)),false);
});
test('preview vectors move toward east/north; reference WCM clamps at 0/30 kt',()=>{
  const [lon,lat]=advance(-121,35,4,3,60);
  assert.ok(lon>-121 && lat>35);
  const [west,south]=advance(-121,35,-4,-3,60);
  assert.ok(west<-121 && south<35);
  assert.deepEqual(colour(-1),[59,111,182]);
  assert.deepEqual(colour(30),[176,32,138]);
  assert.deepEqual(colour(50),colour(30));
});
