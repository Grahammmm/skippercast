import {getRegion} from "./region.js?v=8.4";
import {readConditions, tideAt, HOUR} from './marine-data.js?v=8.4';
import {esc, num, local, from} from './marine-charts.js?v=8.4';
import {rateHour} from './morning-outlook.js?v=8.4';

// One UTC clock drives every column; an absent sample is never interpolated.
export function matrixHTML({bundle, point, species, time, family, now=Date.now()}) {
  if (!bundle) return '<p>Hourly comparison is loading.</p>';
  const times=Array.from({length:13},(_,i)=>time+(i-3)*HOUR);
  const columns=times.map(t=>({t,c:readConditions(bundle,point,t,family),n:readConditions(bundle,point,t,'gfs'),r:rateHour(bundle,point,species,t,now)}));
  const wave=p=>`${num(p.height)} ft · ${num(p.period)} s · ${from(p.from)}`;
  const rows=[
    [getRegion().target_options?.find(t=>t.id===species)?.control_mode==='boat-comfort'?'Boat comfort':'Conditions',x=>`${num(x.r.conditions)}/10 · ${x.r.confidence}`],
    ['Wind / gust · kt',x=>`${num(x.c.wind)} / ${num(x.c.gust)} · ${from(x.c.windFrom)}`],
    ['Combined seas',x=>wave(x.c.sea)],
    ['Primary swell · NOAA',x=>wave(x.n.swell)],
    ['Secondary swell · NOAA',x=>wave(x.n.secondary)],
    ['Chop · NOAA',x=>wave(x.n.chop)],
    ['Tide · ft MLLW',x=>num(tideAt(bundle.tides,x.t))],
    ['Surface flow · kt',x=>`${num(x.c.current)} · toward ${from(x.c.currentTo)}`],
    ['Visibility · mi',x=>num(Number.isFinite(x.c.visibility)?x.c.visibility/1609.344:null)],
    ['Rain · mm',x=>num(x.c.rain)],
  ];
  return `<div class="matrix-scroll" tabindex="0" role="region" aria-label="Hourly weather comparison. Scroll horizontally for more hours."><table class="forecast-matrix"><caption>Hourly comparison · select a column to move the map and forecast</caption><thead><tr><th scope="col">${esc(family==='gfs'?'NOAA GFS':'ECMWF')}</th>${columns.map(x=>`<th scope="col" class="${x.t===time?'selected-hour':''}"><button data-forecast-epoch="${x.t}" aria-pressed="${x.t===time}">${esc(local(x.t,{weekday:'short',hour:'numeric'}))}</button></th>`).join('')}</tr></thead><tbody>${rows.map(([label,fn])=>`<tr><th scope="row">${label}</th>${columns.map(x=>`<td class="${x.t===time?'selected-hour':''}">${esc(fn(x))}</td>`).join('')}</tr>`).join('')}</tbody></table></div><p class="small">Waves come <b>from</b> the shown direction; currents flow <b>toward</b> it. Tide height is not bar current. Missing values stay blank (—).</p>`;
}
