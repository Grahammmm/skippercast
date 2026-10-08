import './coast/coast-embedded.test.ts';
import './coast/coast-embed.test.ts';
import './coast/coast3d.test.ts';
import './coast/coast-regional.test.ts';
import './coast/coast-habitat-display.test.ts';
import './coast/coast-preferences.test.ts';
import './coast/surface-field.test.ts';
import './coast/habitat-lifecycle.test.ts';
import './coast/coast-streaming-seams.test.ts';
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {coastPath} from '../packages/coast/src/transport.ts';
import {coastURL,plannerURL,matchingHour,coastAdmission} from '../packages/coast/src/links.ts';
globalThis.REGIONS={};globalThis.DEPLOYMENT={};
const {shellFor}=await import('../server/routes/assets.ts');
test('coast transport maps only relative public reads to the isolated same-origin bridge',()=>{
 assert.equal(coastPath('/api/report'),'/api/coast/report');
 assert.equal(coastPath('/api/habitat/tiles?region=morro-bay&release='+'a'.repeat(64)),'/api/coast/habitat/tiles?region=morro-bay&release='+'a'.repeat(64));
 assert.equal(coastPath('/data/coast-wide/manifest.json'),'/coast-data/data/coast-wide/manifest.json');
 for(const path of ['https://evil.example/data/a','//evil.example/data/a','/private/a','/api/account','/data/%2e%2e/private','/data/../private'])assert.throws(()=>coastPath(path));
});
test('coast and chart links carry actual location and do not substitute Morro forecasts',()=>{
 assert.equal(coastURL('https://skippercast.com/coast?region=monterey-point-sur').searchParams.get('place'),'monterey');
 assert.equal(coastURL('https://skippercast.com/coast?region=san-diego').searchParams.has('place'),false);
 const next=plannerURL('https://skippercast.com/coast?profile=spear&target=cabezon-shallow-reef&region=morro-bay&hour=2026-10-06T12:00:00.000Z','conception','export');
 assert.equal(next.pathname,'/');assert.equal(next.hash,'#export');assert.equal(next.searchParams.get('region'),'point-arguello-conception');assert.equal(next.searchParams.get('target'),'cabezon-shallow-reef');assert.equal(next.searchParams.get('hour'),'2026-10-06T12:00Z');
});
test('shared hour serialization does not select a different forecast hour',()=>{
 const hours=[{at:'2026-10-06T12:00:00.000Z'}];assert.equal(matchingHour(hours,'2026-10-06T12:00Z'),hours[0].at);assert.equal(matchingHour(hours,'2026-10-06T13:00Z'),null);
});
test('the coastal shell is addressable without switching the incomplete v2 homepage',()=>{
 assert.equal(shellFor('/coast',new URLSearchParams(),{}),'/coast.html');assert.equal(shellFor('/',new URLSearchParams(),{}),'/');assert.equal(shellFor('/map',new URLSearchParams(),{}),null);
});
test('canonical geography wins over conflicting aliases and never falls back for unsupported places',()=>{
 assert.equal(coastURL('https://skippercast.com/coast?region=monterey-point-sur&place=avila').searchParams.get('place'),'monterey');
 assert.equal(coastURL('https://skippercast.com/coast?region=southern-california&place=morro').searchParams.has('place'),false);
 assert.equal(coastURL('https://skippercast.com/coast?region=&place=morro').searchParams.has('place'),false);
 assert.equal(coastURL('https://skippercast.com/coast?coast=north&place=morro').searchParams.has('place'),false);
 assert.equal(coastURL('https://skippercast.com/coast?place=unknown').searchParams.get('place'),'unknown');
 assert.equal(coastURL('https://skippercast.com/coast?region=morro-bay&place=avila').searchParams.get('place'),'avila');
});

test('renderer admission rejects empty and unsupported explicit geography while allowing bare home setup',()=>{
 for(const query of ['region=&place=morro','coast=&place=morro','place=','place=unknown','region=san-diego&place=morro','coast=north'])assert.equal(coastAdmission('https://skippercast.com/coast?'+query),false,query);
 for(const query of ['', 'place=morro','region=monterey-point-sur&place=avila','coast=central','area=north'])assert.equal(coastAdmission('https://skippercast.com/coast?'+query),true,query);
});
import './coast/coast-palette.test.ts';
import './coast/coast-overlays.test.ts';
