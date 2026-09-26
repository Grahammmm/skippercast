import {getRegion} from "./region.js?v=8.12";
import { futureDates, pacificEpoch, localDate } from "./forecast.js?v=8.12";
import {
  readConditions,
  comfort,
  angleBetween,
  HOUR,
  POINTS,
} from "./marine-data.js?v=8.12";
import { esc, local, num } from "./marine-charts.js?v=8.12";
const MODELS = [
  "gfs_global",
  "ecmwf_ifs025",
  "ncep_gfswave025",
  "ecmwf_wam025",
];
const clamp = (n) => Math.round(Math.max(0, Math.min(10, n)) * 10) / 10;
export function hourScores(c, other, species, checkedGust = Math.max(c.gust, other.gust)) {
  const wind = Math.max(c.wind, other.wind),
    gust = checkedGust,
    sea = Math.max(c.sea.height, other.sea.height);
  const crossing =
    c.secondary.height >= 1 &&
    angleBetween(c.swell.from, c.secondary.from) >= 60
      ? 0.7
      : 0;
  const short = c.chop.height >= 0.5 && c.chop.period <= 6 ? 0.8 : 0;
  const comfortScore = clamp(
    10 -
      Math.max(0, wind - 4) * 0.22 -
      Math.max(0, gust - 7) * 0.1 -
      Math.max(0, sea - 1.5) * 0.7 -
      Math.max(0, c.chop.height - 0.4) * 0.9 -
      crossing -
      short,
  );
  const mode=getRegion().target_options?.find(t=>t.id===species)?.control_mode || (["reef","lingcod","rockfish","halibut","dungeness"].includes(species)?'bottom':'water-column');
  const bottom=mode==='bottom';
  const controlScore = clamp(
    10 -
      Math.max(0, wind - 4) * (bottom ? 0.32 : 0.22) -
      Math.max(0, gust - 8) * 0.08 -
      Math.max(0, c.chop.height - 0.4) * (bottom ? 1.1 : 0.8) -
      Math.max(0, sea - 2) * 0.45 -
      crossing -
      short,
  );
  return {
    comfort: comfortScore,
    control: mode==='boat-comfort'?null:controlScore,
    conditions: mode==='boat-comfort'?comfortScore:Math.min(comfortScore, controlScore),
    score_scope: mode==='boat-comfort'?'boat-comfort':'comfort-and-control',
    bite: null,
    overall: null,
  };
}
// A conditions estimate is distinct from confidence or permission to make a trip.
// Invalid gusts remain flagged, and are never silently raised to sustained wind.
export function rateHour(bundle, point, species, time, now=Date.now()) {
  const empty={conditions:null,comfort:null,control:null,bite:null,overall:null,confidence:"Low",reasons:[]};
  if (!bundle || now-bundle.retrieved>3*3600000) return {...empty,reasons:["Fresh forecasts unavailable"]};
  const usable=id=>{
    const m=bundle.models?.[id], issued=m?.meta?.last_run_initialisation_time;
    return m?.data?.[point] && Number.isFinite(issued) && now/1000-issued<=36*HOUR &&
      (!Number.isFinite(m.retrieved)||now-m.retrieved<=3*3600000);
  };
  const gfsWind=usable("gfs_global"), gfsWave=usable("ncep_gfswave025");
  const ecmwfWind=usable("ecmwf_ifs025"), ecmwfWave=usable("ecmwf_wam025");
  const gfs=readConditions(bundle,point,time,"gfs"), ecmwf=readConditions(bundle,point,time,"ecmwf");
  if(!gfsWind) for(const k of ["wind","gust","windFrom","visibility","weatherCode"]) gfs[k]=null;
  if(!ecmwfWind) for(const k of ["wind","gust","windFrom","visibility","weatherCode"]) ecmwf[k]=null;
  if(!gfsWave) for(const k of ["sea","chop","swell","secondary"]) gfs[k]={height:null,period:null,from:null};
  if(!ecmwfWave) for(const k of ["sea","chop","swell","secondary"]) ecmwf[k]={height:null,period:null,from:null};
  const c=gfs, other=ecmwf;
  const alerts=bundle.alerts?.[POINTS[point].offshore?"offshore":"coastal"];
  const active=Array.isArray(alerts)?alerts.filter(a=>(!Number.isFinite(a.starts)||a.starts<=time)&&(!Number.isFinite(a.ends)||a.ends>=time)).map(a=>a.title):null;
  const state=comfort(c,other,active);
  const reasons=state.level==="unknown"||state.level==="hazard" ? [...state.flags] : [];
  if(!gfsWind||!gfsWave) reasons.push("NOAA GFS forecast unavailable or outside verified model coverage");
  if(!ecmwfWind||!ecmwfWave) reasons.push("ECMWF comparison unavailable or outside verified model coverage");
  const winds=[c.wind,other.wind].filter(Number.isFinite), seas=[c.sea.height,other.sea.height].filter(Number.isFinite);
  if(!winds.length||!seas.length) return {...empty,reasons:[...new Set([...reasons,"No usable wind and combined-sea forecast for this hour"])]};
  const wind=Math.max(...winds), sea=Math.max(...seas);
  const gusts=[c,other].filter(m=>Number.isFinite(m.wind)&&Number.isFinite(m.gust)&&m.gust>=m.wind).map(m=>m.gust);
  const complete=gfsWind&&gfsWave&&ecmwfWind&&ecmwfWave&&
    [c.wind,c.windFrom,c.visibility,c.weatherCode,c.sea.height,c.sea.period,c.sea.from,c.chop.height,c.swell.height,c.swell.period,c.swell.from,c.secondary.height,other.wind,other.sea.height].every(Number.isFinite)&&
    ![c.chop,c.secondary].some(part=>part.height>0&&![part.period,part.from].every(Number.isFinite))&&gusts.length===2;
  let result;
  if(complete){
    result=hourScores(c,{wind:other.wind,sea:{height:other.sea.height}},species,Math.max(...gusts));
  }else{
    // A limited outlook uses only observed forecast fields. Missing chop, swell or
    // gust is never substituted with zero; the score cannot clear the 8+ banner.
    const mode=getRegion().target_options?.find(t=>t.id===species)?.control_mode || (["reef","lingcod","rockfish","halibut","dungeness"].includes(species)?'bottom':'water-column');
    const bottom=mode==='bottom', gust=gusts.length?Math.max(...gusts):null;
    const comfortScore=clamp(10-Math.max(0,wind-4)*0.22-Math.max(0,sea-1.5)*0.7-(gust===null?0:Math.max(0,gust-7)*0.1));
    const controlScore=clamp(10-Math.max(0,wind-4)*(bottom?0.32:0.22)-Math.max(0,sea-2)*0.45-(gust===null?0:Math.max(0,gust-8)*0.08));
    result={comfort:comfortScore,control:mode==='boat-comfort'?null:controlScore,conditions:Math.min(6.9,mode==='boat-comfort'?comfortScore:Math.min(comfortScore,controlScore)),score_scope:mode==='boat-comfort'?'boat-comfort':'comfort-and-control',bite:null,overall:null};
    reasons.push("Limited estimate from available wind and seas; missing comparison or wave detail");
    if(!gusts.length) reasons.push("Gust forecast unavailable or inconsistent; no gust assumed");
  }
  if(gusts.length===1) reasons.push("Inconsistent gust omitted; one valid gust forecast remains");
  if(MODELS.some(id=>bundle.models[id]?.refreshError)) reasons.push("A source refresh failed; using its recent saved forecast");
  if(state.level==="hazard"){
    result.conditions=Math.min(1.9,result.conditions);
    reasons.push("Marine advisory or visibility hazard; rating capped below a fishable day");
  }
  const uncertain=!complete||reasons.length>0;
  if(uncertain) result.conditions=Math.min(7.9,result.conditions);
  return {...result,confidence:uncertain?"Low":"Moderate",reasons:[...new Set(reasons)],wind,sea,limited:!complete||active===null,hazard:state.level==="hazard"};
}
function summarizeHours(bundle,point,species,times,now) {
  const rows=times.map(t=>rateHour(bundle,point,species,t,now));
  const result={conditions:null,comfort:null,control:null,bite:null,overall:null,confidence:"Low",reasons:[...new Set(rows.flatMap(r=>r.reasons))],sampleCount:rows.length};
  const rated=rows.filter(r=>Number.isFinite(r.conditions));
  result.ratedHours=rated.length;
  if (!rated.length) return result;
  for(const k of ["conditions","comfort","control"]) result[k]=rated.every(r=>Number.isFinite(r[k]))?Math.min(...rated.map(r=>r[k])):null;
  result.score_scope=rated[0].score_scope;
  result.wind=Math.max(...rated.map(r=>r.wind)); result.sea=Math.max(...rated.map(r=>r.sea));
  result.limited=rated.length<rows.length||rated.some(r=>r.limited);
  result.hazard=rated.some(r=>r.hazard);
  if(result.limited){result.conditions=Math.min(result.conditions,6.9);result.reasons.push(`Only ${rated.length} of ${rows.length} hours have usable wind and seas or full detail`);}
  result.confidence=rows.some(r=>r.confidence==="Low")?"Low":"Moderate";
  return result;
}
export function rankTimelineDays(bundle,point,species,hours,now=Date.now()) {
  const dates=[...new Set(hours.map(t=>localDate(new Date(t*1000))))];
  const today=localDate(new Date(now));
  return dates.map((date,i)=>{
    const full=Array.from({length:7},(_,h)=>pacificEpoch(`${date}T${String(h+7).padStart(2,"0")}:00`));
    const remaining=date===today && hours[0]>full.at(-1);
    const candidates=remaining?hours.filter(t=>localDate(new Date(t*1000))===date):full;
    const times=candidates.filter(t=>t>=hours[0]&&t<=hours.at(-1));
    const row=summarizeHours(bundle,point,species,times,now);
    const partial=!remaining&&times.length<7;
    if(partial && row.conditions!==null) {row.conditions=Math.min(row.conditions,7.9);row.confidence="Low";row.reasons.push("Partial morning within the available timeline");}
    return {...row,date,time:times[0]??hours[0],provisional:i>=4,window:remaining?"Remaining today":partial?"Partial 7 a.m.–1 p.m.":"7 a.m.–1 p.m.",partial};
  });
}
export function rankMornings(
  bundle,
  point,
  species,
  now = Date.now(),
  horizon = now / 1000 + 168 * HOUR,
) {
  return futureDates(new Date(now)).map((date, i) => {
    const times = Array.from({ length: 7 }, (_, h) =>
      pacificEpoch(`${date}T${String(h + 7).padStart(2, "0")}:00`),
    );
    const row = {
      date,
      time: times[1],
      point,
      provisional: i >= 3,
      confidence: "Low",
      conditions: null,
      comfort: null,
      control: null,
      bite: null,
      overall: null,
      reasons: [],
    };
    if (!bundle || now - bundle.retrieved > 3 * 3600000) {
      row.reasons.push("Fresh forecasts unavailable");
      return row;
    }
    if (times.at(-1) > horizon) {
      row.reasons.push("Full morning extends beyond the slider window");
      return row;
    }
    return {...row,...summarizeHours(bundle,point,species,times,now)};
  });
}
export function renderOutlook(rows, point) {
  const valid = rows
    .filter((r) => Number.isFinite(r.conditions))
    .sort((a, b) => b.conditions - a.conditions);
  const comfortOnly=rows.some(r=>r.score_scope==='boat-comfort');
  const best = valid[0],
    qualifying = valid.filter((r) => r.conditions >= 8);
  const bestLabel=best?.conditions<4?"Least rough outlook":best?.confidence==="Low"?"Tentative best":"Best";
  const banner = document.getElementById("best-day-banner");
  banner.classList.toggle("qualifying", !!qualifying.length);
  banner.innerHTML = best
    ? `<span>${comfortOnly?"Daytime boat comfort":best.conditions<4?"Least rough outlook":best.confidence === "Low" ? "Tentative conditions" : best.provisional ? "Provisional best" : "Best conditions"}</span><strong>${local(best.time, { weekday: "short" })} · ${num(best.conditions)}/10</strong>`
    : "<span>7-day outlook</span><strong>Check conditions</strong>";
  banner.setAttribute("aria-label", best ? `Open seven-day outlook. ${bestLabel}: ${local(best.time, { weekday: "long" })}, ${num(best.conditions)} out of 10, ${best.confidence} confidence. Bite potential unscored.` : "Open seven-day outlook. Not enough data to rate conditions.");
  banner.dataset.hour = best?.time || "";
  const host = document.getElementById("morning-outlook");
  host.innerHTML = `<details class="morning-summary"><summary>${best ? `${bestLabel}: ${local(best.time, { weekday: "long" })} · ${num(best.conditions)}/10 conditions` : "Seven-day outlook · ratings unavailable"}<span>${qualifying.length ? `${qualifying.length} morning${qualifying.length === 1 ? "" : "s"} at 8+` : "No verified 8+ conditions yet"}</span></summary><p class="small">${esc(POINTS[point].name)} · 7 a.m.–1 p.m. Pacific. ${comfortOnly?"This ranks modeled boat comfort only; lobster gear handling and diving are unscored. Inspect the actual night fishing and return hours separately.":"This ranks modeled comfort and gear control across the entire window."} Bite potential and an overall bite-plus-comfort rating are unavailable. It is not a routed trip or entrance clearance.</p><div class="morning-days">${rows.map((r) => `<button class="morning-day ${r.conditions >= 8 ? "good" : ""}" data-morning="${r.time}"><strong>${local(r.time, { weekday: "short", month: "numeric", day: "numeric" })}</strong><b>${r.conditions === null ? "Unrated" : num(r.conditions) + "/10"}</b><span>${r.confidence}${r.provisional ? " · provisional" : ""} · ${r.conditions === null ? esc(r.reasons[0]) : r.hazard?'hazard':r.limited?'limited forecast':'comfort '+num(r.comfort)+(comfortOnly?' · gear unscored':' / control '+num(r.control))}</span></button>`).join("")}</div><details><summary>How the rating works</summary><p class="small">${comfortOnly?"Lobster shows the lowest modeled boat-comfort result from 7 a.m. through 1 p.m.; hoop handling, night operations and diving safety are unscored.":"A disclosed planning heuristic: take the lower of comfort and gear-control scores, then the lowest hourly result from 7 a.m. through 1 p.m."} A complete rating uses the rougher model’s wind, gusts and combined seas, plus resolved chop and crossing swells. If wind and combined seas exist but a comparison or secondary detail is missing, a limited estimate is capped at 6.9 with Low confidence. An active marine advisory or visibility hazard caps the score at 1.9. Without usable wind or combined seas, there is no score. Missing whole hours also make the day limited. No estimate certifies a routed trip or harbor entrance. Surface current does not estimate bottom drift; fish presence and bite potential remain unknown.</p><a href="species-research.html#morning-ratings">Full score formula ↗</a></details></details>`;
  return best;
}
