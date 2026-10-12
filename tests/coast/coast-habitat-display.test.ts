import test from 'node:test';
import assert from 'node:assert/strict';
import {habitatDisplay,habitatTriangles} from '../../packages/coast/src/coast3d/habitat-display.ts';
import {coastPoint} from '../../packages/coast/src/coast3d/grid.ts';
import {forecastAreaForPlace} from '../../packages/coast/src/coast3d/report.ts';
import {habitatPlace,reportAreaPlace} from '../../packages/coast/src/coast3d/places.ts';
test('coast scale shows habitat while close views reveal compact reefs without changing scores',()=>{assert.equal(habitatDisplay(100000).pins,false);assert.equal(habitatDisplay(30000).mode,'areas');assert.equal(habitatDisplay(16000).pins,false);assert.equal(habitatDisplay(12000).pins,true);assert.equal(habitatDisplay(4200).mode,'detail');assert.ok(habitatDisplay(100000).fillOpacity>habitatDisplay(4200).fillOpacity);});
test('habitat fill retains holes and never mutates original coordinates',()=>{
 const outer=[[-121,35],[-120.99,35],[-120.99,35.01],[-121,35.01],[-121,35]],hole=[[-120.997,35.003],[-120.997,35.007],[-120.993,35.007],[-120.993,35.003],[-120.997,35.003]],rings=[outer,hole],original=structuredClone(rings),tri=habitatTriangles(rings);
 const area=(ring:number[][])=>{const p=ring.map(c=>coastPoint(c[0],c[1]));return Math.abs(p.slice(1).reduce((sum,b,i)=>sum+p[i][0]*b[1]-b[0]*p[i][1],0)/2);};
 let actual=0;for(let i=0;i<tri.length;i+=9){const [ax,,az,bx,,bz,cx,,cz]=tri.slice(i,i+9);actual+=Math.abs((bx-ax)*(cz-az)-(bz-az)*(cx-ax))/2;}
 assert.ok(Math.abs(actual-(area(outer)-area(hole)))<.01);assert.deepEqual(rings,original);
});
test('SLO forecasts never acquire Monterey or Conception bindings',()=>{assert.equal(forecastAreaForPlace('morro'),'central');assert.equal(forecastAreaForPlace('cambria'),'north');assert.equal(forecastAreaForPlace('avila'),'south');for(const place of ['monterey','carmel','point-sur','big-sur','gorda','arguello','conception','coast'])assert.equal(forecastAreaForPlace(place),null);});

test('ranked reef and shore jumps retain published region geography rather than the preceding SLO forecast',()=>{
 assert.equal(habitatPlace('monterey-point-sur',-121.94,36.32),'point-sur');assert.equal(habitatPlace('monterey-point-sur',-121.96,36.52),'carmel');assert.equal(habitatPlace('point-arguello-conception',-120.47,34.455),'conception');assert.equal(habitatPlace('morro-bay',-121,35.45),'morro');assert.equal(reportAreaPlace('north'),'cambria');assert.equal(reportAreaPlace('south'),'avila');
 for(const region of ['monterey-point-sur','point-arguello-conception','unknown'])assert.equal(forecastAreaForPlace(habitatPlace(region,-121,35.35)),null);assert.equal(habitatPlace('morro-bay',NaN,35.35),'coast');
});
