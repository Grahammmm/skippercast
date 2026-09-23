import test from 'node:test';
import assert from 'node:assert/strict';
import {modelURLs,morningRows,gridDistanceNm} from '../dist/coastal-forecast.js';

test('statewide model requests use the chosen map location and independent model pairs',()=>{
  for(const [lat,lon] of [[41.7,-124.5],[38.2,-123.1],[36.6,-122.1],[34.1,-119.3],[32.6,-117.2]]){
    const urls=modelURLs(lat,lon);
    assert.equal(new URL(urls.wind).searchParams.get('latitude'),lat.toFixed(2));
    assert.equal(new URL(urls.wave).searchParams.get('longitude'),lon.toFixed(2));
    assert.equal(new URL(urls.wind).searchParams.get('models'),'ecmwf_ifs025,gfs_global');
    assert.equal(new URL(urls.wave).searchParams.get('models'),'ecmwf_wam025,ncep_gfswave025');
    assert.equal(new URL(urls.wave).searchParams.get('cell_selection'),'sea');
  }
  assert.throws(()=>modelURLs(20,-110));
  assert.ok(gridDistanceNm({latitude:36.25,longitude:-121.9},{latitude:36.25,longitude:-122})<6);
  assert.equal(gridDistanceNm({latitude:36.25,longitude:-121.9},{latitude:null,longitude:-122}),Infinity);
});

test('missing fields and contradictory gusts stay visible in coastwide outlook',()=>{
  const time=Array.from({length:7},(_,i)=>`2026-09-24T${String(i+7).padStart(2,'0')}:00`);
  const wind={timezone:'America/Los_Angeles',hourly:{time,wind_speed_10m_ecmwf_ifs025:[5,5,5,5,5,5,5],wind_speed_10m_gfs_global:[4,4,4,4,4,4,4],wind_gusts_10m_ecmwf_ifs025:[7,7,7,3,7,7,7],wind_gusts_10m_gfs_global:[6,6,6,null,6,6,6]}};
  const wave={timezone:'America/Los_Angeles',hourly:{time,wave_height_ecmwf_wam025:[2,2,2,2,2,2,2],wave_height_ncep_gfswave025:[2,2,2,2,2,2,2]}};
  const rows=morningRows(wind,wave,new Date('2026-09-23T15:00:00Z'));
  assert.equal(rows.length,1);
  assert.equal(rows[0].date,'2026-09-24');
  assert.equal(rows[0].gust[1],null);
  assert.ok(rows[0].flags.includes('incomplete model coverage'));
  assert.ok(rows[0].flags.includes('gust below sustained wind'));
  assert.deepEqual(morningRows({...wind,timezone:'UTC'},wave,new Date('2026-09-23T15:00:00Z')),[]);
});
