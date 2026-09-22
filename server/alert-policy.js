// Pure, region-independent alert assessment. Threshold fit is not trip clearance.
export const finite=n=>typeof n==='number'&&Number.isFinite(n);
export function dateInZone(epoch,zone){return new Intl.DateTimeFormat('en-CA',{timeZone:zone,year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(epoch));}
export function samplePoint(data,key,time,unit){
  const h=data?.hourly, i=h?.time?.indexOf(time);
  if(data?.hourly_units?.[key]!==unit||data?.hourly_units?.time!=='unixtime'||i<0||!finite(h?.[key]?.[i]))return null;
  return h[key][i];
}
export function assessTrip(trip,region,intelligence,rules,advisories,now=Date.now()){
  const point=region.forecast_points.findIndex(p=>p.id===trip.point);
  const issues=[],values={wind:null,gust:null,sea:null,chop:null};
  if(point<0||intelligence?.region_id!==region.id)return {status:'unverified',legal:'unverified',issues:['Regional forecast unavailable'],values,checked_at:new Date(now).toISOString(),runs:{}};
  if(!finite(Date.parse(intelligence.completed_at))||now-Date.parse(intelligence.completed_at)>3*3600000||Date.parse(intelligence.completed_at)>now+3600000)issues.push('Forecast feed time is missing, stale or invalid');
  const models=intelligence.forecast?.models||{};
  const base=models.gfs_global?.data?.[point];
  const hour=t=>Number(new Intl.DateTimeFormat('en-US',{timeZone:region.timezone,hour:'2-digit',hourCycle:'h23'}).format(new Date(t*1000)));
  const times=(base?.hourly?.time||[]).filter(t=>dateInZone(t*1000,region.timezone)===trip.date&&hour(t)>=trip.start_hour&&hour(t)<=trip.end_hour);
  if(times.length!==trip.end_hour-trip.start_hour+1)issues.push('The complete saved window is not populated');
  const max=(key,value)=>{if(finite(value))values[key]=values[key]===null?value:Math.max(values[key],value);else issues.push('Required '+key+' sample missing');};
  for(const model of ['gfs_global','ecmwf_ifs025','ncep_gfswave025','ecmwf_wam025']){
    const m=models[model],source=intelligence.sources?.['model-'+model];
    if(source?.status!=='ok'||m?.error||!finite(m?.meta?.last_run_initialisation_time)||now/1000-m.meta.last_run_initialisation_time>36*3600||m.meta.last_run_initialisation_time>now/1000+3600)issues.push(model+' is unavailable or stale');
    for(const t of times){
      const d=m?.data?.[point];
      if(!finite(m?.meta?.data_end_time)||t>m.meta.data_end_time)issues.push(model+' published horizon does not cover the full window');
      if(model==='gfs_global'||model==='ecmwf_ifs025'){
        const w=samplePoint(d,'wind_speed_10m',t,'kn'),g=samplePoint(d,'wind_gusts_10m',t,'kn');max('wind',w);max('gust',g);
        if(finite(g)&&finite(w)&&g<w)issues.push('Inconsistent gust sample');
        const visibility=samplePoint(d,'visibility',t,'m'),code=samplePoint(d,'weather_code',t,'wmo code');
        if(visibility===null||code===null)issues.push('Visibility or weather hazard check missing');
        if(visibility!==null&&visibility<1609.344||code!==null&&code>=95)issues.push('Fog or thunderstorm signal');
      }else{const period=samplePoint(d,'wave_period',t,'s');if(period===null||period<=0)issues.push('Combined wave period unavailable or invalid');max('sea',samplePoint(d,'wave_height',t,'ft'));if(model==='ncep_gfswave025')max('chop',samplePoint(d,'wind_wave_height',t,'ft'));}
    }
  }
  const species=trip.species==='reef'?['lingcod','rockfish']:[trip.species];
  let legal='reviewed season';
  for(const id of species){
    const p=rules?.species?.[id];
    if(!p||trip.date<rules.valid_from||trip.date>rules.valid_through){issues.push('Trip-date rules unavailable');legal='unverified';continue;}
    const window=p.windows.find(w=>trip.date>=w.start&&trip.date<=w.end);
    if(!window){legal='closed';issues.push('Outside the reviewed species season');}
    else if(window.restriction){legal='restricted';issues.push(window.restriction);}
    else if(window.requires_opening_review){legal='unverified';issues.push('Scheduled opening needs review');}
    if(p.source_ids.some(s=>{const c=rules.checks?.[s];return c?.status!=='unchanged'||c.source_status!=='ok'||c.content_sha256!==rules.sources?.[s]?.approved_content_sha256||!finite(Date.parse(c.data_retrieved_at))||now-Date.parse(c.data_retrieved_at)>36*3600000;})){
      legal='unverified';issues.push('Rules changed or need a fresh source check');
    }
  }
  if(!Array.isArray(advisories))issues.push('Marine advisories unavailable');
  else if(advisories.some(a=>!times.length||(!a.onset||Date.parse(a.onset)<=times.at(-1)*1000)&&(!a.ends&&!a.expires||Date.parse(a.ends||a.expires)>=times[0]*1000)))issues.push('Applicable marine advisory');
  const within=finite(values.wind)&&finite(values.gust)&&finite(values.sea)&&values.wind<=trip.wind_limit&&values.gust<=trip.gust_limit&&values.sea<=trip.sea_limit&&values.chop<=1;
  const status=issues.length?'unverified':within?'within limits':'above limits';
  return {status,legal,values,issues:[...new Set(issues)],checked_at:new Date(now).toISOString(),
    runs:Object.fromEntries(Object.entries(models).map(([id,m])=>[id,m.meta?.last_run_initialisation_time??null]))};
}

export function alertDecision(previous,current,{final=false,missed=false}={}){
  if(missed)return 'missed-final';
  if(final)return 'final';
  if(!previous)return 'initial';
  if(previous.status==='within limits'&&current.status!=='within limits')return 'retraction';
  if(previous.status!==current.status||JSON.stringify(previous.issues)!==JSON.stringify(current.issues))return 'update';
  const limits={wind:2,gust:3,sea:.5,chop:.5};
  return Object.keys(limits).some(k=>finite(previous.values?.[k])!==finite(current.values[k])||finite(current.values[k])&&Math.abs(current.values[k]-previous.values[k])>=limits[k])?'update':null;
}

export function alertMessage(trip,region,assessment,kind){
  const value=(v,u)=>finite(v)?v.toFixed(1)+' '+u:'unavailable';
  const name=region.forecast_points.find(p=>p.id===trip.point)?.name||trip.point;
  return `${kind==='retraction'?'No longer within saved limits':kind==='final'?'Day-before assessment':kind==='missed-final'?'Missed day-before assessment':kind==='initial'?'Saved-trip assessment':'Trip update'} · ${trip.date} · ${name}\n${assessment.status}. Window ${trip.start_hour}:00–${trip.end_hour}:00 ${region.timezone}.\nWind ${value(assessment.values.wind,'kt')}; gust ${value(assessment.values.gust,'kt')}; seas ${value(assessment.values.sea,'ft')}; chop ${value(assessment.values.chop,'ft')}.\n${assessment.issues.join('; ')||'Within your numerical preferences; this does not evaluate route, entrance or catch success.'}\nRules: ${assessment.legal}. Recheck current marine, species and entrance conditions before departure.\nChecked ${assessment.checked_at}. NOAA/ECMWF run times: ${Object.entries(assessment.runs||{}).map(([k,v])=>k+' '+(v?new Date(v*1000).toISOString():'unavailable')).join('; ')}\nhttps://forecast.weather.gov/MapClick.php?TextType=2&zoneid=${(region.contexts?.[region.forecast_points.find(p=>p.id===trip.point)?.context]?.marine_zones||region.marine_zones)[region.forecast_points.find(p=>p.id===trip.point)?.offshore?'offshore':'coastal']}\n${region.harbor.information_url}`;
}
