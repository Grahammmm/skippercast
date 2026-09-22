import {getRegion} from './region.js?v=8.11';
import { readConditions, tideAt, HOUR, POINTS } from "./marine-data.js?v=8.11";
import { esc, num, from, local, weatherName } from "./marine-charts.js?v=8.11";
import { pacificEpoch } from "./forecast.js?v=8.11";
import { rateHour } from "./morning-outlook.js?v=8.11";
export function forecastSummaryHTML(bundle,point,species,time,family,dayRating,now=Date.now()) {
  const c=readConditions(bundle,point,time,family), parts=readConditions(bundle,point,time,"gfs");
  const other=readConditions(bundle,point,time,family==="gfs"?"ecmwf":"gfs");
  const rating=rateHour(bundle,point,species,time,now);
  const tide=tideAt(bundle.tides,time), later=tideAt(bundle.tides,time+HOUR);
  const trend=Number.isFinite(tide)&&Number.isFinite(later)?(later>tide?"rising":"falling"):"trend unavailable";
  const card=(label,value,note)=>`<div class="forecast-metric"><span>${label}</span><strong>${value}</strong><small>${note}</small></div>`;
  const wave=(part)=>`${num(part.height)} ft${part.period>0?` <span>@ ${num(part.period)} s</span>`:""}`;
  const waveNote=(part)=>part.height===0?"No resolved component":`From ${from(part.from)}`;
  const reasons=rating.reasons.length?rating.reasons.join(" · "):"Two-model comparison; lower comfort / gear-control estimate.";
  return `<div class="hour-score"><div><span>Hourly conditions</span><strong>${rating.conditions===null?"No score":num(rating.conditions)+"<small>/10</small>"}</strong></div><p>${rating.confidence} confidence${time-now/1000>=72*HOUR?" · provisional":""}<br><span>Comfort ${num(rating.comfort)} · fishing stability ${num(rating.control)}</span></p></div>
    <details class="hour-details"><summary>Selected-hour measurements</summary><div class="forecast-metrics">${[
      card("Wind / gust",`${num(c.wind)} / ${num(c.gust)} kt`, `From ${from(c.windFrom)}${c.gust!==null&&c.gust<c.wind?" · gust inconsistent":""}`),
      card("Combined seas",wave(c.sea),`From ${from(c.sea.from)} · ${family==="gfs"?"primary-wave":"mean"} period`),
      card("Primary swell · NOAA",wave(parts.swell),waveNote(parts.swell)),
      card("Secondary swell · NOAA",wave(parts.secondary),waveNote(parts.secondary)),
      card("Wind chop · NOAA",wave(parts.chop),waveNote(parts.chop)),
      card(`Tide · ${getRegion().stations.tide_name}`,`${num(tide)} ft`,`${trend} · MLLW; not bar current`),
      card("Surface current",`${num(c.current)} kt`,`Toward ${from(c.currentTo)} · coarse model`),
      card("Air / sea temperature",`${num(c.air,0)} / ${num(c.sst,0)}°F`,`${weatherName(c.weatherCode)}`),
      card("Visibility / rain",`${num(c.visibility===null?null:c.visibility/1609.344)} mi / ${num(c.rain)} mm`,"Forecast at the selected hour"),
      card(`${family==="gfs"?"ECMWF":"NOAA GFS"} comparison`,`${num(other.wind)} / ${num(other.gust)} kt`,`${num(other.sea.height)} ft seas · score uses rougher values`),
     ].join("")}</div></details>
    <details class="rating-notes"><summary>${rating.conditions===null?"Why no score":rating.confidence==="Low"?"Why confidence is low":"Rating & location details"}</summary><p>${esc(reasons)}</p><p>${esc(POINTS[point].name)}. Day buttons show the lowest hourly conditions score for ${esc(dayRating?.window||"7 a.m.–1 p.m.")}${dayRating?.sampleCount?` (${dayRating.sampleCount} hourly samples)`:""}. This hour is scored separately. Bite potential remains unknown. Scores do not assess the harbor entrance or your routed trip.</p>${dayRating?.reasons?.length?`<p>Day confidence: ${esc(dayRating.reasons.join(" · "))}</p>`:""}</details>`;
}

export function ratingLabel(score) {
  return !Number.isFinite(score)?"Data incomplete":score>=8?"Excellent":score>=6?"Good":score>=4?"Fair":score>=2?"Poor":"Very rough";
}
export function boatDayHTML(bundle, point, species, time, dayRating, now=Date.now()) {
  if(!bundle) return '<p>Loading the day’s wind, seas and fishing conditions…</p>';
  const date=new Intl.DateTimeFormat('en-CA',{timeZone:'America/Los_Angeles',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(time*1000));
  const start=dayRating?.time??pacificEpoch(date+'T07:00');
  const count=dayRating?.sampleCount||7;
  const samples=Array.from({length:count},(_,i)=>start+i*HOUR);
  const rows=samples.flatMap(t=>['gfs','ecmwf'].map(f=>readConditions(bundle,point,t,f)));
  const noaa=samples.map(t=>readConditions(bundle,point,t,'gfs'));
  const max=k=>{const v=rows.map(k).filter(Number.isFinite);return v.length?Math.max(...v):null;};
  const wind=max(c=>c.wind),sea=max(c=>c.sea.height),chop=max(c=>c.chop.height);
  const periods=noaa.map(c=>c.swell.period).filter(n=>Number.isFinite(n)&&n>0);
  const complete=rows.every(c=>[c.wind,c.sea.height,c.swell.period].every(Number.isFinite));
  const fresh=now-bundle.retrieved<=3*3600000 && Object.values(bundle.models).every(m=>!Number.isFinite(m.retrieved)||now-m.retrieved<=3*3600000);
  const rated=Number.isFinite(dayRating?.conditions);
  const quality=ratingLabel(dayRating?.conditions);
  const title=`${local(time,{weekday:'long'})} on the boat`;
  let first;
  if(!fresh) first='The forecast is out of date, so the selected day’s boat conditions cannot be assessed reliably.';
  else if(wind===null||sea===null) first='There is not enough wind and wave coverage to describe this day reliably yet.';
  else first=`${rated?quality+' conditions expected':'Available forecast hours show'} at ${POINTS[point].name}: wind up to ${num(wind)} kt and seas up to ${num(sea)} ft${periods.length?`, with swell spaced ${num(Math.min(...periods),0)}–${num(Math.max(...periods),0)} seconds apart`:''}${!complete?' (partial coverage)':''}.`;
  const reason=dayRating?.reasons?.[0];
  let second=!rated?`A day rating is unavailable${reason?': '+reason.toLowerCase():' until the required forecasts are verified'}; recheck before planning the trip.`:dayRating.conditions<4?'Expect uncomfortable boat motion and difficult fishing; this is a poor window for a small-boat outing.':dayRating.conditions<6?'Expect noticeable boat motion and more effort keeping your gear fishing effectively.':chop>=1?'Wind chop may make the ride bumpy and holding your fishing position harder.':'The forecast suggests a more manageable ride and easier gear handling; check the entrance and your return conditions before departure.';
  if(dayRating?.score_scope==='boat-comfort'&&rated) second='This describes boat motion only; night operations, diving and lobster gear handling need a separate assessment.';
  if(rated&&dayRating.confidence==='Low') second=second.replace(/\.$/,'')+' (low forecast confidence).';
  return `<div class="boat-day-heading"><strong>${esc(title)}</strong><span>${rated?num(dayRating.conditions)+'/10 · '+quality:'Data incomplete'}</span></div><p>${esc(first)} ${esc(second)}</p><small>${esc(dayRating?.window||'7 a.m.–1 p.m.')} Pacific · forecast, not catch probability${dayRating?.provisional?' · provisional outlook':''}</small>`;
}
