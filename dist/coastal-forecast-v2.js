// Coastwide model context at the current map center. This is not a routed trip,
// an entrance assessment, or a forecast of fish presence.
const zone='America/Los_Angeles';
const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const finite=value=>typeof value==='number'&&Number.isFinite(value)&&value>=0?value:null;
const one=value=>value===null?'—':value.toFixed(1);
const modelValue=(packet,field,model,index)=>finite(packet?.hourly?.[`${field}_${model}`]?.[index]);
function morningMax(packet,field,model,date){
  const times=packet?.hourly?.time;
  if(!Array.isArray(times))return null;
  const values=[];
  for(let hour=7;hour<=13;hour++){
    const time=`${date}T${String(hour).padStart(2,'0')}:00`,index=times.indexOf(time),value=index<0?null:modelValue(packet,field,model,index);
    if(value===null)return null;
    values.push(value);
  }
  return Math.max(...values);
}
const direction=value=>value===null?'—':['N','NE','E','SE','S','SW','W','NW'][Math.round(value/45)%8];
export function gridDistanceNm(from,to){
  if(![from.latitude,from.longitude,to?.latitude,to?.longitude].every(Number.isFinite))return Infinity;
  const rad=Math.PI/180,dLat=(to.latitude-from.latitude)*rad,dLon=(to.longitude-from.longitude)*rad;
  const a=Math.sin(dLat/2)**2+Math.cos(from.latitude*rad)*Math.cos(to.latitude*rad)*Math.sin(dLon/2)**2;
  return 3440.065*2*Math.asin(Math.min(1,Math.sqrt(a)));
}

export function modelURLs(latitude,longitude) {
  if(!Number.isFinite(latitude)||!Number.isFinite(longitude)||latitude<32.4||latitude>42.1||longitude< -126||longitude> -116.7)throw Error('Outside California model coverage');
  const common={latitude:latitude.toFixed(2),longitude:longitude.toFixed(2),forecast_days:'8',timezone:zone,cell_selection:'sea'};
  const wind=new URLSearchParams({...common,models:'ecmwf_ifs025,gfs_global',wind_speed_unit:'kn',hourly:'wind_speed_10m,wind_gusts_10m,wind_direction_10m,visibility,precipitation'});
  const wave=new URLSearchParams({...common,models:'ecmwf_wam025,ncep_gfswave025',length_unit:'imperial',hourly:'wave_height,swell_wave_height,swell_wave_period,swell_wave_direction,secondary_swell_wave_height,secondary_swell_wave_period,secondary_swell_wave_direction,wind_wave_height,wind_wave_period,wind_wave_direction'});
  return {wind:`https://api.open-meteo.com/v1/forecast?${wind}`,wave:`https://marine-api.open-meteo.com/v1/marine?${wave}`};
}

export function morningRows(wind,wave,now=new Date()) {
  const dates=new Set();
  const parts=Object.fromEntries(new Intl.DateTimeFormat('en-US',{timeZone:zone,year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(now).map(part=>[part.type,part.value]));
  const today=`${parts.year}-${parts.month}-${parts.day}`;
  const times=wave?.hourly?.time;
  if(wind?.timezone!==zone||wave?.timezone!==zone||!Array.isArray(times)||!Array.isArray(wind?.hourly?.time))return [];
  const rows=[];
  for(const time of times){
    if(typeof time!=='string'||!/^\d{4}-\d{2}-\d{2}T10:00$/.test(time))continue;
    const date=time.slice(0,10);if(date<=today||dates.has(date)||rows.length>=7)continue;
    const wi=wind.hourly.time.indexOf(time),wa=wave.hourly.time.indexOf(time);
    if(wi<0||wa<0)continue;
    dates.add(date);
    const g=morningMax(wind,'wind_speed_10m','gfs_global',date),e=morningMax(wind,'wind_speed_10m','ecmwf_ifs025',date);
    const gg=morningMax(wind,'wind_gusts_10m','gfs_global',date),eg=morningMax(wind,'wind_gusts_10m','ecmwf_ifs025',date);
    const gw=morningMax(wave,'wave_height','ncep_gfswave025',date),ew=morningMax(wave,'wave_height','ecmwf_wam025',date);
    const swell=modelValue(wave,'swell_wave_height','ncep_gfswave025',wa),period=modelValue(wave,'swell_wave_period','ncep_gfswave025',wa);
    const secondary=modelValue(wave,'secondary_swell_wave_height','ncep_gfswave025',wa),secondPeriod=modelValue(wave,'secondary_swell_wave_period','ncep_gfswave025',wa);
    const chop=modelValue(wave,'wind_wave_height','ncep_gfswave025',wa);
    const windDirection=direction(modelValue(wind,'wind_direction_10m','gfs_global',wi));
    const flags=[];
    if([g,e,gg,eg,gw,ew].some(v=>v===null))flags.push('incomplete model coverage');
    for(let hour=7;hour<=13;hour++){
      const hourTime=`${date}T${String(hour).padStart(2,'0')}:00`,index=wind.hourly.time.indexOf(hourTime);
      if(index<0)continue;
      if(['ecmwf_ifs025','gfs_global'].some(m=>{const speed=modelValue(wind,'wind_speed_10m',m,index),gust=modelValue(wind,'wind_gusts_10m',m,index);return speed!==null&&gust!==null&&gust<speed;})){flags.push('gust below sustained wind');break;}
    }
    if(g!==null&&e!==null&&Math.abs(g-e)>4)flags.push('wind models differ >4 kt');
    if(gw!==null&&ew!==null&&Math.abs(gw-ew)>1)flags.push('wave models differ >1 ft');
    rows.push({date,time,wind:[e,g],gust:[eg,gg],waves:[ew,gw],windDirection,swell,period,swellDirection:direction(modelValue(wave,'swell_wave_direction','ncep_gfswave025',wa)),secondary,secondPeriod,secondaryDirection:direction(modelValue(wave,'secondary_swell_wave_direction','ncep_gfswave025',wa)),chop,flags});
  }
  return rows;
}

async function getJSON(url,signal){const response=await fetch(url,{signal});if(!response.ok)throw Error(`model service HTTP ${response.status}`);const data=await response.json();if(data?.error)throw Error(data.reason||'model service error');return data;}
let generation=0,cache=new Map();
export async function updateCoastalForecast(root,point,sector){
  const id=++generation;
  root.innerHTML=`<h1>Weather & ocean · ${esc(sector?.name||'current map area')}</h1><p>Loading two wind and two wave models at the nearest sea grid…</p>`;
  try{
    const key=`${point.latitude.toFixed(2)},${point.longitude.toFixed(2)}`;
    let record=cache.get(key);
    if(!record||Date.now()-record.at>1800000){
      const urls=modelURLs(point.latitude,point.longitude),controller=new AbortController(),timer=setTimeout(()=>controller.abort(),16000);
      try{const [wind,wave]=await Promise.all([getJSON(urls.wind,controller.signal),getJSON(urls.wave,controller.signal)]);record={wind,wave,urls,at:Date.now()};cache.set(key,record);if(cache.size>12)cache.delete(cache.keys().next().value);}
      finally{clearTimeout(timer);}
    }
    if(id!==generation)return;
    const {wind,wave,urls}=record;
    const windDistance=gridDistanceNm(point,wind),waveDistance=gridDistanceNm(point,wave);
    const near=windDistance<=30&&waveDistance<=30;
    const rows=near?morningRows(wind,wave):[];
    const available=rows.length;
    root.innerHTML=`<h1>Weather & ocean · ${esc(sector?.name||'current map area')}</h1>
      <p class="small">Requested ${point.latitude.toFixed(2)}°, ${point.longitude.toFixed(2)}° · wind grid ${esc(wind.latitude)}, ${esc(wind.longitude)} (${one(windDistance)} nm away) · wave grid ${esc(wave.latitude)}, ${esc(wave.longitude)} (${one(waveDistance)} nm away). Model output accessed ${new Date(record.at).toLocaleString('en-US',{timeZone:zone})} Pacific; model run issue times are not provided by this response.</p>
      <p>Seven-day model outlook. Wind, gust and combined seas are the highest hourly values from 7 a.m.–1 p.m. Pacific; swell components and direction are 10 a.m. snapshots. A dash means missing coverage, never calm. This does not rate harbor entrances, currents, legality, or fish presence.</p>
      ${available?`<div class="coastal-forecast-grid">${rows.map(row=>`<article class="coastal-forecast-card"><h2>${esc(new Date(row.date+'T12:00:00Z').toLocaleDateString('en-US',{timeZone:zone,weekday:'short',month:'short',day:'numeric'}))}</h2><p><strong>Max wind</strong> ${one(row.wind[0])} / ${one(row.wind[1])} kt<br><small>IFS / GFS · max gust ${one(row.gust[0])} / ${one(row.gust[1])} kt · 10 a.m. GFS ${row.windDirection}</small></p><p><strong>Max seas</strong> ${one(row.waves[0])} / ${one(row.waves[1])} ft<br><small>WAM / GFS Wave</small></p><p><strong>10 a.m. primary swell</strong> ${one(row.swell)} ft @ ${one(row.period)} s ${row.swellDirection}<br><strong>Secondary</strong> ${one(row.secondary)} ft @ ${one(row.secondPeriod)} s ${row.secondaryDirection}<br><strong>Wind waves</strong> ${one(row.chop)} ft <small>(GFS Wave)</small></p>${row.flags.length?`<p class="model-flags">${esc(row.flags.join('; '))}</p>`:''}</article>`).join('')}</div>`:`<p>${near?'Model coverage for this location is unavailable':'The nearest sea grid is more than 30 nm from the map center'}. Conditions are unknown here, not calm.</p>`}
      <p class="small">Open-Meteo distributes <a href="${esc(urls.wind)}" target="_blank" rel="noopener">ECMWF IFS and NOAA GFS wind data ↗</a> and <a href="${esc(urls.wave)}" target="_blank" rel="noopener">ECMWF WAM and NOAA GFS Wave data ↗</a>. The model pairs are distinct underlying models; Open-Meteo is the access service. Wave components are displayed from GFS Wave only because WAM does not populate them here. Recheck <a href="https://www.weather.gov/marine/" target="_blank" rel="noopener">NWS marine forecasts and advisories ↗</a> and entrance conditions before departure.</p>`;
  }catch(error){if(id!==generation)return;root.innerHTML=`<h1>Weather & ocean · ${esc(sector?.name||'current map area')}</h1><p>Local model feed unavailable: ${esc(error.message)}. Conditions are unknown, not calm.</p><p><a href="https://www.weather.gov/marine/" target="_blank" rel="noopener">NWS marine forecasts ↗</a></p>`;}
}
