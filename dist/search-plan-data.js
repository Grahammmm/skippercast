import {distanceNm,POINTS} from './marine-data.js';
import {rateHour} from './morning-outlook.js';
import {pointBundle} from './region.js';
export function nearestSearchForecast(area,profile,points=POINTS){
 const rows=points.map((p,i)=>({p,i,d:distanceNm(area,p)})).filter(x=>profile.kind!=='offshore'||x.p.offshore);
 rows.sort((a,b)=>a.d-b.d);return rows[0]?.d<=12?rows[0]:null;
}
export function searchWindow(bundle,point,species,time,now=Date.now()){
 if(!bundle)return {conditions:null,confidence:'Low',reasons:['Forecast not loaded']};
 const rows=Array.from({length:5},(_,i)=>rateHour(pointBundle(bundle,point),point,species,time+i*3600,now));
 const reasons=[...new Set(rows.flatMap(r=>r.reasons))];
 return {conditions:rows.every(r=>Number.isFinite(r.conditions))?Math.min(...rows.map(r=>r.conditions)):null,confidence:rows.some(r=>r.confidence==='Low')?'Low':'Moderate',reasons};
}
// Three adjacent, populated native cells form one rectangular search strip.
// Never span a masked cell, join across latitude rows, or move an observed front.
export function oceanSearchAreas(frame,profile,region,limit=30){
 if(!frame||frame.regionId!==region.id||!['wcofs-surface-forecast','sst-analysis'].includes(frame.layerId)||!Number.isFinite(frame.time))return [];
 const [dy,dx]=frame.step||[],ti=frame.fields.indexOf('temperature_c');if(ti<0||![dy,dx].every(n=>Number.isFinite(n)&&n>0&&n<=.25))return [];
 if(Number.isFinite(frame.selectedTime)&&(frame.layerId==='wcofs-surface-forecast'?Math.abs(frame.selectedTime-frame.time)>5400:frame.time>frame.selectedTime||frame.selectedTime-frame.time>48*3600))return [];
 const ui=frame.fields.indexOf('u_mps'),vi=frame.fields.indexOf('v_mps'),ei=frame.fields.indexOf('analysis_error_c');
 const groups=new Map();for(const row of frame.rows){if(!Number.isFinite(row[ti]))continue;const key=row[0].toFixed(6);if(!groups.has(key))groups.set(key,[]);groups.get(key).push(row);}
 const areas=[];
 for(const rows of groups.values()){
  rows.sort((a,b)=>a[1]-b[1]);
  for(let i=0;i+2<rows.length;i+=3){const a=rows.slice(i,i+3);if(a.slice(1).some((r,j)=>Math.abs(r[1]-a[j][1]-dx)>dx*.05))continue;
   const temps=a.map(r=>r[ti]);const west=a[0][1]-dx/2,east=a[2][1]+dx/2,south=a[0][0]-dy/2,north=a[0][0]+dy/2,b=region.bounds||region.fishing_bounds;
   if(west<b[0]||east>b[2]||south<b[1]||north>b[3])continue;
   const band=profile.thermal_range_c,within=!band||temps.every(t=>t>=band[0]&&t<=band[1]);
   // Thermal envelope adds context only; outside is not proof of absence.
   const gradient=(Math.max(...temps)-Math.min(...temps))/(dx*2*111*Math.cos(a[0][0]*Math.PI/180));
   // Display thresholds are explicit heuristics, not fitted catch probabilities.
   if(gradient<.02)continue;
   const contrast=Math.max(...temps)-Math.min(...temps);
   const errors=a.map(r=>r[ei]);
   const supported=frame.layerId==='sst-analysis'&&errors.every(e=>Number.isFinite(e)&&e>=0)&&contrast>Math.max(...errors)*2;
   if(frame.layerId==='sst-analysis'&&!supported)continue;
   const vectors=a.map(r=>[r[ui],r[vi]]),flowKnown=vectors.every(v=>v.every(Number.isFinite));
   const flowChange=flowKnown?Math.hypot(vectors[2][0]-vectors[0][0],vectors[2][1]-vectors[0][1]):null;
   const priority=band&&!within?3:gradient>=.05&&(supported||flowChange>=.1)?1:2;
   const reasons=[`Temperature changes ${contrast.toFixed(1)}°C across ${(dx*2*111*Math.cos(a[0][0]*Math.PI/180)).toFixed(1)} km`];
   if(band)reasons.push(within?'Within the broad albacore reference envelope; not an optimum':'Outside the broad albacore reference envelope; lower search priority');
   else reasons.push('No fixed temperature optimum applied; confirm species, bait and depth on the sounder');
   if(supported)reasons.push('Temperature contrast exceeds twice the largest reported analysis error');
   if(flowKnown)reasons.push(`Modeled surface-flow change ${(flowChange*1.94384).toFixed(2)} kt across the strip; not proven convergence or bait`);
   const latitude=a[0][0],longitude=a[1][1];
   areas.push({type:'Feature',geometry:{type:'Polygon',coordinates:[[[west,south],[east,south],[east,north],[west,north],[west,south]]]},properties:{id:`water-${latitude}-${a[0][1]}`,name:`Water transition ${latitude.toFixed(2)}°N ${Math.abs(longitude).toFixed(2)}°W`,latitude,longitude,bounds:[west,south,east,north],species:[],habitat_kind:'ocean',search_priority:priority,evidence_confidence:'Low',search_reasons:reasons,search_method:'ocean-transition-v2',surface_flow_change_mps:flowChange,temperature_c:[Math.min(...temps),Math.max(...temps)],gradient,thermal_reference:band?(within?'within':'outside'):null,frame_time:frame.time,source_url:frame.sourceURL,source_date:frame.issuedAt,depth_qualified:false,exportable:false}});
  }
 }
 return areas.sort((a,b)=>a.properties.search_priority-b.properties.search_priority||b.properties.gradient-a.properties.gradient).slice(0,limit);
}
