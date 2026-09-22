import {getRegion} from "./region.js?v=8.9";
import { futureDates, pacificEpoch, localDate } from "./forecast.js?v=8.9";
import {
  readConditions,
  comfort,
  angleBetween,
  HOUR,
  POINTS,
} from "./marine-data.js?v=8.9";
import { esc, local, num } from "./marine-charts.js?v=8.9";
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
  if (MODELS.some(id=>!Number.isFinite(bundle.models[id]?.meta?.last_run_initialisation_time) || now/1000-bundle.models[id].meta.last_run_initialisation_time>36*HOUR)) return {...empty,reasons:["Model-run freshness cannot be verified"]};
  const c=readConditions(bundle,point,time,"gfs"), other=readConditions(bundle,point,time,"ecmwf");
  const alerts=bundle.alerts?.[POINTS[point].offshore?"offshore":"coastal"];
  const active=Array.isArray(alerts)?alerts.filter(a=>(!Number.isFinite(a.starts)||a.starts<=time)&&(!Number.isFinite(a.ends)||a.ends>=time)).map(a=>a.title):null;
  const state=comfort(c,other,active);
  const recoverable=new Set(["Wind models differ by >4 kt","Wave models differ by >1 ft","Gust below sustained wind: inconsistent source","Comparison model gust is below sustained wind"]);
  const reasons=state.level==="unknown"||state.level==="hazard" ? [...state.flags] : [];
  if (!Number.isFinite(c.secondary.height) || [c.chop,c.secondary].some(part=>part.height>0 && ![part.period,part.from].every(Number.isFinite))) reasons.push("Swell or chop components incomplete");
  if (state.level==="hazard" || reasons.some(r=>!recoverable.has(r))) return {...empty,reasons:[...new Set(reasons)]};
  const gusts=[c,other].filter(m=>Number.isFinite(m.gust)&&m.gust>=m.wind).map(m=>m.gust);
  if (!gusts.length) return {...empty,reasons:["Both gust forecasts are inconsistent; no valid gust comparison"]};
  const result=hourScores(c,other,species,Math.max(...gusts));
  if (gusts.length<2) reasons.push("Inconsistent gust omitted; the other model supplies the gust estimate");
  const uncertain=reasons.length>0;
  if (uncertain) result.conditions=Math.min(7.9,result.conditions);
  return {...result,confidence:uncertain?"Low":"Moderate",reasons,wind:Math.max(c.wind,other.wind),sea:Math.max(c.sea.height,other.sea.height)};
}
function summarizeHours(bundle,point,species,times,now) {
  const rows=times.map(t=>rateHour(bundle,point,species,t,now));
  const result={conditions:null,comfort:null,control:null,bite:null,overall:null,confidence:"Low",reasons:[...new Set(rows.flatMap(r=>r.reasons))],sampleCount:rows.length};
  if (!rows.length || rows.some(r=>!Number.isFinite(r.conditions))) return result;
  for(const k of ["conditions","comfort","control"]) result[k]=rows.every(r=>Number.isFinite(r[k]))?Math.min(...rows.map(r=>r[k])):null;
  result.score_scope=rows[0].score_scope;
  result.wind=Math.max(...rows.map(r=>r.wind)); result.sea=Math.max(...rows.map(r=>r.sea));
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
    if (
      MODELS.some(
        (id) =>
          !Number.isFinite(
            bundle.models[id]?.meta?.last_run_initialisation_time,
          ) ||
          now / 1000 - bundle.models[id].meta.last_run_initialisation_time >
            36 * HOUR,
      )
    ) {
      row.reasons.push("Model-run freshness cannot be verified");
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
  const banner = document.getElementById("best-day-banner");
  banner.classList.toggle("qualifying", !!qualifying.length);
  banner.innerHTML = best
    ? `<span>${comfortOnly?"Daytime boat comfort":best.confidence === "Low" ? "Tentative conditions" : best.provisional ? "Provisional best" : "Best conditions"}</span><strong>${local(best.time, { weekday: "short" })} · ${num(best.conditions)}/10</strong>`
    : "<span>7-day outlook</span><strong>Check conditions</strong>";
  banner.setAttribute("aria-label", best ? `Open seven-day outlook. ${best.confidence === "Low" ? "Tentative best" : "Best conditions"}: ${local(best.time, { weekday: "long" })}, ${num(best.conditions)} out of 10, ${best.confidence} confidence. Bite potential unscored.` : "Open seven-day outlook. Not enough data to rate conditions.");
  banner.dataset.hour = best?.time || "";
  const host = document.getElementById("morning-outlook");
  host.innerHTML = `<details class="morning-summary"><summary>${best ? `${best.confidence === "Low" ? "Tentative best" : "Best"}: ${local(best.time, { weekday: "long" })} · ${num(best.conditions)}/10 conditions` : "Seven-day outlook · ratings unavailable"}<span>${qualifying.length ? `${qualifying.length} morning${qualifying.length === 1 ? "" : "s"} at 8+` : "No verified 8+ conditions yet"}</span></summary><p class="small">${esc(POINTS[point].name)} · 7 a.m.–1 p.m. Pacific. ${comfortOnly?"This ranks modeled boat comfort only; lobster gear handling and diving are unscored. Inspect the actual night fishing and return hours separately.":"This ranks modeled comfort and gear control across the entire window."} Bite potential and an overall bite-plus-comfort rating are unavailable. It is not a routed trip or entrance clearance.</p><div class="morning-days">${rows.map((r) => `<button class="morning-day ${r.conditions >= 8 ? "good" : ""}" data-morning="${r.time}"><strong>${local(r.time, { weekday: "short", month: "numeric", day: "numeric" })}</strong><b>${r.conditions === null ? "Unrated" : num(r.conditions) + "/10"}</b><span>${r.confidence}${r.provisional ? " · provisional" : ""} · ${r.conditions === null ? esc(r.reasons[0]) : "comfort " + num(r.comfort) + (comfortOnly?" · gear unscored":" / control " + num(r.control))}</span></button>`).join("")}</div><details><summary>How the rating works</summary><p class="small">${comfortOnly?"Lobster shows the lowest modeled boat-comfort result from 7 a.m. through 1 p.m.; hoop handling, night operations and diving safety are unscored.":"A disclosed planning heuristic: take the lower of comfort and gear-control scores, then the lowest hourly result from 7 a.m. through 1 p.m."} Use the rougher model’s wind, gusts and combined seas, plus GFS chop and crossing swells. Missing critical inputs, stale runs, fog, storms or active marine alerts prevent a rating. If only one model has an inconsistent gust below its sustained wind, that gust is omitted, the other model supplies the gust estimate, and the displayed score is capped at 7.9 with Low confidence. Both sustained-wind forecasts still contribute. With material model disagreement, use the rougher forecast, label Low confidence and cap the conditions rating at 7.9. Surface current does not estimate bottom drift. Recent charter reports and ocean observations appear in the fishing-evidence panel. Exact fish presence, forage and pressure remain unknown; the evidence is not converted into a bite-probability score.</p><a href="species-research.html#morning-ratings">Full score formula ↗</a></details></details>`;
  return best;
}
