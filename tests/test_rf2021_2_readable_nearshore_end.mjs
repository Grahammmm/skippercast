import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
globalThis.REGIONS={};
globalThis.DEPLOYMENT={allowed_origins:['https://skippercast.com']};
const {serveCoastPage}=await import('../server/coast-pages.ts');
const regions=Object.fromEntries(['morro-bay','cambria-san-simeon'].map(id=>[id,JSON.parse(readFileSync(new URL('../regions/'+id+'/region.json',import.meta.url)))]));
const template=readFileSync(new URL('../dist/coast-readable.html',import.meta.url),'utf8');
const now=new Date('2026-10-07T12:00:00Z'),at=now.toISOString(),later='2026-10-07T15:00:00Z';
const base={schemaVersion:1,countyId:'slo',generatedAt:'2026-10-07T11:50:00Z',forecasts:[{id:'central',sourceId:'nws',hours:[{at,windKnots:8,gustKnots:12,waveFt:3,wavePeriodS:12}]}],observations:[],sources:[{id:'nws',label:'NWS',kind:'forecast',outcome:'ok',issuedAt:'2026-10-07T10:00:00Z',fetchedAt:'2026-10-07T11:50:00Z',url:'https://example.test/'}],tides:[],tideEvents:[],alerts:[],catches:[]};
const site=extra=>({areaId:'central',name:'Original CDIP',availability:'available',freshness:'current',issuedAt:'2026-10-07T10:00:00Z',fetchedAt:'2026-10-07T11:50:00Z',temporalResolutionMinutes:180,hours:[{at,waveFt:2,periodS:11},{at:later,waveFt:3,periodS:12}],...extra});
async function page(nearshore,hour='12'){
 const data={...base,nearshore:[nearshore]};
 const response=await serveCoastPage(new Request('https://skippercast.com/report?hour=2026-10-07T'+hour+':00Z'),{template,regions,now,fetcher:async()=>new Response(JSON.stringify(data),{headers:{'Content-Type':'application/json'}})});
 return {status:response.status,html:await response.text()};
}
const shown=html=>html.includes('Original model sample');
test('readable_nearshore_invalid_declared_end_is_gap',async()=>{
 for(const validThrough of ['not-a-date','','   ','2026-02-31T99:00:00Z',5,true,{},[]]){
  const {status,html}=await page(site({validThrough}));
  assert.equal(status,200,JSON.stringify(validThrough));assert.equal(shown(html),false,JSON.stringify(validThrough));
  assert.match(html,/8 \/ 12 kt/);
 }
});
test('readable_nearshore_declared_end_is_inclusive',async()=>{
 for(const [validThrough,present] of [[at,true],['2026-10-07T05:00:00-07:00',true],['2026-10-07T11:59:59.999Z',false]]){
  const {html}=await page(site({validThrough}));assert.equal(shown(html),present,validThrough);
 }
});
test('readable_nearshore_missing_end_keeps_frame_span',async()=>{
 for(const declared of [{validThrough:null},{}]){
  for(const [hour,present] of [['13',true],['11',false],['16',false]]){
   const {html}=await page(site(declared),hour);assert.equal(shown(html),present,hour);
  }
 }
});
test('readable_nearshore_healthy_control',async()=>{
 const input=site({validThrough:later}),copy=structuredClone(input),{html}=await page(input);
 assert.equal(shown(html),true);assert.match(html,/Original model sample <time datetime="2026-10-07T12:00:00.000Z"/);assert.match(html,/Sampling interval 180 minutes/);
 assert.ok(structuredClone(input)&&JSON.stringify(input)===JSON.stringify(copy));
 for(const stale of [{issuedAt:'2026-10-05T10:00:00Z'},{fetchedAt:'2026-10-07T08:00:00Z'}])assert.equal(shown((await page(site({validThrough:later,...stale}))).html),false);
});
