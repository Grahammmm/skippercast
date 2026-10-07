// Coastwide model context at the actual map center. Source valid times are UTC;
// Pacific morning summaries are views of those original samples, not forecasts
// for an inferred harbor, routed trip, legal clearance or fish presence.
const zone='America/Los_Angeles',HOUR=3600;
const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const one=value=>typeof value==='number'&&Number.isFinite(value)?value.toFixed(1):'—';
const localFormat=new Intl.DateTimeFormat('en-US',{timeZone:zone,year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',hourCycle:'h23'});
const parts=epoch=>Object.fromEntries(localFormat.formatToParts(new Date(epoch*1000)).map(p=>[p.type,p.value]));
const dateOf=p=>`${p.year}-${p.month}-${p.day}`;
const direction=value=>value===null?'—':['N','NE','E','SE','S','SW','W','NW'][Math.round(value/45)%8];
const expectedUnit=field=>field.endsWith('_height')?'ft':field.endsWith('_period')?'s':field.endsWith('_direction')||field==='wind_direction_10m'?'°':'kn';
function validClock(packet){return ['UTC','GMT'].includes(packet?.timezone)&&packet.utc_offset_seconds===0&&packet?.hourly_units?.time==='unixtime'&&Array.isArray(packet?.hourly?.time)&&packet.hourly.time.every(t=>typeof t==='number'&&Number.isSafeInteger(t)&&t>0&&t%HOUR===0&&Number.isFinite(new Date(t*1000).getTime()));}
function epochIndex(packet,epoch){if(!validClock(packet))return -1;const index=packet.hourly.time.indexOf(epoch);return index>=0&&packet.hourly.time.lastIndexOf(epoch)===index?index:-1;}
function modelValue(packet,field,model,index){
 const key=`${field}_${model}`,value=packet?.hourly?.[key]?.[index];
 if(index<0||packet?.hourly_units?.[key]!==expectedUnit(field)||typeof value!=='number'||!Number.isFinite(value)||value<0)return null;
 if(field.endsWith('_direction')||field==='wind_direction_10m')return value<=360?value:null;
 if(field.endsWith('_period'))return value>0?value:null;
 if(field==='wind_gusts_10m'){const speed=modelValue(packet,'wind_speed_10m',model,index);if(speed===null||value<speed)return null;}
 return value;
}
function gustContradiction(packet,model,index){const key=`wind_gusts_10m_${model}`,gust=packet?.hourly?.[key]?.[index],speed=modelValue(packet,'wind_speed_10m',model,index);return packet?.hourly_units?.[key]==='kn'&&typeof gust==='number'&&Number.isFinite(gust)&&speed!==null&&gust<speed;}
function flagsFor(wind,wave,wi,wa,values){
 const flags=[];if(values.some(value=>value===null))flags.push('incomplete model coverage or unsupported units');
 if(['ecmwf_ifs025','gfs_global'].some(model=>gustContradiction(wind,model,wi)))flags.push('gust below sustained wind; gust withheld');
 if(values[0]!==null&&values[1]!==null&&Math.abs(values[0]-values[1])>4)flags.push('wind models differ >4 kt');
 if(values[4]!==null&&values[5]!==null&&Math.abs(values[4]-values[5])>1)flags.push('wave models differ >1 ft');
 if(wi<0||wa<0)flags.push('exact source epoch missing, duplicated or unsupported');
 return flags;
}
function sample(wind,wave,epoch){
 const wi=epochIndex(wind,epoch),wa=epochIndex(wave,epoch);
 const windValues=['ecmwf_ifs025','gfs_global'].map(model=>modelValue(wind,'wind_speed_10m',model,wi));
 const gust=['ecmwf_ifs025','gfs_global'].map(model=>modelValue(wind,'wind_gusts_10m',model,wi));
 const waves=['ecmwf_wam','ncep_gfswave016'].map(model=>modelValue(wave,'wave_height',model,wa));
 return {epoch,windEpoch:wi>=0?epoch:null,waveEpoch:wa>=0?epoch:null,wind:windValues,gust,waves,windDirection:direction(modelValue(wind,'wind_direction_10m','gfs_global',wi)),swell:modelValue(wave,'swell_wave_height','ncep_gfswave016',wa),period:modelValue(wave,'swell_wave_period','ncep_gfswave016',wa),swellDirection:direction(modelValue(wave,'swell_wave_direction','ncep_gfswave016',wa)),secondary:modelValue(wave,'secondary_swell_wave_height','ncep_gfswave016',wa),secondPeriod:modelValue(wave,'secondary_swell_wave_period','ncep_gfswave016',wa),secondaryDirection:direction(modelValue(wave,'secondary_swell_wave_direction','ncep_gfswave016',wa)),chop:modelValue(wave,'wind_wave_height','ncep_gfswave016',wa),flags:flagsFor(wind,wave,wi,wa,[...windValues,...gust,...waves])};
}
function selectedEpoch(at){const ms=at instanceof Date?at.getTime():typeof at==='number'?at*1000:typeof at==='string'&&/^\d{4}-\d{2}-\d{2}T\d{2}:00(?::00(?:\.000)?)?Z$/.test(at)?Date.parse(at):NaN;return Number.isFinite(ms)&&Number.isFinite(new Date(ms).getTime())&&ms>0&&ms%(HOUR*1000)===0&&(typeof at!=='string'||new Date(ms).toISOString().slice(0,16)===at.slice(0,16))?ms/1000:null;}
/** Exact UTC sample only; missing/duplicate epochs and wrong units are gaps. */
export function selectedHour(wind,wave,at){const epoch=selectedEpoch(at);return epoch===null?null:sample(wind,wave,epoch);}
export function gridDistanceNm(from,to){
 if(![from?.latitude,from?.longitude,to?.latitude,to?.longitude].every(Number.isFinite)||Math.abs(from.latitude)>90||Math.abs(to.latitude)>90||Math.abs(from.longitude)>180||Math.abs(to.longitude)>180)return Infinity;
 const rad=Math.PI/180,dLat=(to.latitude-from.latitude)*rad,dLon=(to.longitude-from.longitude)*rad;
 const a=Math.sin(dLat/2)**2+Math.cos(from.latitude*rad)*Math.cos(to.latitude*rad)*Math.sin(dLon/2)**2;
 return 3440.065*2*Math.asin(Math.min(1,Math.sqrt(a)));
}
export function modelURLs(latitude,longitude){
 if(!Number.isFinite(latitude)||!Number.isFinite(longitude)||latitude<32.4||latitude>42.1||longitude< -126||longitude> -116.7)throw Error('Outside California model coverage');
 const common={latitude:latitude.toFixed(2),longitude:longitude.toFixed(2),forecast_days:'8',timezone:'UTC',timeformat:'unixtime',cell_selection:'sea'};
 const wind=new URLSearchParams({...common,models:'ecmwf_ifs025,gfs_global',wind_speed_unit:'kn',hourly:'wind_speed_10m,wind_gusts_10m,wind_direction_10m,visibility,precipitation'});
 const wave=new URLSearchParams({...common,models:'ecmwf_wam,ncep_gfswave016',length_unit:'imperial',hourly:'wave_height,swell_wave_height,swell_wave_period,swell_wave_direction,secondary_swell_wave_height,secondary_swell_wave_period,secondary_swell_wave_direction,wind_wave_height,wind_wave_period,wind_wave_direction'});
 return {wind:`/api/om/v1/forecast?${wind}`,wave:`/api/om/v1/marine?${wave}`};
}
function morningIndex(packet){const index=new Map();for(const epoch of packet.hourly.time){const p=parts(epoch),key=dateOf(p)+'/'+p.hour;const values=index.get(key)??[];values.push(epoch);index.set(key,values);}return index;}
function morningMax(packet,field,model,date,clock){
 if(!validClock(packet))return null;
 const values=[];
 for(let hour=7;hour<=13;hour++){
  const epochs=clock.get(date+'/'+String(hour).padStart(2,'0'))??[];
  if(epochs.length!==1)return null;
  const value=modelValue(packet,field,model,epochIndex(packet,epochs[0]));if(value===null)return null;values.push(value);
 }
 return Math.max(...values);
}
export function morningRows(wind,wave,now=new Date()){
 if(!validClock(wind)||!validClock(wave)||!Number.isFinite(now.getTime()))return [];
 const today=dateOf(parts(now.getTime()/1000)),dates=new Map(),windClock=morningIndex(wind),waveClock=morningIndex(wave);
 for(const [key,epochs] of waveClock){const [date,hour]=key.split('/');if(hour==='10'&&date>today&&!dates.has(date))dates.set(date,epochs[0]);}
 return [...dates].sort(([a],[b])=>a.localeCompare(b)).slice(0,7).map(([date,epoch])=>{
  const row=sample(wind,wave,epoch);row.date=date;row.time=epoch;
  row.wind=['ecmwf_ifs025','gfs_global'].map(model=>morningMax(wind,'wind_speed_10m',model,date,windClock));row.gust=['ecmwf_ifs025','gfs_global'].map(model=>morningMax(wind,'wind_gusts_10m',model,date,windClock));row.waves=['ecmwf_wam','ncep_gfswave016'].map(model=>morningMax(wave,'wave_height',model,date,waveClock));
  row.flags=flagsFor(wind,wave,epochIndex(wind,epoch),epochIndex(wave,epoch),[...row.wind,...row.gust,...row.waves]);
  if(wind.hourly.time.some(t=>dateOf(parts(t))===date&&Number(parts(t).hour)>=7&&Number(parts(t).hour)<=13&&['ecmwf_ifs025','gfs_global'].some(model=>gustContradiction(wind,model,epochIndex(wind,t)))))row.flags.push('gust below sustained wind; gust withheld');
  row.flags=[...new Set(row.flags)];return row;
 });
}
const instances=new WeakMap();
const timeLabel=epoch=>new Date(epoch*1000).toLocaleString('en-US',{timeZone:zone,timeZoneName:'short',month:'short',day:'numeric',hour:'numeric',minute:'2-digit'});
function rowHTML(row,title){return `<article class="coastal-forecast-card"><h2>${esc(title)}</h2><p><strong>Wind</strong> ${one(row.wind[0])} / ${one(row.wind[1])} kt<br><small>IFS / GFS · gust ${one(row.gust[0])} / ${one(row.gust[1])} kt · GFS ${row.windDirection}</small></p><p><strong>Seas</strong> ${one(row.waves[0])} / ${one(row.waves[1])} ft<br><small>WAM / GFS Wave</small></p><p><strong>Primary swell</strong> ${one(row.swell)} ft @ ${one(row.period)} s ${row.swellDirection}<br><strong>Secondary</strong> ${one(row.secondary)} ft @ ${one(row.secondPeriod)} s ${row.secondaryDirection}<br><strong>Wind waves</strong> ${one(row.chop)} ft <small>(GFS Wave)</small></p>${row.flags.length?`<p class="model-flags">${esc(row.flags.join('; '))}</p>`:''}</article>`;}
function render(root,state){
 const {point,sector,options,record}=state,{wind,wave,urls}=record;
 const windDistance=gridDistanceNm(point,wind),waveDistance=gridDistanceNm(point,wave),near=windDistance<=30&&waveDistance<=30;
 const now=options.now??new Date(),at=Object.hasOwn(options,'at')?options.at:Math.floor(now.getTime()/(HOUR*1000))*HOUR,selected=near?selectedHour(wind,wave,at):null,rows=near?morningRows(wind,wave,now):[];
 const caveat=options.profile==='spear'?'In-water visibility, entry, exit and dive currents remain unverified.':options.profile==='shore'?'Exact beach breakers, access and water quality remain unverified.':'Harbor entrance, complete route and return conditions require separate checks.';
 root.innerHTML=`<h1>Weather & ocean · ${esc(sector?.name||'current map area')}</h1><p class="small">Requested ${point.latitude.toFixed(2)}°, ${point.longitude.toFixed(2)}° · wind grid ${esc(wind.latitude)}, ${esc(wind.longitude)} (${one(windDistance)} nm away) · wave grid ${esc(wave.latitude)}, ${esc(wave.longitude)} (${one(waveDistance)} nm away). Model output accessed ${esc(new Date(record.accessedAt).toLocaleString('en-US',{timeZone:zone}))} Pacific; model run issue times are not provided by this response.</p><p>${esc(options.profile??'boat')} · target ${esc(options.target??'unspecified')}. ${esc(caveat)} No target-specific fishing score or safe-trip clearance is inferred.</p><h2>Selected UTC hour</h2>${selected?`<p><time datetime="${esc(new Date(selected.epoch*1000).toISOString())}">${esc(timeLabel(selected.epoch))}</time> · ${esc(new Date(selected.epoch*1000).toISOString())}. Requested UTC selection; exact hourly source match required. ${selected.windEpoch!==null?'Wind source valid time matches.':'No exact wind source valid time.'} ${selected.waveEpoch!==null?'Wave source valid time matches.':'No exact wave source valid time.'}</p>${rowHTML(selected,'Selected-hour independent models')}`:`<p>Selected hour unavailable${!near?': the nearest sea grid is more than 30 nm from the map center':': unsupported UTC selection'}. The selection is not replaced with now or a nearby sample.</p>`}<h2>Seven-day morning model outlook</h2><p>Wind, gust and combined seas are maxima of every hour from 7 a.m.–1 p.m. Pacific; swell components and direction are original 10 a.m. snapshots. A dash means missing coverage, never calm. Models have their own source horizons.</p>${rows.length?`<div class="coastal-forecast-grid">${rows.map(row=>rowHTML(row,timeLabel(row.epoch)+' · morning maxima')).join('')}</div>`:`<p>${near?'Model coverage for this location is unavailable':'The nearest sea grid is more than 30 nm from the map center'}. Conditions are unknown here, not calm.</p>`}<p class="small">SkipperCast builds these forecasts from <a href="${esc(urls.wind)}" target="_blank" rel="noopener">ECMWF IFS and NOAA GFS wind data ↗</a> and <a href="${esc(urls.wave)}" target="_blank" rel="noopener">ECMWF WAM and NOAA GFS Wave data ↗</a> (NOAA and ECMWF open data, CC BY 4.0). The model pairs are distinct underlying models. Wave components are displayed from GFS Wave only because WAM does not populate them here. Recheck <a href="https://www.weather.gov/marine/" target="_blank" rel="noopener">NWS marine forecasts and advisories ↗</a> and entrance conditions before departure.</p>`;
}
function validPacketShape(packet){return packet!==null&&typeof packet==='object'&&!Array.isArray(packet)&&Number.isFinite(packet.latitude)&&Math.abs(packet.latitude)<=90&&Number.isFinite(packet.longitude)&&Math.abs(packet.longitude)<=180&&packet.hourly!==null&&typeof packet.hourly==='object'&&!Array.isArray(packet.hourly)&&Array.isArray(packet.hourly.time)&&packet.hourly_units!==null&&typeof packet.hourly_units==='object'&&!Array.isArray(packet.hourly_units);}
async function getJSON(url,signal,fetchImpl){const response=await fetchImpl(url,{signal});if(!response.ok)throw Error(`model service HTTP ${response.status}`);const data=await response.json();if(data?.error)throw Error(data.reason||'model service error');return data;}
/** at accepts a whole-hour Date, UTC ISO string or epoch seconds. Hour/profile/
 * target changes reuse this root's current snapshot/inflight request. */
export async function updateCoastalForecast(root,point,sector,options={}){
 let state=instances.get(root);if(!state){state={generation:0,cache:new Map(),pending:null,controller:null,disposed:false};instances.set(root,state);}if(state.disposed)return false;
 state.point={...point};state.sector=sector;state.options={...options,now:options.now instanceof Date?new Date(options.now):options.now,at:options.at instanceof Date?new Date(options.at):options.at};if(!Object.hasOwn(options,'at'))delete state.options.at;
 let key,urls;try{urls=modelURLs(point.latitude,point.longitude);key=urls.wind+'|'+urls.wave;}catch(error){root.innerHTML=`<h1>Weather & ocean</h1><p>${esc(error.message)}. Conditions are unavailable.</p>`;state.generation++;state.controller?.abort();state.pending=null;state.controller=null;state.record=null;state.key=null;return false;}
 let record=state.cache.get(key);
 if(record&&Date.now()-record.accessedAt<=1800000){if(state.pending?.key!==key){state.generation++;state.controller?.abort();state.pending=null;state.controller=null;}state.key=key;state.record=record;render(root,state);return true;}
 if(state.pending?.key===key){await state.pending.promise;return !state.disposed&&state.key===key&&!!state.record;}
 const id=++state.generation;state.key=key;state.record=null;state.controller?.abort();const controller=new AbortController();state.controller=controller;
 root.innerHTML=`<h1>Weather & ocean · ${esc(sector?.name||'current map area')}</h1><p>Loading two wind and two wave models at the nearest sea grid…</p>`;
 const promise=(async()=>{const timer=setTimeout(()=>controller.abort(),16000);try{
  const [wind,wave]=await Promise.all([getJSON(urls.wind,controller.signal,options.fetchImpl??fetch),getJSON(urls.wave,controller.signal,options.fetchImpl??fetch)]);if(!validPacketShape(wind)||!validPacketShape(wave))throw Error('Malformed model packet; source grid or hourly structure unavailable');record={wind,wave,urls,accessedAt:Date.now()};if(state.disposed||id!==state.generation)return false;
  state.cache.set(key,record);if(state.cache.size>12)state.cache.delete(state.cache.keys().next().value);state.record=record;render(root,state);return true;
 }catch(error){if(state.disposed||id!==state.generation)return false;root.innerHTML=`<h1>Weather & ocean · ${esc(state.sector?.name||'current map area')}</h1><p>Local model feed unavailable: ${esc(error.message)}. Conditions are unknown, not calm.</p><p><a href="https://www.weather.gov/marine/" target="_blank" rel="noopener">NWS marine forecasts ↗</a></p>`;return false;}finally{clearTimeout(timer);if(id===state.generation){state.pending=null;state.controller=null;}}})();
 state.pending={key,promise};return promise;
}
/** Cancel publication immediately when the host selection changes or hides.
 * Keep admitted snapshots for a later explicit update; do not fetch or render. */
export function suspendCoastalForecast(root){const state=instances.get(root);if(!state||state.disposed)return;state.generation++;state.controller?.abort();state.pending=null;state.controller=null;state.record=null;state.key=null;}
export function disposeCoastalForecast(root){const state=instances.get(root);if(!state)return;state.disposed=true;state.generation++;state.controller?.abort();state.pending=null;state.cache.clear();state.record=null;}
