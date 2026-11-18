// SCA-528 / SCA-188 (F03-15): applicable warnings on the readable coastal report.
// The offline synthetic controls qualify the detector before replaying it on the real page.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
globalThis.REGIONS={};
globalThis.DEPLOYMENT={allowed_origins:['https://skippercast.com']};
const {serveCoastPage}=await import('../server/coast-pages.ts');
const regions=Object.fromEntries(['morro-bay','cambria-san-simeon'].map(id=>[id,JSON.parse(readFileSync(new URL('../regions/'+id+'/region.json',import.meta.url)))]));
const template=readFileSync(new URL('../dist/coast-readable.html',import.meta.url),'utf8');
const now=new Date('2026-10-07T12:00:00Z'),at=now.toISOString();
const H=3600000,iso=ms=>new Date(now.getTime()+ms).toISOString();
const SRC='https://alerts.example.test/nws';

const alert=(id,event,over)=>({id,event,headline:event+' headline '+id,description:'synthetic',effective:iso(-H),expires:iso(2*H),url:SRC+'/'+id,areaIds:['central'],...over});
const A_OVERLAP=alert('ovl','Small Craft Advisory',{});
const A_EXPIRED=alert('exp','Gale Warning',{effective:iso(-5*H),expires:iso(-H)});
const A_FUTURE=alert('fut','Hazardous Seas Warning',{effective:iso(6*H),expires:iso(9*H)});
const A_OTHER_AREA=alert('away','Dense Fog Advisory',{areaIds:['north']});
const ALL=[A_OVERLAP,A_EXPIRED,A_FUTURE,A_OTHER_AREA];

const base={schemaVersion:1,countyId:'slo',generatedAt:'2026-10-07T11:50:00Z',forecasts:[{id:'central',sourceId:'nws',hours:[{at,windKnots:8,gustKnots:12,waveFt:3,wavePeriodS:12}]}],observations:[],tides:[],tideEvents:[],alerts:[],catches:[],sources:[{id:'nws',label:'NWS',kind:'forecast',outcome:'ok',issuedAt:'2026-10-07T10:00:00Z',fetchedAt:'2026-10-07T11:50:00Z',url:'https://example.test/'},{id:'nws-alerts',label:'NWS alerts',kind:'report',outcome:'ok',fetchedAt:'2026-10-07T11:50:00Z',url:SRC}]};
const withAlerts=(alerts,alertSource={})=>({...base,alerts,sources:base.sources.map(s=>s.id==='nws-alerts'?{...s,...alertSource}:s)});

// What the page must say for the selected area (central) and hour (`at`).
// Mirrors the reviewed policy in packages/coast/src/daily.ts: an alert with no areaIds applies to every area;
// absent/null/invalid clocks are kept conservatively (only a parseable clock that excludes the hour removes it);
// the alert source counts as checked only when outcome is ok and fetchedAt is finite and -1h..+2h old (alertCheckFresh).
function expectation(report,area='central'){
 const selected=Date.parse(at);
 const clock=(v,dflt)=>{if(v==null||v==='')return dflt;const t=Date.parse(v);return Number.isNaN(t)?NaN:t;};
 const applicable=report.alerts.filter(a=>{
  if(a.areaIds&&!a.areaIds.includes(area))return false;
  const eff=clock(a.effective,-Infinity),exp=clock(a.expires,Infinity);
  return (Number.isNaN(eff)||eff<=selected)&&(Number.isNaN(exp)||exp>selected);
 });
 const source=report.sources.find(s=>s.id==='nws-alerts');
 const age=source?now.getTime()-Date.parse(source.fetchedAt):NaN;
 const fresh=source?.outcome==='ok'&&Number.isFinite(age)&&age>=-H&&age<=2*H;
 const state=!fresh?'unavailable':applicable.length?'alerts':'verified-empty';
 return {state,applicable,inapplicable:report.alerts.filter(a=>!applicable.includes(a))};
}
// Returns every way `html` fails that expectation (empty list = page is correct).
function gaps(html,want){
 const out=[];
 if(want.state==='alerts')for(const a of want.applicable){
  // Source and validity are required where the alert carries them; an undated alert has no end to show.
  for(const [label,needle] of [['event',a.event],['source',a.url],['valid-until',a.expires]])if(needle&&!html.includes(needle))out.push(`${a.id}: ${label} missing`);
 }
 if(want.state==='verified-empty'&&!/no active (marine )?alerts?/i.test(html))out.push('verified empty result not stated');
 if(want.state==='unavailable'&&!/alerts?[^.<]*(unavailable|could not be (read|retrieved))/i.test(html))out.push('unavailable alert source not stated');
 if(want.state!=='verified-empty'&&/no active (marine )?alerts?/i.test(html))out.push('claims empty while alerts are applicable or the source is unavailable');
 for(const a of want.inapplicable)if(html.includes(a.event)||html.includes(a.url))out.push(`${a.id}: inapplicable alert shown`);
 return out;
}
const render=async (report,query='')=>{const r=await serveCoastPage(new Request('https://skippercast.com/report'+query),{template,regions,now,fetcher:async()=>new Response(JSON.stringify(report),{headers:{'Content-Type':'application/json'}})});return {status:r.status,html:await r.text()};};

test('expectation separates overlapping, expired, future and out-of-area alerts and the source states',()=>{
 const want=expectation(withAlerts(ALL));
 assert.equal(want.state,'alerts');assert.deepEqual(want.applicable.map(a=>a.id),['ovl']);assert.deepEqual(want.inapplicable.map(a=>a.id),['exp','fut','away']);
 assert.equal(expectation(withAlerts([A_EXPIRED,A_OTHER_AREA])).state,'verified-empty');
 assert.equal(expectation(withAlerts([],{outcome:'error'})).state,'unavailable');
 assert.equal(expectation({...base,sources:base.sources.filter(s=>s.id!=='nws-alerts')}).state,'unavailable');
});

test('expectation follows the reviewed freshness and conservative area/clock policy',()=>{
 const stale={fetchedAt:iso(-3*H)},future={fetchedAt:iso(2*H)},bad={fetchedAt:'not-a-date'},missing={fetchedAt:null};
 for(const [n,o] of [['stale',stale],['future',future],['invalid',bad],['null',missing]])assert.equal(expectation(withAlerts([],o)).state,'unavailable',n);
 assert.equal(expectation(withAlerts([],{fetchedAt:iso(-2*H)})).state,'verified-empty');
 assert.equal(expectation(withAlerts([],{fetchedAt:iso(-H/2)})).state,'verified-empty');
 // Stale source with an otherwise applicable alert is still unavailable, never a verified result.
 assert.equal(expectation(withAlerts([A_OVERLAP],stale)).state,'unavailable');
 const noArea=alert('noarea','Storm Warning',{areaIds:undefined}),undated=alert('undated','Small Craft Advisory',{effective:null,expires:null}),badClock=alert('badclock','Dense Fog Advisory',{effective:'garbage',expires:'garbage'});
 const want=expectation(withAlerts([noArea,undated,badClock,A_EXPIRED]));
 assert.equal(want.state,'alerts');assert.deepEqual(want.applicable.map(a=>a.id),['noarea','undated','badclock']);assert.deepEqual(want.inapplicable.map(a=>a.id),['exp']);
 // A page showing an unscoped or undated warning is correct, not over-showing.
 assert.deepEqual(gaps(`<p>${noArea.event} ${noArea.url} ${noArea.expires}</p><p>${undated.event} ${undated.url}</p><p>${badClock.event} ${badClock.url} garbage</p>`,want),[]);
 assert.ok(gaps('<p>No active marine alerts.</p>',expectation(withAlerts([noArea]))).some(g=>g.includes('claims empty')));
 assert.ok(gaps('<p>No active marine alerts.</p>',expectation(withAlerts([],stale))).includes('claims empty while alerts are applicable or the source is unavailable'));
});

test('valid positive control: synthetic markup that shows applicable alerts passes the detector',()=>{
 const want=expectation(withAlerts(ALL));
 const html=`<h2>Marine alerts</h2><article><h3>${A_OVERLAP.event}</h3><p>${A_OVERLAP.headline}</p><p>Source <a href="${A_OVERLAP.url}">NWS</a>; valid ${A_OVERLAP.effective} to <time>${A_OVERLAP.expires}</time></p></article>`;
 assert.deepEqual(gaps(html,want),[]);
 assert.deepEqual(gaps('<p>No active marine alerts from NWS alerts, checked 2026-10-07T11:50:00Z.</p>',expectation(withAlerts([A_EXPIRED,A_OTHER_AREA]))),[]);
 assert.deepEqual(gaps('<p>Marine alert source unavailable. Not treated as no alerts.</p>',expectation(withAlerts([],{outcome:'error'}))),[]);
});

test('negative controls: the detector flags a page that omits, mislabels or over-shows alerts',()=>{
 const want=expectation(withAlerts(ALL));
 assert.deepEqual(gaps('<h2>Selected local forecast hour</h2>',want),['ovl: event missing','ovl: source missing','ovl: valid-until missing']);
 assert.ok(gaps(`<p>${A_OVERLAP.event} ${A_OVERLAP.url} ${A_OVERLAP.expires}</p><p>${A_EXPIRED.event}</p>`,want).includes('exp: inapplicable alert shown'));
 assert.ok(gaps(`<p>${A_OVERLAP.event} ${A_OVERLAP.url} ${A_OVERLAP.expires}</p><p>${A_OTHER_AREA.url}</p>`,want).includes('away: inapplicable alert shown'));
 assert.ok(gaps('<p>No active marine alerts.</p>',want).includes('claims empty while alerts are applicable or the source is unavailable'));
 const down=expectation(withAlerts([],{outcome:'error'}));
 assert.ok(gaps('<p>No active marine alerts.</p>',down).length>0);
 assert.ok(gaps('<p>nothing</p>',expectation(withAlerts([]))).includes('verified empty result not stated'));
});

test('readable report shows applicable alerts and distinguishes checked empty from unavailable',async()=>{
 const starting=alert('start','Storm Warning',{effective:at,areaIds:undefined});
 const ending=alert('end','Hurricane Force Wind Warning',{expires:at});
 const unknown=alert('unknown','Brisk Wind Advisory',{effective:'invalid',expires:null});
 const cases=[
  ['applicable',withAlerts([...ALL,starting,ending,unknown])],
  ['verified-empty',withAlerts([A_EXPIRED,A_OTHER_AREA],{fetchedAt:iso(-2*H)})],
  ['error',withAlerts([],{outcome:'error'})],
  ['stale with a warning',withAlerts([A_OVERLAP],{fetchedAt:iso(-2*H-1)})],
  ['future retrieval',withAlerts([],{fetchedAt:iso(H+1)})],
  ['missing source',{...base,sources:base.sources.filter(s=>s.id!=='nws-alerts')}],
  ['unreadable alert',withAlerts([{...A_OVERLAP,areaIds:'central'}]),{state:'unavailable',inapplicable:[A_OVERLAP]}],
 ];
 for(const [name,report,want=expectation(report)] of cases){
  const {status,html}=await render(report),found=gaps(html,want);
  assert.equal(status,200,name);
  assert.match(html,/SLO reference report/,name);assert.match(html,/8 \/ 12 kt/,name);assert.ok(html.includes(at),name);
  assert.deepEqual(found,[],name);
  if(name==='applicable'){
   assert.ok(html.includes(`<time datetime="${A_OVERLAP.effective}">`));
   assert.ok(html.includes(`<a href="${A_OVERLAP.url}" rel="noopener">NWS alerts</a>`));
   assert.match(html,/Effective Unknown time; expires Unknown time/);
  }
  if(name==='stale with a warning')assert.ok(!html.includes(A_OVERLAP.url));
 }
});

test('explicit reviewed area and selected hour, not the reference area or wall clock, drive alerts',async()=>{
 const late=iso(6*H),northLater={...A_FUTURE,areaIds:['north']};
 const report=withAlerts([A_OVERLAP,A_OTHER_AREA,northLater]);
 for(const [selected,shown,excluded] of [[at,A_OTHER_AREA,northLater],[late,northLater,A_OTHER_AREA]]){
  const {status,html}=await render(report,`?region=cambria-san-simeon&area=north&hour=${encodeURIComponent(selected)}`);
  assert.equal(status,200);
  assert.match(html,/Sources bound to the selected reviewed map area/);
  assert.ok(html.includes(`<code>${selected}</code>`));
  assert.ok(html.includes(shown.url));
  assert.ok(!html.includes(excluded.url));
  assert.ok(!html.includes(A_OVERLAP.url));
 }
});
