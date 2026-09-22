import { getRegion, assetURL } from "./region.js?v=8.11";
import { esc } from "./marine-charts.js?v=8.11";
import { loadDailyEvidence } from "./bite-evidence.js?v=8.11";

const HOUR = 3600000;
export const requiredRuleIDs = (region=getRegion()) => [...new Set(region.species.flatMap(id=>id==='reef'?['lingcod','rockfish']:[id]))];
export function ruleMethods(data,species) {
  const methods=data?.species?.[species]?.methods;
  if(methods && Object.keys(methods).length) return Object.entries(methods).map(([id,p])=>[id,p.label||({rod:'Rod and reel',hoop:'Hoop net',hand:'Hand capture',trap:'Crab trap',snare:'Snare'}[id]||id)]);
  return species==='lobster'?[['hoop','Hoop net'],['hand','Hand capture']]:species==='dungeness'?[['trap','Crab trap'],['hoop','Hoop net'],['snare','Snare']]:[['rod','Rod and reel']];
}
const dateFormat = new Intl.DateTimeFormat("en-CA", {
  timeZone: getRegion().timezone, year: "numeric", month: "2-digit", day: "2-digit",
});
const dateOnly = (s) => /^\d{4}-\d{2}-\d{2}$/.test(s || "") && Number.isFinite(Date.parse(s)) && new Date(s).toISOString().slice(0,10)===s;
const validOpening = (w) => w.start_at === undefined || (typeof w.start_at === 'string' && /T\d{2}:\d{2}:\d{2}(?:Z|[+-]\d{2}:\d{2})$/.test(w.start_at) && Number.isFinite(Date.parse(w.start_at)) && dateFormat.format(new Date(w.start_at)) === w.start);
const age = (s, now) => (now - Date.parse(s)) / HOUR;
const time = (s) => Number.isFinite(Date.parse(s)) ? new Date(s).toLocaleString("en-US", {
  timeZone: getRegion().timezone, month: "short", day: "numeric", year: "numeric",
  hour: "numeric", minute: "2-digit",
}) + " PT" : "Unavailable";
export function officialURL(value) {
  try {
    const u = new URL(value);
    const hosts = getRegion().regulatory_authority_hosts || ["wildlife.ca.gov", "nrm.dfg.ca.gov", "www.fisheries.noaa.gov", "www.ecfr.gov"];
    return u.protocol === "https:" && !u.username && !u.password && hosts.includes(u.hostname) ? u.href : "https://wildlife.ca.gov/Fishing/Ocean";
  } catch { return "https://wildlife.ca.gov/Fishing/Ocean"; }
}
export function sourceIssues(data, ids, now = Date.now()) {
  return ids.filter((id) => {
    const s = data.checks?.[id], definition = data.sources?.[id], approved = definition?.approved_content_sha256;
    return !s || s.status !== 'unchanged' || s.source_status !== 'ok' || s.url !== definition?.url ||
      s.normalization !== definition?.normalization ||
      !/^[a-f0-9]{64}$/.test(approved || '') || s.content_sha256 !== approved ||
      !Number.isFinite(age(s.data_retrieved_at, now)) || age(s.data_retrieved_at, now) < -1 || age(s.data_retrieved_at, now) > 36;
  });
}
export function areaNoticesHTML(data, now = Date.now(), location = null) {
  const all = data.area_notices || [];
  const notices = location ? all.filter(n=>location.noticeIds?.includes(n.id)) : all;
  const other=location?all.filter(n=>!location.noticeIds?.includes(n.id)):[];
  const more=other.length?`<details data-reg-section="other-access"><summary>Other regional access notices (${other.length})</summary>${areaNoticesHTML({...data,area_notices:other},now)}</details>`:'';
  if (!notices.length) return more;
  return `<details data-reg-section="local-access"><summary>${location?'Nearby rules &amp; access':'Area rules &amp; island access'}</summary><p>These notices apply in or near ${esc(location?.name||'this region')}. Their exact legal boundaries, dates and methods control; the browsing area is not a closure boundary.</p>${notices.map(n => {
    const issues = sourceIssues(data, n.source_ids, now);
    if (data.rules_review_status !== 'reviewed') issues.push('rule-content');
    return `<section class="reg-area-notice"><h3>${esc(n.name)}</h3><p>${esc(n.note)}</p><p>${issues.length ? 'Rule-source check incomplete or changed: verify the official notices.' : 'Rule sources match the reviewed versions.'}${n.live_clearance_required ? ' Current operational clearance has not been verified; check before entry.' : ''}</p><div class="reg-links">${n.source_ids.map(id => `<a href="${esc(officialURL(data.sources[id].url))}" target="_blank" rel="noopener">${esc(data.sources[id].name)} ↗</a>`).join('')}</div></section>`;
  }).join('')}</details>${more}`;
}
export function validRegulations(data) {
  return data?.schema_version === 1 && Number.isFinite(Date.parse(data.reviewed_at)) &&
    dateOnly(data.valid_from) && dateOnly(data.valid_through) && data.valid_from <= data.valid_through &&
    data.sources && data.checks && Array.isArray(data.common_notes) &&
    (!data.area_notices || Array.isArray(data.area_notices) && data.area_notices.every(n =>
      typeof n.id === 'string' && typeof n.name === 'string' && typeof n.note === 'string' &&
      Array.isArray(n.source_ids) && n.source_ids.length && n.source_ids.every(id => data.sources[id]?.url))) &&
    requiredRuleIDs().every((id) => {
      const p = data.species?.[id];
      return p && [p.name, p.season, p.bag, p.size].every((x) => typeof x === "string") &&
        Array.isArray(p.details) && p.details.every((s) => typeof s === "string") &&
        Array.isArray(p.source_ids) && p.source_ids.length > 0 && p.source_ids.every((s) => data.sources[s]?.url) &&
        Array.isArray(p.windows) && p.windows.every((w) => dateOnly(w.start) && dateOnly(w.end) && w.start <= w.end && validOpening(w));
    });
}

export function localizeRuleState(state, location) {
  if(!location)return state;
  const protection=location.protection;
  if(location.coverage==='discovery')return {...state,status:'unknown',label:'Offshore rules: verify',reason:'Regional forecast and offshore search context are available here. The exact location or full search area is outside the reviewed fishing footprint, so nearby seasonal limits cannot authorize fishing here.'};
  if(location.coverage!=='covered' || location.regionId!==getRegion().id)return {...state,status:'unknown',label:'Location not covered',reason:location.coverage==='mixed'?'This area crosses the reviewed regional footprint. Check the rules for every part of the area.':'This location is outside the loaded region’s reviewed coverage. Local targets and season clearance are unavailable.'};
  if(protection?.status==='excluded')return {...state,status:'excluded',label:'Protected area',reason:`${protection.names.join('; ')}. SkipperCast withholds fishing targets in all mapped protected areas, including conservation areas that allow some activities. Consult the exact official rules.${protection.fresh?'':' The boundary check also needs refreshing.'}`};
  if(protection?.status!=='clear')return {...state,status:'unknown',label:'Check local boundaries',reason:'The protected-area check is unavailable or stale. Saved seasonal limits do not clear this location.'};
  return state;
}
export function regulationState(data, species, now = Date.now(), tripDate = null, method = null, tripInstant = null, location = null) {
  if (species === "reef") {
    const members = ["lingcod", "rockfish"].map((id) => regulationState(data, id, now, tripDate, method, tripInstant,location));
    const status = ["excluded", "unknown", "closed", "scheduled", "restricted", "open"].find((s) => members.some((m) => m.status === s));
    return { ...members.find((m) => m.status === status), members,
      issues: [...new Set(members.flatMap((m) => m.issues))],
      label: status === "closed" && members.some((m) => m.status !== "closed") ? "Check both seasons" : members.find((m) => m.status === status).label };
  }
  const today = dateOnly(tripDate) ? tripDate : dateFormat.format(new Date(now));
  if (!validRegulations(data) || !data?.species?.[species])
    return { status: "unknown", label: "Check rules", today, reason: "Regulations unavailable. Open the official CDFW rules before fishing.", issues: [] };
  const p = data.species[species];
  const issues = sourceIssues(data, p.source_ids, now);
  const reviewed = today >= data.valid_from && today <= data.valid_through && age(data.reviewed_at, now) >= -1;
  const window = p.windows.find((w) => today >= w.start && today <= w.end);
  let status = !window ? "closed" : window.requires_opening_review ? "scheduled" : window.restriction ? "restricted" : "open";
  let reason = status === "closed" ? "Outside the reviewed local season." : status === "scheduled" ?
    "Scheduled opening only. A new review of season, health and trap restrictions is required before showing open." :
    "Local closures, MPAs and gear restrictions still apply.";
  if(window?.restriction) reason=window.restriction;
  const opening = window?.start_at ? Date.parse(window.start_at) : null;
  const timedTrip = Number.isFinite(tripInstant) && dateFormat.format(new Date(tripInstant)) === today ? tripInstant : !tripDate ? now : null;
  let timingNote = null, timedRestriction = false;
  if (opening !== null && today === window.start) {
    timingNote = `Season starts ${time(window.start_at)}. The opening date is not an all-day opening.`;
    if (timedTrip !== null && timedTrip < opening) {status='closed';reason=`Before the legal opening time. ${timingNote}`;}
    else if (timedTrip === null && status === 'open') {status='restricted';timedRestriction=true;reason=timingNote;}
  }
  if (data.rules_review_status !== 'reviewed') {
    status = 'unknown';
    reason = 'Saved regulatory content needs review. Consult the official rules before fishing.';
  } else if (!reviewed) {
    status = "unknown";
    reason = "This date is outside the reviewed rule period. Current-year rules need review.";
  } else if (issues.length) {
    status = "unknown";
    reason = issues.some((id) => data.checks[id]?.status === "changed") ?
      "An official source changed after review. The saved limits below may have changed; check CDFW." :
      "The daily source check is incomplete or over 36 hours old. Check CDFW; saved rules are shown below.";
  }
  const methodProfile=p.methods?.[method];
  const methodReason=methodProfile?.note || null;
  if (methodProfile?.requires_clearance && status==='open') {status='scheduled';reason='Season and permission for this gear are separate. Check the current gear clearance before setting it.';}
  return localizeRuleState({ method, methodReason, timingNote, status, label: timedRestriction && status==='restricted' ? 'Opening time applies' : { restricted: "Depth / species restrictions", open: "Season open", closed: "Season closed", scheduled: "Opener unconfirmed", unknown: "Check rules" }[status], today, reason, issues, profile: p },location);
}

export function regulationsHTML(data, species, now = Date.now(), fallback = false, tripDate = null, method = null, tripInstant = null, includeAreas = true, location = null) {
  const state = regulationState(data, species, now, tripDate, method, tripInstant, location);
  const summary = `<summary><span>Rules</span><span class="reg-badge reg-${state.status}" aria-live="polite">${esc(state.label)}</span><span class="reg-chevron" aria-hidden="true">⌄</span></summary>`;
  const localNote=location?`<p class="reg-local"><strong>${esc(location.source)} · ${esc(location.name)}</strong><br>${location.point.latitude.toFixed(5)}, ${location.point.longitude.toFixed(5)}${location.targetNote?`<br>${esc(location.targetNote)}${location.targetSource?` <a href="${esc(officialURL(location.targetSource))}" target="_blank" rel="noopener">Official source ↗</a>`:''}`:''}</p>`:'';
  if(location && (location.coverage!=='covered'||location.regionId!==getRegion().id))return summary+`<div class="reg-body">${localNote}<p>${esc(state.reason)}</p><p>${location.coverage==='discovery'?'Offshore targets are search references, with fish presence unverified. Check U.S. versus Mexican waters, federal rules and trip-wide possession limits before fishing.':'Pan back into a mapped region or choose one in Options. Neighboring rules are not transferred to this location.'}</p><a class="reg-official" href="https://wildlife.ca.gov/Fishing/Ocean/Regulations/Fishing-Map" target="_blank" rel="noopener">Official CDFW regional rules ↗</a></div>`;
  if (species === "reef" && validRegulations(data)) {
    const ids = ["lingcod", "rockfish"];
    const seasonsMatch = data.species.lingcod.season === data.species.rockfish.season;
    return summary + `<div class="reg-body" tabindex="0" aria-label="Lingcod and rockfish regulation details">
      ${localNote}<div class="reg-context">Trip date · ${esc(state.today)} · ${esc(getRegion().timezone)}</div>
      <h2>Lingcod &amp; rockfish</h2><p class="reg-area">${esc(getRegion().name)} · recreational boat fishing</p>
      <p class="reg-notice reg-${state.status}">${esc(state.reason)}</p>
      ${seasonsMatch ? `<p>${esc(data.species.lingcod.season)}</p>` : "<p>Check each species’ season below.</p>"}
      ${ids.map((id) => `<section class="reg-combined-limit"><h3>${esc(data.species[id].name)}</h3><p>${esc(data.species[id].bag)}</p><p>${esc(data.species[id].size)}</p></section>`).join("")}
      <p class="reg-separate">Keep the limits separate. Rockfish identification and species sublimits matter.</p>
      ${ids.map((id) => `<details class="reg-child" data-reg-section="${id}"><summary>${id === "lingcod" ? "Lingcod" : "Rockfish"} gear, sublimits &amp; sources</summary>${regulationsHTML(data, id, now, fallback, tripDate, method, tripInstant, false,location).replace(/^<summary>[\s\S]*?<\/summary>/, "")}</details>`).join("")}
      ${areaNoticesHTML(data, now,location)}
      <a class="reg-official" href="${esc(officialURL(data.sources["rules-groundfish"].url))}" target="_blank" rel="noopener">Official groundfish rules ↗</a>
    </div>`;
  }
  if (!state.profile) return summary + `<div class="reg-body"><p>${esc(state.reason)}</p><a href="https://wildlife.ca.gov/Fishing/Ocean" target="_blank" rel="noopener">Official CDFW rules ↗</a></div>`;
  const p = state.profile;
  const timestamps = p.source_ids.map((id) => data.checks[id]?.data_retrieved_at).filter((s) => Number.isFinite(Date.parse(s)));
  const checked = timestamps.length === p.source_ids.length ? timestamps.sort((a, b) => Date.parse(a) - Date.parse(b))[0] : null;
  const links = p.source_ids.map((id) => `<a href="${esc(officialURL(data.sources[id].url))}" target="_blank" rel="noopener">${esc(data.sources[id].name)} ↗</a>`).join("");
  return summary + `<div class="reg-body" tabindex="0" aria-label="${esc(p.name)} regulation details">
    ${localNote}<div class="reg-context">Trip date · ${esc(state.today)} · ${esc(getRegion().timezone)}</div>
    <h2>${esc(p.name)}</h2><p class="reg-area">${esc(data.area)}</p>
    <p class="reg-notice reg-${state.status}">${esc(state.reason)}</p>
    ${state.timingNote ? `<p>${esc(state.timingNote)}</p>` : ''}
    ${state.methodReason ? `<p class="reg-notice">${esc(state.methodReason)}</p>` : ""}<dl class="reg-limits"><dt>Season</dt><dd>${esc(p.season)}</dd><dt>Daily / possession limit</dt><dd>${esc(p.bag)}</dd><dt>Minimum size</dt><dd>${esc(p.size)}</dd></dl>
    <details data-reg-section="gear"><summary>Gear, identification & other limits</summary><ul>${p.details.map((s) => `<li>${esc(s)}</li>`).join("")}</ul></details>
    <details data-reg-section="area"><summary>Where these rules apply</summary><p>${esc(data.scope)}</p><ul>${data.common_notes.filter((s) => !["dungeness","lobster"].includes(species) || !s.startsWith("For finfish,")).map((s) => `<li>${esc(s)}</li>`).join("")}</ul><a href="${esc(officialURL(data.official_map_url))}" target="_blank" rel="noopener">CDFW map: check exact position & MPAs ↗</a></details>
    ${includeAreas ? areaNoticesHTML(data, now,location) : ''}
    <div class="reg-freshness"><p>Rules reviewed: ${esc(time(data.reviewed_at))}<br>Oldest required source check: ${esc(time(checked))}${fallback ? " · saved snapshot" : ""}</p><p>Official sources are checked daily. Changes need review; a successful download does not approve new rules. Recheck before each trip.</p></div>
    <a class="reg-official" href="${esc(officialURL(data.sources[p.primary_source_id || p.source_ids[0]].url))}" target="_blank" rel="noopener">Read current official rules ↗</a>
    <details data-reg-section="sources"><summary>All official sources & check status</summary><div class="reg-links">${links}</div>${state.issues.length ? `<p>Needs review / fresh check: ${state.issues.map((id) => esc(data.sources[id].name)).join("; ")}.</p>` : "<p>Required sources match the reviewed versions.</p>"}</details>
  </div>`;
}

export function initRegulations(card, select, {resolveLocation=(v)=>v}={}) {
  let registry = null, fallback = true, species = select.value, lastRefresh = 0;
  let spotViews=[];
  let tripDate = null, tripInstant = null, method = null, followForecast = true;
  let locationContext=null;
  document.addEventListener('skippercast:location',event=>{locationContext=event.detail;species=select.value;render();});
  card.addEventListener('change',event=>{
    if(event.target.id==='rules-trip-date'){tripDate=event.target.value;tripInstant=null;followForecast=false;render();}
    if(event.target.id==='rules-method'){method=event.target.value;render();}
  });
  card.addEventListener('click',event=>{if(event.target.id==='rules-follow-forecast'){followForecast=true;tripDate=lastForecastDate;tripInstant=lastForecastInstant;render();}});
  let lastForecastDate=null,lastForecastInstant=null;
  document.addEventListener('skippercast:time',event=>{
    if(event.detail.regionId!==getRegion().id)return;
    lastForecastInstant=event.detail.epoch*1000;
    lastForecastDate=dateFormat.format(new Date(lastForecastInstant));
    if(followForecast && tripInstant!==lastForecastInstant){tripDate=lastForecastDate;tripInstant=lastForecastInstant;render();}
  });
  function render(open = false) {
    locationContext=resolveLocation(locationContext);
    spotViews=spotViews.filter(v=>v.card.isConnected);
    for(const v of spotViews){
      v.location=resolveLocation(v.location);
      const content=regulationsHTML(registry,v.species,Date.now(),fallback,tripDate,method,tripInstant,true,v.location);
      if(v.card.innerHTML!==content){const expanded=[...v.card.querySelectorAll('[data-reg-section][open]')].map(s=>s.dataset.regSection);v.card.innerHTML=content;for(const section of v.card.querySelectorAll('[data-reg-section]'))section.open=expanded.includes(section.dataset.regSection);}
    }
    const options=ruleMethods(registry,species);
    method=options.some(o=>o[0]===method)?method:options[0][0];
    let html = regulationsHTML(registry ? {...registry, area: getRegion().name + " · " + getRegion().jurisdiction} : null, species, Date.now(), fallback, tripDate, method, tripInstant,true,locationContext);
    const controls=`<div class="rule-controls"><label>Fishing date<input id="rules-trip-date" type="date" value="${tripDate||dateFormat.format(new Date())}"></label><label>Method<select id="rules-method">${options.map(([id,name])=>`<option value="${id}" ${method===id?"selected":""}>${name}</option>`).join("")}</select></label>${followForecast?"":'<button id="rules-follow-forecast">Use forecast date</button>'}</div>`;
    html=html.replace("</summary>","</summary>"+controls);
    if (card.innerHTML !== html) {
      const expanded = [...card.querySelectorAll("[data-reg-section][open]")].map((x) => x.dataset.regSection);
      card.innerHTML = html;
      if (!open) for (const section of card.querySelectorAll("[data-reg-section]")) section.open = expanded.includes(section.dataset.regSection);
    }
    if (open) card.open = true;
  }
  function selected() {
    const changed = species !== select.value;
    species = select.value;
    render(changed);
  }
  select.addEventListener("change", selected);
  document.addEventListener("skippercast:species", selected);
  async function refresh() {
    lastRefresh = Date.now();
    try {
      const result = await loadDailyEvidence();
      const candidate = result.data.regulations;
      if (candidate?.jurisdiction_id === getRegion().jurisdiction_id && validRegulations(candidate) && (!registry || Date.parse(candidate.reviewed_at) >= Date.parse(registry.reviewed_at))) {
        registry = candidate;
        fallback = result.fallback;
      }
    } catch { /* Keep the original check timestamps; stale is never current. */ }
    render();
  }
  render();
  (async () => {
    try {
      const response = await fetch(assetURL("regulations"), { cache: "no-cache", signal: AbortSignal.timeout(10000) });
      if (!response.ok) throw Error("Rules unavailable");
      const candidate = await response.json();
      if (candidate?.jurisdiction_id === getRegion().jurisdiction_id && validRegulations(candidate)) registry = candidate;
    } catch { /* Official links remain available if both data paths fail. */ }
    render();
    await refresh();
  })();
  const tick = () => {
    render();
    if (Date.now() - lastRefresh >= HOUR) refresh();
  };
  setInterval(() => { if (document.visibilityState === "visible") tick(); }, 60000);
  document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible") tick(); });
  // Leaflet must not pan or zoom when interacting with or scrolling the card.
  for (const type of ["pointerdown", "mousedown", "dblclick", "wheel", "touchstart", "touchmove"])
    card.addEventListener(type, (event) => event.stopPropagation(), { passive: true });
  return {mountSpot(container,location,selectedSpecies){
    const spot=document.createElement('details');spot.className='spot-rules';
    spot.innerHTML=regulationsHTML(registry,selectedSpecies,Date.now(),fallback,tripDate,method,tripInstant,true,location);
    container.append(spot);spotViews.push({card:spot,location,species:selectedSpecies});
  }};
}
