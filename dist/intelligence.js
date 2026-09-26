import {getRegion,localContext} from './region.js?v=8.12';
import {esc,num,from,local} from './marine-charts.js?v=8.12';
import {readConditions,angleBetween,distanceNm} from './marine-data.js?v=8.12';

export function freshSource(source,now=Date.now()) {
  if(!source?.data || source.status!=='ok')return false;
  const timestamp=source.data.sample_at||source.data.issued_at||source.data_retrieved_at;
  const age=(now-Date.parse(timestamp))/3600000;
  return Number.isFinite(age)&&age>=-1&&age<=source.max_age_hours;
}
export function memberSummary(members,windLimit=8,gustLimit=12) {
  const winds=members.filter(m=>Number.isFinite(m[1])&&m[1]>=0).map(m=>m[1]).sort((a,b)=>a-b);
  const gusts=members.filter(m=>Number.isFinite(m[2])&&m[2]>=m[1]);
  const quantile=p=>winds.length?winds[Math.round((winds.length-1)*p)]:null;
  return {n:winds.length,p10:quantile(.1),p50:quantile(.5),p90:quantile(.9),
    windPercent:winds.length>=20?100*winds.filter(w=>w>windLimit).length/winds.length:null,
    gustN:gusts.length,gustPercent:gusts.length>=20?100*gusts.filter(m=>m[2]>gustLimit).length/gusts.length:null};
}
export function currentFrame(source,time,now=Date.now()) {
  if(!freshSource(source,now))return null;
  const d=source.data;
  if(d.kind==='observation') {
    if(Math.abs(time-now/1000)>3600)return null;
    return [...d.frames].reverse().find(f=>f.cells.length && f.time<=now/1000+300 && now/1000-f.time<=6*3600)||null;
  }
  // Show a nearby populated three-hour snapshot with its exact time, never interpolate.
  const nearest=d.frames.reduce((best,f)=>!best||Math.abs(f.time-time)<Math.abs(best.time-time)?f:best,null);
  if(time<d.valid_from || time>d.valid_through)return null;
  return nearest&&Math.abs(nearest.time-time)<=5400?nearest:null;
}
export function nearestCurrent(source,time,point,now=Date.now()) {
  const frame=currentFrame(source,time,now);if(!frame)return null;
  const best=frame.cells.map(c=>({cell:c,distance:distanceNm(point,{latitude:c[0],longitude:c[1]})})).sort((a,b)=>a.distance-b.distance)[0];
  if(!best || best.distance*1.852>source.data.resolution_km*1.5)return null;
  return {...best,time:frame.time,kind:source.data.kind};
}
const sourceLink=s=>{let url;try{url=new URL(s?.data?.source_url||s?.url);if(url.protocol!=='https:')return '';}catch{return '';}return `<a href="${esc(url.href)}" target="_blank" rel="noopener">Source & documentation ↗</a>`;};
function statusText(s){return s?`${s.status}${s.data?.sample_at?' · observed '+new Date(s.data.sample_at).toLocaleString('en-US',{timeZone:getRegion().timezone}):s.data?.issued_at?' · run '+new Date(s.data.issued_at).toLocaleString('en-US',{timeZone:getRegion().timezone}):''}`:'Awaiting a current regional feed';}

export function spectrumSVG(frame) {
  const bins=frame?.bins?.filter(b=>b.every(Number.isFinite)&&b[0]>0&&b[1]>=0&&b[2]>=0&&b[2]<=360)||[];
  if(!bins.length)return '<p>No quality-controlled spectral bins available.</p>';
  const maximum=Math.max(...bins.map(b=>b[1]),.001);
  return `<svg class="insight-svg" viewBox="0 0 480 450" role="img" aria-label="Observed wave energy by period and mean incoming direction"><g transform="translate(240 215)">${[5,10,15,20,25].map(p=>`<circle r="${p*7}" fill="none" stroke="#b7d8df" opacity=".2"/><text x="4" y="${-p*7+14}" fill="#e0eff3" font-size="12">${p}s</text>`).join('')}<path d="M0 -185V185M-185 0H185" stroke="#c8e5eb" opacity=".3"/>${bins.map(([f,e,d])=>{const p=1/f,r=Math.min(p,25)*7,a=d*Math.PI/180;return `<circle cx="${Math.sin(a)*r}" cy="${-Math.cos(a)*r}" r="6" fill="#6cf3c6" opacity="${.15+.85*e/maximum}"><title>${num(p)} s · from ${from(d)} · ${num(e,3)} m²/Hz</title></circle>`;}).join('')}<text x="-7" y="-195" fill="white">N</text><text x="197" y="5" fill="white">E</text><text x="-8" y="204" fill="white">S</text><text x="-211" y="5" fill="white">W</text></g><text x="20" y="438" fill="#e0eff3" font-size="14">Brighter = more energy density · outer ring = 25+ seconds</text></svg>`;
}

export function uncertaintyHTML(data,state,limits={wind:8,gust:12}) {
  const point=getRegion().forecast_points[state.point];
  const matches=p=>point&&p.point_id===point.id&&p.requested?.[0]===point.latitude&&p.requested?.[1]===point.longitude;
  const source=data?.sources?.ensemble,p=source?.data?.points?.find(matches);
  const frame=freshSource(source)?p?.frames.find(f=>f.time===state.time):null;
  const s=frame?memberSummary(frame.members,limits.wind,limits.gust):null;
  const wave=data?.sources?.['wave-ensemble'];const rows=freshSource(wave)?wave.data.frames.filter(f=>Math.abs(f.time-state.time)<=5400&&f.threshold_m===1):[];
  const match=rows.sort((a,b)=>Math.abs(a.time-state.time)-Math.abs(b.time-state.time))[0];
  const wp=match?.points.find(matches);
  return `<div class="insight-grid"><div><small>Wind, 10th–90th member range</small><strong>${s?`${num(s.p10)}–${num(s.p90)} kt`:'Unavailable'}</strong><small>${s?`${s.n}/31 members · median ${num(s.p50)} kt`:esc(statusText(source))}</small></div><div><small>Members above ${limits.wind} kt wind</small><strong>${num(s?.windPercent,0)}%</strong><small>Above ${limits.gust} kt gust: ${num(s?.gustPercent,0)}% (${s?.gustN||0} valid members)</small></div><div><small>Seas above 1 m (3.28 ft)</small><strong>${num(wp?.percent,0)}%</strong><small>${match?'NOAA snapshot '+local(match.time,{weekday:'short',hour:'numeric'}):'No nearby populated ensemble hour'}${wp?.grid?` · sea grid ${wp.grid.map(n=>num(n,3)).join(', ')} · ${num(wp.distance_km/1.852)} nm away`:''}</small></div></div><p class="small">Raw ensemble fractions, not calibrated odds or catch probability. NOAA's sea threshold is <b>3.28 ft</b>, not your 3 ft comfort limit. Missing members are excluded; fewer than 20 withholds a wind percentage.</p><p class="insight-status">Wind ${esc(statusText(source))} · ${sourceLink(source)}<br>Waves ${esc(statusText(wave))} · ${sourceLink(wave)}</p>`;
}

export function verificationHTML(data) {
  const v=data?.verification;if(!v)return '<p>Forecast verification feed unavailable.</p>';
  const summary=v.summary, groups=v.groups||[],pairs=v.comparisons||[],collectionNotes={...v.collection_issues,...v.collection_deferrals};
  const count=n=>Number.isFinite(n)?n.toLocaleString():'Unknown';
  const percentage=n=>Number.isFinite(n)?`${Math.round(n*100)}%`:'Not due';
  const range=(values,suffix)=>values?.length&&values.every(Number.isFinite)?values.map(n=>num(n)).join('–')+suffix:'Unknown';
  return `<p><strong>${esc(summary?.headline||v.status)}</strong></p><div class="insight-grid"><div><small>Forecast rows archived in advance</small><strong>${count(v.archived_forecasts)}</strong></div><div><small>Distinct station / variable / weather hours</small><strong>${count(summary?.matched_valid_times)}</strong></div><div><small>Matured forecasts with observations</small><strong>${percentage(summary?.coverage_fraction)}</strong></div></div><p>${esc(summary?.next_action||'The archive is collecting prospective history. No local model winner or automatic correction is assigned.')}</p>${Object.keys(collectionNotes).length?`<details><summary>Collection gaps & deferred samples</summary><ul>${Object.entries(collectionNotes).map(([key,reason])=>`<li><strong>${esc(key)}</strong>: ${esc(typeof reason==='string'?reason:reason?.reason||'Source detail unavailable')}</li>`).join('')}</ul><p class="small">Deferred or rejected samples do not enter the accuracy archive. A later refresh retries them with its actual acquisition time.</p></details>`:''}${groups.length?`<details><summary>Station errors & evidence coverage (${groups.length} groups)</summary><div class="matrix-scroll"><table class="forecast-matrix"><thead><tr><th>Model / station</th><th>Forecast lead</th><th>Mean absolute error / bias</th><th>Unique hours / days</th><th>Coverage / grid distance</th><th>Evidence</th></tr></thead><tbody>${groups.map(g=>`<tr><th>${esc(g.model)} · ${esc(g.station)}<small>${esc(g.variable)}</small></th><td>${g.lead_hours.join('–')} h<small>Acquired ${range(g.acquisition_lead_hours,' h ahead')}</small></td><td>${num(g.mae)} / ${g.bias>0?'+':''}${num(g.bias)} ${esc(g.unit)}</td><td>${count(g.distinct_valid_times)} / ${count(g.distinct_days)}<small>${count(g.n)} matched forecast rows</small></td><td>${percentage(g.coverage_fraction)}<small>${range(g.spatial_match?.distance_km,' km')}</small></td><td>${esc(g.support?.level||g.status)}<small>${esc(g.measurement_comparison||'Measurement basis not recorded')}</small></td></tr>`).join('')}</tbody></table></div></details>`:'<p>Results appear as archived forecasts reach their valid time and matching buoy observations arrive.</p>'}${pairs.length?`<details><summary>Compare models on the same cases</summary>${pairs.map(p=>`<p><strong>${esc(p.station)} · ${esc(p.variable)} · ${p.lead_hours.join('–')} h</strong><br>${esc(p.model_a)} ${num(p.mae_a)} ${esc(p.unit)} MAE; ${esc(p.model_b)} ${num(p.mae_b)} ${esc(p.unit)} MAE.<br><small>${p.distinct_valid_times} unique hours across ${p.distinct_days} days · ${esc(p.status)}. ${p.lower_error_model?'Lower historical error: '+esc(p.lower_error_model)+'. This is descriptive, not a permanent winner.':'Insufficient evidence to choose a model.'}</small></p>`).join('')}</details>`:''}<p class="small">Positive bias means the model ran high. Repeated runs do not create additional weather hours. Missing matches stay unknown. ${esc(v.limitations)}</p>`;
}

export function initIntelligence(map) {
  let data=null,state=null,loading=false,heading=NaN,activeLayer='off';
  const mapLayer=L.layerGroup().addTo(map);
  const container=document.createElement('section');container.id='regional-intelligence';
  container.innerHTML=`<details class="insight-card" open><summary>Forecast range & uncertainty</summary><div id="ensemble-content">Loading ensemble sources…</div></details><details class="insight-card"><summary>Currents · measured and modeled</summary><div class="insight-form"><label>Map layer<select id="regional-current-layer"><option value="off">Off</option><option value="wcofs">NOAA regional forecast</option><option value="hfr-1">Observed HF radar · 1 km</option><option value="hfr-6">Observed HF radar · 6 km</option></select></label></div><div id="currents-content"></div></details><details class="insight-card"><summary>Wave energy & Parker comfort</summary><div class="insight-form"><label>Your heading · ° true<input id="comfort-heading" type="number" min="0" max="359" placeholder="Optional"></label></div><div id="encounter-content"></div><div id="spectral-content"></div><div id="comfort-feedback"></div></details><details class="insight-card"><summary>How the forecasts perform locally</summary><div id="verification-content"></div></details><div id="trip-alerts"></div>`;
  document.getElementById('forecast-content').append(container);
  container.querySelector('#comfort-heading').addEventListener('input',e=>{heading=e.target.value===''?NaN:Number(e.target.value);renderWave();});
  container.querySelector('#regional-current-layer').addEventListener('change',e=>{activeLayer=e.target.value;draw();});
  function renderWave(){
    if(!state)return;const c=readConditions(state.bundle,state.point,state.time,'gfs');
    const parts=[['Primary swell',c.swell],['Secondary swell',c.secondary],['Chop',c.chop]];
    container.querySelector('#encounter-content').innerHTML=`<div class="insight-grid">${parts.map(([name,p])=>{const a=angleBetween(heading,p.from);return `<div><small>${name}</small><strong>${num(p.height)} ft · ${num(p.period)} s</strong><small>${a===null||heading<0||heading>359?'Heading/direction unavailable':`${a<45?'From ahead':a>135?'From astern':'Across the beam'} · ${num(a,0)}° off bow`}</small></div>`;}).join('')}</div><p class="small">${esc(getRegion().boat.name)} · wave exposure, not a validated roll or slamming simulation. Short chop and crossing swells can change comfort.</p>`;
    const station=localContext(state.point).stations[getRegion().forecast_points[state.point]?.offshore?'offshore_buoy':'nearshore_buoy'];
    const source=data?.sources?.['spectra-'+station],frame=freshSource(source)?source.data.frames.at(-1):null;
    container.querySelector('#spectral-content').innerHTML=`<p><strong>Observed energy · buoy ${esc(station)}</strong><br>${esc(statusText(source))}</p>${frame?spectrumSVG(frame):'<p>No fresh spectrum available.</p>'}<p class="small">Each dot is a measured frequency band with its mean incoming direction. This observation stays at its measured time as you browse future forecasts. ${sourceLink(source)}</p>`;
  }
  function draw(){
    mapLayer.clearLayers();if(!state||activeLayer==='off')return;
    const source=data?.sources?.[activeLayer],frame=currentFrame(source,state.time);
    if(!frame)return;
    for(const c of frame.cells){
      const icon=L.divIcon({className:'current-vector',html:`<span style="display:block;transform:rotate(${c[3]}deg);color:${activeLayer==='wcofs'?'#087a90':'#7645a8'};font-size:23px;font-weight:bold">↑</span>`,iconSize:[24,24],iconAnchor:[12,12]});
      L.marker([c[0],c[1]],{icon,title:`${source.name}: ${c[2]} kt toward ${c[3]}°`,keyboard:true}).bindPopup(`<strong>${esc(source.name)}</strong><p>${num(c[2])} kt toward ${from(c[3])}<br>${esc(local(frame.time,{month:'short',day:'numeric',hour:'numeric'}))} · ${source.data.kind}</p><p>Surface flow; not bottom current or boat drift.</p>`).addTo(mapLayer);
    }
  }
  function render(){
    if(!state)return;
    container.querySelector('#ensemble-content').innerHTML=uncertaintyHTML(data,state);
    const point=getRegion().forecast_points[state.point];
    container.querySelector('#currents-content').innerHTML=['wcofs','hfr-1','hfr-6'].map(id=>{const s=data?.sources?.[id],v=nearestCurrent(s,state.time,point);return `<p><strong>${esc(s?.name||id)}</strong><br>${v?`${num(v.cell[2])} kt toward ${from(v.cell[3])} · ${num(v.distance)} nm from forecast sample · ${local(v.time,{weekday:'short',hour:'numeric'})}`:'No fresh, sufficiently close sample for this hour.'}<br><small>${esc(statusText(s))} · ${sourceLink(s)}</small></p>`;}).join('')+'<p class="small">Observed arrows are shown only near now. Regional forecasts use their nearest three-hour snapshot within the published 72-hour horizon. Empty coverage stays empty. WCOFS assimilates radar; these are not independent measurements.</p>';
    container.querySelector('#verification-content').innerHTML=verificationHTML(data);renderWave();draw();
  }
  async function load(){
    if(loading)return;loading=true;
    for(const url of [`/api/intelligence?region=${encodeURIComponent(getRegion().id)}`,getRegion().intelligence_feed,`regions/${getRegion().id}/intelligence.json`].filter(Boolean)){
      try{const response=await fetch(url,{signal:AbortSignal.timeout(15000)});if(!response.ok)continue;const candidate=await response.json();if(candidate.schema_version!==1||candidate.region_id!==getRegion().id)continue;data=candidate;break;}catch{}
    }
    loading=false;render();
  }
  document.addEventListener('skippercast:forecast',event=>{state=event.detail;render();});
  document.getElementById('load-forecast').addEventListener('click',load);
  setInterval(()=>{if(!document.hidden)load();},30*60000);load();
  return {getState:()=>state,getData:()=>data};
}
