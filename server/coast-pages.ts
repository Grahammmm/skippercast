import {serveCoastData} from './coast-data.ts';
import {secure} from './security-headers.ts';
import {fishLink,canonicalHour,FISH_REGIONS} from '../web/fish-links.ts';
import {resolveReportBinding,type ManagedReportContext,type ReportLocalArea} from '../packages/coast/src/state/report-binding.ts';
import {slo} from '../packages/coast/src/counties.ts';
import {escape as esc,informationContent} from '../packages/coast/src/information.ts';
import type {Report,ForecastHour,SourceStatus} from '../packages/coast/src/types.ts';
import type {NearshoreSite,NearshoreHour} from '../packages/coast/src/enrichment-types.ts';

export type CoastPageRegion={id:string;map?:{center?:readonly number[];local_areas?:readonly ReportLocalArea[]}};
export type CoastPageOptions={template?:string;regions:Readonly<Record<string,CoastPageRegion>>;fetcher?:typeof fetch;now?:Date;publicOrigin?:string};
export type ReadableSelection={context:ManagedReportContext|null;workspace:string;reference:boolean;reason:string|null};
const STATE_KEYS=['region','coast','view','target','hour','profile','day','layers','area','base','spot','focus','presentation','current','habitat','ui','place','mode','species'];
const AREA_PLACES:Readonly<Record<string,string>>={north:'cambria',central:'morro',south:'avila'};
const PLACE_AREAS:Readonly<Record<string,string>>={cambria:'north',morro:'central',avila:'south'};
const HOUR=3600000;
function workspaceURL(url:URL):string{const kept=new URLSearchParams();for(const key of STATE_KEYS)for(const value of url.searchParams.getAll(key))kept.append(key,value);return '/'+(kept.size?'?'+kept.toString():'')+'#forecast';}
function fieldClock(at:unknown):number{return typeof at==='string'?Date.parse(at):NaN;}
function stamp(at:unknown):string{const epoch=fieldClock(at);return Number.isFinite(epoch)?`<time datetime="${esc(at)}">${esc(new Intl.DateTimeFormat('en-US',{timeZone:slo.timezone,month:'short',day:'numeric',year:'numeric',hour:'numeric',minute:'2-digit',timeZoneName:'short'}).format(new Date(epoch)))}</time>`:'Unknown time';}
function value(number:unknown,decimals=1):string{return typeof number==='number'&&Number.isFinite(number)?number.toFixed(decimals):'—';}
function sourceLink(url:unknown,label:string):string{try{if(typeof url!=='string')throw Error('Missing link');const parsed=new URL(url);if(!['http:','https:'].includes(parsed.protocol)||parsed.username||parsed.password)throw Error('Unsupported link');return `<a href="${esc(parsed.href)}" rel="noopener">${esc(label)}</a>`;}catch{return esc(label);}}

/** URL geography wins; no home cookie, nearest-place binding or silent central fallback. */
export function readableSelection(input:URL,regions:CoastPageOptions['regions'],now=new Date()):ReadableSelection{
 const url=fishLink(input.href),p=url.searchParams,workspace=workspaceURL(url);
 const reference=!['region','coast','place','area','view','spot','focus','habitat'].some(key=>input.searchParams.has(key));
 const fail=(reason:string):ReadableSelection=>({context:null,workspace,reference,reason});
 if(STATE_KEYS.some(key=>input.searchParams.getAll(key).length>1))return fail('The shared selection has duplicate parameters. Its geography and time are not guessed.');
 let region=p.get('region');
 if(p.has('region')&&!region)return fail('The shared region is empty.');
 if(!region&&p.has('coast'))return fail('A coastal overview does not supply a local SLO report binding.');
 const area=p.get('area'),place=p.get('place');
 if(!region&&place)return fail('The selected place has no reviewed local report package.');
 if(!region&&area){const alias=Object.hasOwn(AREA_PLACES,area)?AREA_PLACES[area]:undefined;region=alias&&Object.hasOwn(FISH_REGIONS,alias)?FISH_REGIONS[alias]??null:null;if(region)p.set('region',region);else return fail('The selected area has no reviewed local report binding.');}
 if(!region){if(!reference)return fail('The shared geography is incomplete.');region='morro-bay';}
 if(!Object.hasOwn(regions,region)||!['morro-bay','cambria-san-simeon'].includes(region))return fail('Local SLO sources are unavailable for the selected region.');
 const config=regions[region];if(!config||config.id!==region)return fail('The selected region metadata is unavailable.');
 const localAreas=config.map?.local_areas??[];
 const profile=p.has('profile')?p.get('profile'):p.has('mode')?p.get('mode'):'boat';
 if(!['boat','shore','spear'].includes(profile??''))return fail('The selected fishing profile is unsupported.');
 const hour=p.get('hour');let at=new Date(Math.floor(now.getTime()/HOUR)*HOUR);
 if(p.has('hour')){const canonical=canonicalHour(hour);if(!canonical)return fail('The selected UTC hour is unsupported; it is not replaced with now.');at=new Date(canonical);}
 else if(p.has('day'))return fail('This shared date needs an explicit UTC hour. No first forecast hour is substituted.');
 let point:{latitude:number;longitude:number}|null=null;let localId:string|null=null;
 const view=p.get('view');
 if(view&&!['coast','conditions','history','fleet','reports'].includes(view)){
  const tokens=view.split(',');if(tokens.length!==3||tokens.some(token=>!/^[-]?(?:\d+(?:\.\d+)?|\.\d+)$/.test(token)))return fail('The shared map position is unsupported.');
  const [latitude,longitude,zoom]=tokens.map(Number);if(typeof latitude!=='number'||typeof longitude!=='number'||typeof zoom!=='number'||![latitude,longitude,zoom].every(Number.isFinite)||Math.abs(latitude)>90||Math.abs(longitude)>180||zoom<0||zoom>24)return fail('The shared map position is unsupported.');point={latitude,longitude};
 }
 if(!point){
  if(['spot','focus','habitat'].some(key=>p.has(key)))return fail('This selected public feature needs its shared map position to bind local sources.');
  let areaId:string|undefined;
  if(place&&Object.hasOwn(PLACE_AREAS,place)&&FISH_REGIONS[place]===region)areaId=PLACE_AREAS[place];
  else if(area&&Object.hasOwn(AREA_PLACES,area))areaId=area;
  const named=areaId?slo.areas.find(item=>item.id===areaId):undefined;
  if(named)point={latitude:named.lat,longitude:named.lon};
  else{const center=config.map?.center,[latitude,longitude]=center??[];if(typeof latitude==='number'&&typeof longitude==='number'&&[latitude,longitude].every(Number.isFinite))point={latitude,longitude};}
 }
 if(!point)return fail('The selected package has no reviewed map position.');
 if(area&&!Object.hasOwn(AREA_PLACES,area)){if(!localAreas.some(item=>item.id===area))return fail('The selected local area is unsupported.');localId=area;}
 const context:ManagedReportContext={regionId:region,point,localAreas,localId,profile:profile as ManagedReportContext['profile'],target:p.get('target')??p.get('species')??'reef',at};
 const binding=resolveReportBinding(context);
 if(!binding)return fail('The selected map position is outside the reviewed local SLO report areas.');
 if(area&&Object.hasOwn(AREA_PLACES,area)&&binding.areaId!==area)return fail('The supplied legacy report area disagrees with the reviewed area at the selected map position.');
 return {context,workspace:workspaceURL(url),reference,reason:null};
}
function currentForecast(report:Report,areaId:string,at:Date,now:Date):{hour:ForecastHour|undefined;source:SourceStatus|undefined}{
 const forecast=report.forecasts.find(item=>item.id===areaId),source=report.sources.find(item=>item.id===forecast?.sourceId);
 if(!forecast||!source||source.outcome!=='ok')return {hour:undefined,source};
 const issue=now.getTime()-fieldClock(source.issuedAt),retrieval=now.getTime()-fieldClock(source.fetchedAt),selected=at.getTime();
 if(!Number.isFinite(issue)||!Number.isFinite(retrieval)||issue<-HOUR||issue>18*HOUR||retrieval<-HOUR||retrieval>2*HOUR||selected<now.getTime()-HOUR||selected>=now.getTime()+72*HOUR)return {hour:undefined,source};
 return {hour:forecast.hours.find(item=>fieldClock(item.at)===selected),source};
}
function nearshoreSample(site:NearshoreSite,at:Date,now:Date):NearshoreHour|undefined{
 const issue=now.getTime()-fieldClock(site.issuedAt),retrieval=now.getTime()-fieldClock(site.fetchedAt);
 if(site.availability!=='available'||site.freshness!=='current'||!Number.isFinite(issue)||!Number.isFinite(retrieval)||issue<-300000||issue>=48*HOUR||retrieval<-300000||retrieval>=3*HOUR)return undefined;
 const frames=site.hours.filter(item=>Number.isFinite(fieldClock(item.at))).sort((a,b)=>fieldClock(a.at)-fieldClock(b.at)),first=frames[0],last=frames.at(-1),selected=at.getTime(),declared=fieldClock(site.validThrough);
 if(!first||!last||selected<fieldClock(first.at)||selected>fieldClock(last.at)||(Number.isFinite(declared)&&selected>declared))return undefined;
 return frames.filter(item=>Math.abs(fieldClock(item.at)-selected)<=1.5*HOUR).sort((a,b)=>Math.abs(fieldClock(a.at)-selected)-Math.abs(fieldClock(b.at)-selected))[0];
}
function reportMarkup(report:Report,selection:ReadableSelection,now:Date):string{
 const context=selection.context,binding=context&&resolveReportBinding(context);if(!context||!binding)return gapMarkup(selection);
 const {hour,source}=currentForecast(report,binding.areaId,context.at,now),area=slo.areas.find(item=>item.id===binding.areaId),nearshore=report.nearshore?.filter(item=>item.areaId===binding.areaId)??[];
 const caveat=context.profile==='boat'?'Check the harbor entrance, complete route and return conditions separately.':context.profile==='shore'?'Check actual breakers, current access and beach-health advisories at the exact beach.':'Check in-water visibility, swell, currents, entry and exit at the exact dive site. Surface current cannot clear a dive.';
 const tides=report.tides.find(item=>Math.abs(fieldClock(item.at)-context.at.getTime())<=4*60000);
 return `<h1>Readable coastal source report</h1><p class="scope">${selection.reference?'SLO reference report; no shared map geography was supplied.':'Sources bound to the selected reviewed map area.'} ${esc(area?.name??binding.areaId)} · ${esc(context.profile)} · target ${esc(context.target)}.</p><p>Selected UTC hour: ${stamp(context.at.toISOString())} (<code>${esc(context.at.toISOString())}</code>).</p><p class="small">Report assembled ${stamp(report.generatedAt)}. This is the source assembly time, not the time this page was opened.</p><p><a href="${esc(selection.workspace)}">Open this selection in the shared workspace</a></p><p>${esc(caveat)}</p><h2>Selected local forecast hour</h2>${hour?`<article><dl><dt>Wind / gust</dt><dd>${value(hour.windKnots,0)} / ${value(hour.gustKnots,0)} kt</dd><dt>Offshore seas / period</dt><dd>${value(hour.waveFt)} ft / ${value(hour.wavePeriodS,0)} s</dd></dl><p>Original valid time ${stamp(hour.at)}. Issue ${stamp(source?.issuedAt)}; source retrieval ${stamp(source?.fetchedAt)}.</p></article>`:'<p class="gap">No fresh, supported local NWS forecast sample covers this exact selected hour. Older, missing and later hours are not filled. The shared seven-day model comparison remains available in the workspace.</p>'}<h2>Nearshore model samples</h2>${nearshore.length?nearshore.map(site=>{const sample=nearshoreSample(site,context.at,now);return `<article><h3>${esc(site.name)}</h3>${sample?`<p>${value(sample.waveFt)} ft · ${value(sample.periodS,0)} s. Original model sample ${stamp(sample.at)}. Sampling interval ${value(site.temporalResolutionMinutes,0)} minutes; this is not an hourly measurement or exact beach breakers.</p>`:'<p class="gap">No current supported model sample covers the selected time. Frames are not extended before or after their source range.</p>'}<p class="small">Issue ${stamp(site.issuedAt)}; retrieval ${stamp(site.fetchedAt)}. ${sourceLink(site.url,'Original nearshore source')}</p></article>`;}).join(''):'<p>Nearshore model samples are unavailable for this area.</p>'}<h2>Reference tide prediction</h2><p>${tides?value(tides.heightFt)+' ft MLLW · original prediction '+stamp(tides.at):'No tide prediction covers the selected hour.'} ${esc(slo.tideStation.note)} High water does not establish slack current.</p><h2>Buoy observations · original clocks</h2><p>These are station observations, independently of the selected forecast day.</p><div class="observations">${report.observations.slice(0,100).map(item=>{const age=now.getTime()-fieldClock(item.observedAt),fresh=Number.isFinite(age)&&age>=-HOUR&&age<3*HOUR;return `<article><h3>${esc(slo.buoys.find(station=>station.id===item.stationId)?.name??item.stationId)}</h3><p>${fresh?'Recent source observation':'Historical or unsupported freshness; not a current reading'} · ${stamp(item.observedAt)}</p><dl><dt>Water</dt><dd>${value(item.waterTempF)} °F</dd><dt>Waves / period</dt><dd>${value(item.waveFt)} ft / ${value(item.wavePeriodS,0)} s</dd><dt>Wind / gust</dt><dd>${value(item.windKnots,0)} / ${value(item.gustKnots,0)} kt</dd></dl><p>${sourceLink(item.url,'Original station record')}</p></article>`;}).join('')||'<p>No measured buoy observations are available.</p>'}</div><h2>Beach and dive context</h2><p>${esc(caveat)} In-water visibility remains unknown without a fresh dated observation for the entry being considered.</p>${(report.waterQuality??[]).filter(item=>item.areaId===binding.areaId).map(item=>`<article><h3>${esc(item.name)}</h3><p>${esc(item.status)} · sample ${stamp(item.sampledAt)} · retrieved ${stamp(item.fetchedAt)}. A published status is not continuous testing or water-entry clearance.</p>${sourceLink(item.url,'Original beach-health advisory')}</article>`).join('')||'<p>Applicable beach-health sample records are unavailable.</p>'}<h2>Source status and clocks</h2>${report.sources.slice(0,100).map(item=>`<article class="source"><h3>${sourceLink(item.url,item.label)}</h3><p>${esc(item.kind)} · ${esc(item.outcome)}. Issued ${stamp(item.issuedAt)}; retrieved ${stamp(item.fetchedAt)}${item.validThrough?'; valid through '+stamp(item.validThrough):''}.</p></article>`).join('')||'<p>Source receipts are unavailable.</p>'}<p>No separate conditions-window or trip-safety score is calculated by this text page. The shared workspace supplies the full local report, history, fleet evidence and planning tools.</p>`;
}
function gapMarkup(selection:ReadableSelection):string{return `<h1>Readable coastal report</h1><p class="gap">${esc(selection.reason??'The local source report is unavailable.')}</p><p>The selected geography, profile and hour have not been replaced with Morro Bay or today. Missing local coverage stays missing.</p><p><a href="${esc(selection.workspace)}">Open the preserved selection in the shared workspace</a></p>`;}
function validReport(value:unknown):value is Report{if(!value||typeof value!=='object')return false;const report=value as Record<string,unknown>;return report.schemaVersion===1&&report.countyId==='slo'&&Number.isFinite(fieldClock(report.generatedAt))&&['forecasts','observations','tides','tideEvents','alerts','sources','catches'].every(key=>Array.isArray(report[key]));}
async function publicReport(request:Request,fetcher:typeof fetch):Promise<Report|null>{try{const url=new URL('/api/coast/report',request.url),response=await serveCoastData(new Request(url,{method:'GET'}),fetcher);if(!response.ok)return null;const report:unknown=await response.json();return validReport(report)?report:null;}catch{return null;}}
function rss(report:Report,origin:string):string{
 const root=new URL('/',origin),reportURL=new URL('/report',root).href,date=new Intl.DateTimeFormat('en-CA',{timeZone:slo.timezone,year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(report.generatedAt));
 const item=(title:string,guid:string,at:string,description:string)=>`<item><title>${esc(title)}</title><link>${esc(reportURL)}</link><guid isPermaLink="false">${esc(guid)}</guid><pubDate>${esc(new Date(at).toUTCString())}</pubDate><description>${esc(description)}</description></item>`;
 const seen=new Set<string>();let observations='';for(const observation of report.observations.slice(0,100)){if(!Number.isFinite(fieldClock(observation.observedAt)))continue;const identity=observation.stationId+':'+observation.observedAt;if(seen.has(identity))continue;seen.add(identity);observations+=item('SLO buoy '+observation.stationId+' · observed',identity,observation.observedAt,`Original observation ${observation.observedAt}. Water ${value(observation.waterTempF)} F; waves ${value(observation.waveFt)} ft. This observation is not refreshed by report assembly or feed retrieval.`);}
 return `<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>SkipperCast · SLO source report</title><link>${esc(reportURL)}</link><description>SLO reference source records. Forecasts, observations and retrievals retain separate clocks.</description><lastBuildDate>${esc(new Date(report.generatedAt).toUTCString())}</lastBuildDate>${item('SLO report · '+date,'slo:report:'+report.generatedAt,report.generatedAt,'Report assembled '+report.generatedAt+'. Read original source clocks and missing/stale states. This is not a new on-water observation.')}${observations}</channel></rss>`;
}
function response(request:Request,body:string,status=200,type='text/html;charset=utf-8'):Response{return secure(new Response(request.method==='HEAD'?null:body,{status,headers:{'Content-Type':type,'Cache-Control':'no-store'}}));}
/** Read-only page/report composition; client identity never enters public source requests. */
export async function serveCoastPage(request:Request,options:CoastPageOptions):Promise<Response>{
 if(!['GET','HEAD'].includes(request.method))return secure(new Response('Method not allowed',{status:405,headers:{Allow:'GET, HEAD'}}));
 const url=new URL(request.url),path=url.pathname;if(!['/report','/feed.xml','/methodology','/about'].includes(path))return response(request,'Not found',404,'text/plain;charset=utf-8');
 const now=options.now??new Date(),workspace=workspaceURL(fishLink(url.href));
 if(path==='/feed.xml'){const report=await publicReport(request,options.fetcher??fetch);if(report)try{return response(request,rss(report,options.publicOrigin??'https://skippercast.com'),200,'application/rss+xml;charset=utf-8');}catch{/* An unreadable source cannot become a fresh feed. */}return response(request,'Source feed unavailable. No new publication time is fabricated.',503,'text/plain;charset=utf-8');}
 const template=options.template;if(!template||template.split('<!--COAST_REPORT-->').length!==2)return response(request,'Readable page shell unavailable. Open the shared workspace.',503,'text/plain;charset=utf-8');
 let content:string,title:string,status=200;
 if(path==='/methodology'||path==='/about'){const info=informationContent(path==='/methodology'?'methodology':'about');content=`<h1>${esc(info.title)}</h1>${info.html}<p><a href="${esc(workspace)}">Open this selection in the shared workspace</a></p>`;title=info.title;}
 else{const selection=readableSelection(url,options.regions,now);title='Readable coastal report';if(!selection.context)content=gapMarkup(selection);else{const report=await publicReport(request,options.fetcher??fetch);if(!report){status=503;content=gapMarkup({...selection,reason:'Current public coastal source report unavailable. No calm conditions or fresh source clock is assumed.'});}else try{content=reportMarkup(report,selection,now);}catch{status=503;content=gapMarkup({...selection,reason:'The public source record could not be read. Unsupported fields are not replaced with estimates.'});}}}
 const query=new URL(workspace,url.origin).search;
 const shell=template.replace(/href="(\/report|\/methodology|\/about)"/g,(_match,path:string)=>`href="${esc(path+query)}"`);
 const body=shell.replace('<!--COAST_REPORT-->',()=>content).replace(/<title>[^<]*<\/title>/,()=>`<title>${esc(title)} · SkipperCast</title>`);return response(request,body,status);
}
