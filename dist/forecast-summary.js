import { readConditions, tideAt, HOUR, POINTS } from "./marine-data.js?v=6.0";
import { esc, num, from, local, weatherName } from "./marine-charts.js?v=6.0";
import { rateHour } from "./morning-outlook.js?v=6.0";
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
  return `<div class="hour-score"><div><span>Hourly conditions</span><strong>${rating.conditions===null?"No score":num(rating.conditions)+"<small>/10</small>"}</strong></div><p>${rating.confidence} confidence${time-now/1000>=72*HOUR?" · provisional":""}<br><span>Comfort ${num(rating.comfort)} · control ${num(rating.control)}</span></p></div>
    <div class="forecast-metrics">${[
      card("Wind / gust",`${num(c.wind)} / ${num(c.gust)} kt`, `From ${from(c.windFrom)}${c.gust!==null&&c.gust<c.wind?" · gust inconsistent":""}`),
      card("Combined seas",wave(c.sea),`From ${from(c.sea.from)} · ${family==="gfs"?"primary-wave":"mean"} period`),
      card("Primary swell · NOAA",wave(parts.swell),waveNote(parts.swell)),
      card("Secondary swell · NOAA",wave(parts.secondary),waveNote(parts.secondary)),
      card("Wind chop · NOAA",wave(parts.chop),waveNote(parts.chop)),
      card("Tide · Port San Luis",`${num(tide)} ft`,`${trend} · MLLW; not bar current`),
      card("Surface current",`${num(c.current)} kt`,`Toward ${from(c.currentTo)} · coarse model`),
      card("Air / sea temperature",`${num(c.air,0)} / ${num(c.sst,0)}°F`,`${weatherName(c.weatherCode)}`),
      card("Visibility / rain",`${num(c.visibility===null?null:c.visibility/1609.344)} mi / ${num(c.rain)} mm`,"Forecast at the selected hour"),
      card(`${family==="gfs"?"ECMWF":"NOAA GFS"} comparison`,`${num(other.wind)} / ${num(other.gust)} kt`,`${num(other.sea.height)} ft seas · score uses rougher values`),
    ].join("")}</div>
    <details class="rating-notes"><summary>${rating.conditions===null?"Why no score":rating.confidence==="Low"?"Why confidence is low":"Rating & location details"}</summary><p>${esc(reasons)}</p><p>${esc(POINTS[point].name)}. Day buttons show the lowest hourly conditions score for ${esc(dayRating?.window||"7 a.m.–1 p.m.")}${dayRating?.sampleCount?` (${dayRating.sampleCount} hourly samples)`:""}. This hour is scored separately. Bite potential remains unknown. Scores do not assess the harbor entrance or your routed trip.</p>${dayRating?.reasons?.length?`<p>Day confidence: ${esc(dayRating.reasons.join(" · "))}</p>`:""}</details>`;
}
