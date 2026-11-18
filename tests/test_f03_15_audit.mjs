// SCA-528 / F03-15: the readable (no-JavaScript) coastal report requires an `alerts` array but
// its markup (server/coast-pages.ts reportMarkup) never consults it. Offline, synthetic fixture only.
// The detector below states what a correct page must show; it is checked against a valid control
// (synthetic HTML that does show it), against deliberately wrong controls, and then replayed on the
// real page. The baseline test records the current observation and passes either way, so it never
// asserts that the gap is desired and keeps passing once alerts are rendered.
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
function expectation(report,area='central'){
 const selected=Date.parse(at),applicable=report.alerts.filter(a=>(a.areaIds??[]).includes(area)&&Date.parse(a.effective)<=selected&&selected<Date.parse(a.expires));
 const source=report.sources.find(s=>s.id==='nws-alerts');
 const state=!source||source.outcome!=='ok'?'unavailable':applicable.length?'alerts':'verified-empty';
 return {state,applicable,inapplicable:report.alerts.filter(a=>!applicable.includes(a))};
}
// Returns every way `html` fails that expectation (empty list = page is correct).
function gaps(html,want){
 const out=[];
 if(want.state==='alerts')for(const a of want.applicable){
  for(const [label,needle] of [['event',a.event],['source',a.url],['valid-until',a.expires]])if(!html.includes(needle))out.push(`${a.id}: ${label} missing`);
 }
 if(want.state==='verified-empty'&&!/no active (marine )?alerts?/i.test(html))out.push('verified empty result not stated');
 if(want.state==='unavailable'&&!/alerts?[^.<]*(unavailable|could not be (read|retrieved))/i.test(html))out.push('unavailable alert source not stated');
 if(want.state!=='verified-empty'&&/no active (marine )?alerts?/i.test(html))out.push('claims empty while alerts are applicable or the source is unavailable');
 for(const a of want.inapplicable)if(html.includes(a.event)||html.includes(a.url))out.push(`${a.id}: inapplicable alert shown`);
 return out;
}
const render=async report=>{const r=await serveCoastPage(new Request('https://skippercast.com/report'),{template,regions,now,fetcher:async()=>new Response(JSON.stringify(report),{headers:{'Content-Type':'application/json'}})});return {status:r.status,html:await r.text()};};

test('expectation separates overlapping, expired, future and out-of-area alerts and the source states',()=>{
 const want=expectation(withAlerts(ALL));
 assert.equal(want.state,'alerts');assert.deepEqual(want.applicable.map(a=>a.id),['ovl']);assert.deepEqual(want.inapplicable.map(a=>a.id),['exp','fut','away']);
 assert.equal(expectation(withAlerts([A_EXPIRED,A_OTHER_AREA])).state,'verified-empty');
 assert.equal(expectation(withAlerts([],{outcome:'error'})).state,'unavailable');
 assert.equal(expectation({...base,sources:base.sources.filter(s=>s.id!=='nws-alerts')}).state,'unavailable');
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

test('baseline receipt: replay the real readable page (read-only); selection and forecast are retained',async()=>{
 const results={};
 for(const [name,report] of [['applicable',withAlerts(ALL)],['verified-empty',withAlerts([A_EXPIRED,A_OTHER_AREA])],['unavailable',withAlerts([],{outcome:'error'})]]){
  const {status,html}=await render(report),want=expectation(report),found=gaps(html,want);
  assert.equal(status,200,name);
  // Existing behavior that must be retained.
  assert.match(html,/SLO reference report/,name);assert.match(html,/8 \/ 12 kt/,name);assert.ok(html.includes(at),name);
  // Never present an expired, future or out-of-area alert on this selection.
  assert.ok(!found.some(g=>g.endsWith('inapplicable alert shown')),name+': '+found.join('; '));
  // Baseline observation: either the page already satisfies the expectation, or it reports exactly the
  // documented omission (no alert event/source/validity, no empty or unavailable statement).
  results[name]=found;
 }
 console.log('F03-15 baseline gaps by state: '+JSON.stringify(results));
 for(const found of Object.values(results))assert.ok(found.length===0||found.every(g=>/missing|not stated/.test(g)),found.join('; '));
});

test('selection is unchanged: an area outside the selected report binding does not borrow alerts',async()=>{
 const north=alert('n','Small Craft Advisory',{areaIds:['north']});
 const {html}=await render(withAlerts([north]));
 assert.ok(!html.includes(north.url));
});
