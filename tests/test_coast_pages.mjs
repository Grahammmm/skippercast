import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
globalThis.REGIONS={};
globalThis.DEPLOYMENT={allowed_origins:['https://skippercast.com']};
const {serveCoastPage,readableSelection}=await import('../server/coast-pages.ts');
const regions=Object.fromEntries(['morro-bay','cambria-san-simeon'].map(id=>[id,JSON.parse(readFileSync(new URL('../regions/'+id+'/region.json',import.meta.url)))]));
const template=readFileSync(new URL('../dist/coast-readable.html',import.meta.url),'utf8');
const now=new Date('2026-10-07T12:00:00Z'),at=now.toISOString();
const report={schemaVersion:1,countyId:'slo',generatedAt:'2026-10-07T11:50:00Z',forecasts:[{id:'central',sourceId:'nws',hours:[{at,windKnots:8,gustKnots:12,waveFt:3,wavePeriodS:12}]}],observations:[{stationId:'46028',observedAt:'2026-10-07T10:30:00Z',waterTempF:56,waveFt:4,wavePeriodS:10,url:'https://www.ndbc.noaa.gov/'}],sources:[{id:'nws',label:'NWS $& <script>',kind:'forecast',outcome:'ok',issuedAt:'2026-10-07T10:00:00Z',fetchedAt:'2026-10-07T11:50:00Z',url:'javascript:alert(1)'}],tides:[],tideEvents:[],alerts:[],catches:[],nearshore:[{areaId:'central',name:'Original CDIP',availability:'available',freshness:'current',issuedAt:'2026-10-07T10:00:00Z',fetchedAt:'2026-10-07T11:50:00Z',validThrough:'2026-10-07T15:00:00Z',temporalResolutionMinutes:180,hours:[{at,waveFt:2,periodS:11},{at:'2026-10-07T15:00:00Z',waveFt:3,periodS:12}]}]};
const request=(path='/report',init)=>new Request('https://skippercast.com'+path,init);
const options=(data=report)=>({template,regions,now,fetcher:async()=>new Response(JSON.stringify(data),{headers:{'Content-Type':'application/json'}})});
const selection=query=>readableSelection(new URL(request('/report'+query).url),regions,now);

test('default readable report explicitly labels SLO reference without native controls or JS',async()=>{
 const response=await serveCoastPage(request(),options()),html=await response.text();
 assert.equal(response.status,200);assert.match(html,/SLO reference report/);assert.match(html,/Wind \/ gust/);assert.match(html,/8 \/ 12 kt/);assert.doesNotMatch(html,/<script|<select|type=["']range|<canvas/i);assert.match(html,/2026-10-07T11:50:00Z/);assert.match(html,/2026-10-07T10:30:00Z/);
});
test('original Fish aliases preserve profile, target, geographic binding and exact hour',()=>{
 const result=selection('?area=north&mode=spear&species=gopher&hour=2026-10-07T12:00:00Z');
 assert.equal(result.context.regionId,'cambria-san-simeon');assert.equal(result.context.profile,'spear');assert.equal(result.context.target,'gopher');assert.equal(result.context.at.toISOString(),at);assert.match(result.workspace,/region=cambria-san-simeon/);
 for(const place of ['morro','avila','cambria'])assert.ok(selection('?place='+place).context,place);
 assert.equal(selection('?region=morro-bay&place=cambria').context.regionId,'morro-bay');
});
test('missing, unknown, explicit empty, mismatched, ambiguous and unsupported geography never falls back',()=>{
 for(const query of ['?region=','?region=monterey-point-sur','?region=constructor','?place=constructor','?area=constructor','?region=morro-bay&region=cambria-san-simeon','?coast=central','?habitat=123','?region=morro-bay&area=avila&view=35.4,-120.9,10','?region=morro-bay&view=36,-120,10'])assert.equal(selection(query).context,null,query);
 assert.equal(selection('?region=morro-bay&hour=2026-10-07T12:30Z').context,null);
 assert.equal(selection('?region=morro-bay&day=2026-10-11').context,null);
 assert.equal(selection('?region=morro-bay&profile=unknown').context,null);
});
test('shared target/time remain exact while later-day, stale and missing forecasts show gaps',async()=>{
 for(const [query,data] of [['?region=morro-bay&target=unlisted&hour=2026-10-11T12:00Z',report],['?region=morro-bay&hour=2026-10-07T13:00Z',report],['', {...report,sources:report.sources.map(x=>({...x,fetchedAt:'2026-10-07T08:00:00Z'}))}]]){
  const html=await(await serveCoastPage(request('/report'+query),options(data))).text();assert.match(html,/No fresh, supported local NWS/);assert.doesNotMatch(html,/8 \/ 12 kt/);
  if(query.includes('unlisted')){assert.match(html,/target unlisted/);assert.match(html,/2026-10-11T12:00:00.000Z/);}
 }
});
test('nearshore original sampling remains visible only within supported first/last range',async()=>{
 for(const [hour,present] of [['11',false],['13',true],['16',false]]){
  const html=await(await serveCoastPage(request('/report?hour=2026-10-07T'+hour+':00Z'),options())).text();
  assert.equal(html.includes('Sampling interval 180 minutes'),present,hour);
  if(present)assert.match(html,/Original model sample <time datetime="2026-10-07T12:00:00.000Z"/);
 }
});
test('public report request strips client identity, range, query and origin',async()=>{
 let seen;const result=await serveCoastPage(request('/report?hour=2026-10-07T12:00Z&token=private',{headers:{Cookie:'session=private',Authorization:'Bearer private',Range:'bytes=2-4',Origin:'https://foreign.test'}}),{...options(),fetcher:async req=>{seen=req;return new Response(JSON.stringify(report),{headers:{'Content-Type':'application/json'}});}});
 assert.equal(result.status,200);assert.equal(seen.url,'https://fish-report.g4651.workers.dev/api/report');assert.equal(seen.method,'GET');assert.equal(seen.redirect,'manual');assert.deepEqual([...seen.headers],[]);assert.doesNotMatch(await result.text(),/token=private/);
});
test('RSS retains assembly and observation dates across reads and deduplicates original observations',async()=>{
 const data={...report,observations:[...report.observations,...report.observations]};
 const a=await(await serveCoastPage(request('/feed.xml'),options(data))).text();
 const b=await(await serveCoastPage(request('/feed.xml'),{...options(data),now:new Date('2026-10-10T12:00:00Z')})).text();
 assert.equal(a,b);assert.match(a,/<lastBuildDate>Wed, 07 Oct 2026 11:50:00 GMT/);assert.match(a,/<pubDate>Wed, 07 Oct 2026 10:30:00 GMT/);assert.equal((a.match(/<item>/g)||[]).length,2);assert.doesNotMatch(a,/10 Oct/);
});
test('escaped markup, unsafe source links and replacement tokens remain inert',async()=>{
 const html=await(await serveCoastPage(request('/report?target=%3Cscript%3E'),options())).text();
 assert.match(html,/NWS \$&amp; &lt;script&gt;/);assert.match(html,/target &lt;script&gt;/);assert.doesNotMatch(html,/javascript:|<script/);assert.doesNotMatch(html,/<!--COAST_REPORT-->/);
});
test('failed snapshots stay explicit gaps without fabricated original clocks',async()=>{
 for(const data of [{...report,countyId:'other'},{...report,generatedAt:'invalid'},{...report,forecasts:null}]){
  const response=await serveCoastPage(request(),options(data));assert.equal(response.status,503);const html=await response.text();assert.match(html,/unavailable|could not be read/);assert.doesNotMatch(html,/Report assembled/);
 }
});
test('GET/HEAD routes are bounded and missing template fails closed; existing privacy is not replaced',async()=>{
 const head=await serveCoastPage(request('/report',{method:'HEAD'}),options());assert.equal(head.status,200);assert.equal(await head.text(),'');assert.equal(head.headers.get('Cache-Control'),'no-store');
 const post=await serveCoastPage(request('/report',{method:'POST'}),options());assert.equal(post.status,405);assert.equal(post.headers.get('Allow'),'GET, HEAD');
 assert.equal((await serveCoastPage(request('/privacy'),options())).status,404);
 for(const shell of [undefined,template+'<!--COAST_REPORT-->'])assert.equal((await serveCoastPage(request(),{...options(),template:shell})).status,503);
 for(const path of ['/methodology','/about']){const response=await serveCoastPage(request(path),{...options(),fetcher:async()=>{throw Error('Must not fetch');}});assert.equal(response.status,200);assert.doesNotMatch(await response.text(),/<script/);}
});
test('unreadable observation record fails closed for both text and RSS',async()=>{
 for(const path of ['/report','/feed.xml'])assert.equal((await serveCoastPage(request(path),options({...report,observations:[null]}))).status,503);
});
test('router uses generated shell and strips request identity from asset fetch without shadowing privacy',async()=>{
 Object.assign(globalThis.REGIONS,regions);globalThis.SHELLS={'/coast-readable.html':'/coast-readable.deadbeef.html'};
 const {coastPages}=await import('../server/routes/coast-pages.ts');let seen;
 const response=await coastPages.fetch(request('/methodology?token=private',{method:'HEAD',headers:{Cookie:'private',Authorization:'Bearer private'}}),{ASSETS:{fetch:async req=>{seen=req;return new Response(template);}}});
 assert.equal(response.status,200);assert.equal(await response.text(),'');assert.equal(seen.url,'https://skippercast.com/coast-readable.deadbeef');assert.equal(seen.method,'GET');assert.deepEqual([...seen.headers],[]);
 assert.equal((await coastPages.fetch(request('/privacy'),{})).status,404);
 assert.equal((await coastPages.fetch(request('/report'),{})).status,503);
});
test('readable and information navigation preserves public selection without identity query fields',async()=>{
 const html=await(await serveCoastPage(request('/methodology?region=morro-bay&hour=2026-10-11T12:00Z&profile=shore&target=gopher&token=private'),options())).text();
 assert.match(html,/href="\/report\?region=morro-bay&amp;target=gopher&amp;hour=2026-10-11T12%3A00Z&amp;profile=shore"/);
 assert.match(html,/#forecast">Open this selection/);assert.doesNotMatch(html,/token=private/);
});
test('legacy area aliases must agree with the reviewed binding at explicit map position',async()=>{
 const points={north:'35.6,-121.1,10',central:'35.4,-120.9,10',south:'35.15,-120.75,10'};
 for(const [bound,point] of Object.entries(points))for(const area of Object.keys(points)){
  const query='?region=morro-bay&area='+area+'&view='+point;
  const result=selection(query);
  if(area===bound){assert.ok(result.context,query);continue;}
  assert.equal(result.context,null,query);assert.match(result.reason,/disagrees/);
  const html=await(await serveCoastPage(request('/report'+query),{...options(),fetcher:async()=>{throw Error('Conflicting area must not fetch');}})).text();
  assert.match(html,/supplied legacy report area disagrees/);assert.doesNotMatch(html,/Report assembled/);
 }
});

test('Fish privacy path serves the complete existing notice under either UI switch',async()=>{
 const {shellFor}=await import('../server/routes/assets.ts');
 for(const UI_V2 of ['true','false'])assert.equal(shellFor('/privacy',new URLSearchParams(),{UI_V2}),'/privacy.html');
 assert.match(readFileSync(new URL('../dist/privacy.html',import.meta.url),'utf8'),/Privacy|privacy/);
});
