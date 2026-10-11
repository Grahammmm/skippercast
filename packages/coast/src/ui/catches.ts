import type {CatchReport,County,Report} from '../types.ts';
import {dateKey} from '../daily.ts';
import {escapeHTML as esc,ageLabel} from './format.ts';
import {icon} from './icons.ts';

/** What the catch renderers read. AppState satisfies it; v2 (web/app/views/Reports.tsx) passes just these. */
export type CatchState={report:Report;county:County;now:Date};
/** fleetBrief also reads the method and the target. */
export type FleetState=CatchState&{mode:string;species:string};

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
function tripCard(trip:CatchReport,s:CatchState){
 const maximum=Math.max(1,...trip.species.map(p=>p.count));
 return `<article class="catch-trip"><header><div><span class="eyebrow">${esc(tripDate(trip.tripDate))} · ${esc(trip.landing)}</span><h3>${esc(trip.boat)}</h3></div><span>${trip.anglers===null?'Anglers unreported':trip.anglers+' anglers'}<small>${esc(trip.tripType)}</small></span></header><dl class="catch-counts">${trip.species.map(p=>`<div><span class="catch-bar" style="width:${Math.max(0,Math.min(100,p.count/maximum*100)).toFixed(1)}%" aria-hidden="true"></span><dt>${esc(p.name)}${p.disposition==='released'||p.released?' <small>released</small>':p.disposition==='retained'?' <small>retained</small>':''}</dt><dd>${p.count}</dd></div>`).join('')}</dl><a class="text-link" href="${esc(trip.sourceUrl)}" target="_blank" rel="noopener">Original dated fish count ${icon('arrow')}</a><p class="small-copy">Publisher page checked ${ageLabel(trip.retrievedAt,s.now)}; this is a retrieval time, not a publication time.</p></article>`;
}
export function catchSheet(s:CatchState){
 const trips=recentCatchTrips(s),first=trips[0],display=trips.slice(0,8),context=s.report.catchContext;
 return `<div class="sheet-heading"><span class="eyebrow">LOCAL FLEET / DATED EVIDENCE</span><h2>What the fleet reported.</h2><p>${first?`Latest available trip: ${tripDate(first.tripDate)}. ${trips.length} linked reports in the past seven local calendar days.`:'No recently verified local trip counts are available.'}</p></div><p>Selected reported catch categories, via SoCal Fish Reports and SkipperCast. Original reports can include additional species. These are trip-level records; they do not identify a particular reef or establish shore or dive results.</p>${display.map(trip=>tripCard(trip,s)).join('')}${trips.length>display.length?`<p>Showing the latest ${display.length} of ${trips.length} available recent reports.</p>`:''}<p class="small-copy">Original species categories are preserved. Unmarked counts mean reported; retention was not established. Missing reports do not mean zero catch. The bars compare reported counts within each trip, not catch odds or abundance.</p><p class="small-copy">${esc(s.report.catchStatus)}</p>${context?`<p class="small-copy">Source feed collected ${ageLabel(context.feedGeneratedAt,s.now)}; Fish received it ${ageLabel(context.receivedAt,s.now)}. Selecting a forecast day does not change these historical trip dates.</p><a class="text-link" href="${esc(context.rights.sourceCatalogUrl)}" target="_blank" rel="noopener">Reviewed facts-only reuse scope ${icon('arrow')}</a>`:''}<div class="sheet-links">${s.county.catchLinks.map(link=>`<a href="${esc(link.url)}" target="_blank" rel="noopener">${esc(link.label)}</a>`).join('')}</div>`;
}
