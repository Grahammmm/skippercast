import type {CatchReport,County,Report} from '../types.ts';
import {dateKey} from '../daily.ts';
import {escapeHTML as esc,ageLabel} from './format.ts';
import {icon} from './icons.ts';

/** What the catch renderers read. AppState satisfies it; v2 (web/app/views/Reports.tsx) passes just these. */
export type CatchState={report:Report;county:County;now:Date};
/** fleetBrief also reads the method and the target. */
export type FleetState=CatchState&{mode:string;species:string};

/** The catch sheet's own words, as catalogue ids the host resolves (the package never imports the app's catalogue). */
export const CATCH_COPY_KEYS=['reportCatch.eyebrow','reportCatch.heading','reportCatch.latest','reportCatch.none','reportCatch.intro','reportCatch.anglersNone','reportCatch.anglers','reportCatch.released','reportCatch.retained','reportCatch.original','reportCatch.checked','reportCatch.showing','reportCatch.caveat','reportCatch.feed','reportCatch.reuse','reportCatch.sourceText'] as const;
export type CatchCopyKey=typeof CATCH_COPY_KEYS[number];
/** Optional host copy for catchSheet. With none, every sentence keeps its original English text and formatters. Variables are raw; the renderer escapes the result once. */
export interface CatchCopy{
 text(key:CatchCopyKey,vars?:Readonly<Record<string,string|number>>):string;
 /** A trip's local calendar date (YYYY-MM-DD) as a short date. */
 date(day:string):string;
 /** How long ago `at` was, from the same thresholds as ageLabel. */
 age(at:string,now:Date):string;
}

const DAY=86400000;
function dayValue(date:string){const value=Date.parse(date+'T00:00:00Z');return /^\d{4}-\d{2}-\d{2}$/.test(date)&&Number.isFinite(value)&&new Date(value).toISOString().slice(0,10)===date?value:NaN;}
function fresh(at:string,now:Date){const age=now.getTime()-Date.parse(at);return Number.isFinite(age)&&age>=-300000&&age<=72*3600000;}
const tripDate=(date:string)=>new Intl.DateTimeFormat('en-US',{timeZone:'UTC',month:'short',day:'numeric'}).format(new Date(dayValue(date)));

/** Trip dates are local calendar dates. Forecast-day selection never moves historical reports. */
export function recentCatchTrips(s:CatchState):CatchReport[]{
 const context=s.report.catchContext;
 if(s.report.countyId!==s.county.id||!context||context.rights.scope!=='linked-factual-counts'||!fresh(context.feedGeneratedAt,s.now)||!fresh(context.receivedAt,s.now))return [];
 const today=dayValue(dateKey(s.now,s.county.timezone));
 return s.report.catches.filter(r=>{const age=today-dayValue(r.tripDate);return age>=0&&age<7*DAY&&fresh(r.retrievedAt,s.now);}).sort((a,b)=>b.tripDate.localeCompare(a.tripDate)||a.id.localeCompare(b.id));
}
function targetMatches(name:string,s:FleetState){
 const normalized=name.toLowerCase().replace(/[^a-z]/g,'');
 return s.species==='lingcod'?normalized==='lingcod':s.species==='rockfish-reef'?normalized.includes('rockfish'):s.species==='gopher-rockfish'?normalized==='gopherrockfish':s.species==='cabezon-shallow-reef'?normalized==='cabezon':s.species==='halibut'?normalized.includes('halibut'):s.species==='surfperch'?normalized.includes('surfperch'):false;
}
export function fleetBrief(s:FleetState){
 if(s.mode!=='boat')return '';
 const latest=recentCatchTrips(s)[0];if(!latest)return '';
 const match=latest.species.find(p=>targetMatches(p.name,s));
 const detail=match?`${match.count} ${match.name}${match.disposition==='released'||match.released?' released':''}`:latest.species.slice(0,2).map(p=>`${p.count} ${p.name}${p.disposition==='released'||p.released?' released':''}`).join(' · ');
 return `<button class="fleet-brief" data-open="catches"><span class="eyebrow">LATEST FLEET REPORT · ${esc(tripDate(latest.tripDate))}</span><span><b>${esc(detail)}</b>${icon('arrow')}</span><small>${esc(latest.boat)} · ${esc(latest.landing)} · dated boat report</small></button>`;
}
function tripCard(trip:CatchReport,s:CatchState,copy?:CatchCopy){
 const maximum=Math.max(1,...trip.species.map(p=>p.count));
 const T=(key:CatchCopyKey,vars:Readonly<Record<string,string|number>>|undefined,en:string)=>copy?esc(copy.text(key,vars)):en;
 const src=(text:string)=>copy?`<span lang="en">${esc(text)}</span>`:esc(text);
 const anglers=copy?(trip.anglers===null?esc(copy.text('reportCatch.anglersNone')):esc(copy.text('reportCatch.anglers',{n:trip.anglers}))):trip.anglers===null?'Anglers unreported':trip.anglers+' anglers';
 const disposition=(p:CatchReport['species'][number])=>p.disposition==='released'||p.released?` <small>${T('reportCatch.released',undefined,'released')}</small>`:p.disposition==='retained'?` <small>${T('reportCatch.retained',undefined,'retained')}</small>`:'';
 return `<article class="catch-trip"><header><div><span class="eyebrow">${esc(copy?copy.date(trip.tripDate):tripDate(trip.tripDate))} · ${esc(trip.landing)}</span><h3>${esc(trip.boat)}</h3></div><span>${anglers}<small>${src(trip.tripType)}</small></span></header><dl class="catch-counts">${trip.species.map(p=>`<div><span class="catch-bar" style="width:${Math.max(0,Math.min(100,p.count/maximum*100)).toFixed(1)}%" aria-hidden="true"></span><dt>${esc(p.name)}${disposition(p)}</dt><dd>${p.count}</dd></div>`).join('')}</dl><a class="text-link" href="${esc(trip.sourceUrl)}" target="_blank" rel="noopener">${T('reportCatch.original',undefined,'Original dated fish count')} ${icon('arrow')}</a><p class="small-copy">${copy?esc(copy.text('reportCatch.checked',{age:copy.age(trip.retrievedAt,s.now)})):`Publisher page checked ${ageLabel(trip.retrievedAt,s.now)}; this is a retrieval time, not a publication time.`}</p></article>`;
}
export function catchSheet(s:CatchState,copy?:CatchCopy){
 const trips=recentCatchTrips(s),first=trips[0],display=trips.slice(0,8),context=s.report.catchContext;
 const T=(key:CatchCopyKey,vars:Readonly<Record<string,string|number>>|undefined,en:string)=>copy?esc(copy.text(key,vars)):en;
 const src=(text:string)=>copy?`<span lang="en">${esc(text)}</span>`:esc(text);
 const status=copy&&s.report.catchStatus?`${esc(copy.text('reportCatch.sourceText'))}${src(s.report.catchStatus)}`:esc(s.report.catchStatus);
 const lead=first?(copy?esc(copy.text('reportCatch.latest',{date:copy.date(first.tripDate),n:trips.length})):`Latest available trip: ${tripDate(first.tripDate)}. ${trips.length} linked reports in the past seven local calendar days.`):T('reportCatch.none',undefined,'No recently verified local trip counts are available.');
 return `<div class="sheet-heading"><span class="eyebrow">${T('reportCatch.eyebrow',undefined,'LOCAL FLEET / DATED EVIDENCE')}</span><h2>${T('reportCatch.heading',undefined,'What the fleet reported.')}</h2><p>${lead}</p></div><p>${T('reportCatch.intro',undefined,'Selected reported catch categories, via SoCal Fish Reports and SkipperCast. Original reports can include additional species. These are trip-level records; they do not identify a particular reef or establish shore or dive results.')}</p>${display.map(trip=>tripCard(trip,s,copy)).join('')}${trips.length>display.length?`<p>${copy?esc(copy.text('reportCatch.showing',{shown:display.length,total:trips.length})):`Showing the latest ${display.length} of ${trips.length} available recent reports.`}</p>`:''}<p class="small-copy">${T('reportCatch.caveat',undefined,'Original species categories are preserved. Unmarked counts mean reported; retention was not established. Missing reports do not mean zero catch. The bars compare reported counts within each trip, not catch odds or abundance.')}</p><p class="small-copy">${status}</p>${context?`<p class="small-copy">${copy?esc(copy.text('reportCatch.feed',{collected:copy.age(context.feedGeneratedAt,s.now),received:copy.age(context.receivedAt,s.now)})):`Source feed collected ${ageLabel(context.feedGeneratedAt,s.now)}; Fish received it ${ageLabel(context.receivedAt,s.now)}. Selecting a forecast day does not change these historical trip dates.`}</p><a class="text-link" href="${esc(context.rights.sourceCatalogUrl)}" target="_blank" rel="noopener">${T('reportCatch.reuse',undefined,'Reviewed facts-only reuse scope')} ${icon('arrow')}</a>`:''}<div class="sheet-links">${s.county.catchLinks.map(link=>`<a href="${esc(link.url)}" target="_blank" rel="noopener">${src(link.label)}</a>`).join('')}</div>`;
}
