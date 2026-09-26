import {distanceNm,POINTS} from './marine-data.js?v=8.13';
import {rateHour} from './morning-outlook.js?v=8.13';
import {pointBundle} from './region.js?v=8.13';
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
 if(!frame||frame.regionId!==region.id||frame.layerId!=='wcofs-surface-forecast'||!Number.isFinite(frame.time))return [];
 const [dy,dx]=frame.step,ti=frame.fields.indexOf('temperature_c');if(ti<0)return [];
 const groups=new Map();for(const row of frame.rows){if(!Number.isFinite(row[ti]))continue;const key=row[0].toFixed(6);if(!groups.has(key))groups.set(key,[]);groups.get(key).push(row);}
 const areas=[];
 for(const rows of groups.values()){
  rows.sort((a,b)=>a[1]-b[1]);
  for(let i=0;i+2<rows.length;i+=3){const a=rows.slice(i,i+3);if(a.slice(1).some((r,j)=>Math.abs(r[1]-a[j][1]-dx)>dx*.05))continue;
   const temps=a.map(r=>r[ti]);const west=a[0][1]-dx/2,east=a[2][1]+dx/2,south=a[0][0]-dy/2,north=a[0][0]+dy/2,b=region.fishing_bounds;
   if(west<b[0]||east>b[2]||south<b[1]||north>b[3])continue;
   const band=profile.thermal_range_c,within=!band||temps.every(t=>t>=band[0]&&t<=band[1]);
   // Thermal envelope adds context only; outside is not proof of absence.
   const gradient=(Math.max(...temps)-Math.min(...temps))/(dx*2*111*Math.cos(a[0][0]*Math.PI/180));
   areas.push({type:'Feature',geometry:{type:'Polygon',coordinates:[[[west,south],[east,south],[east,north],[west,north],[west,south]]]},properties:{id:`water-${a[0][0]}-${a[0][1]}`,name:'Modeled water transition',latitude:a[0][0],longitude:a[1][1],bounds:[west,south,east,north],species:[],habitat_kind:'ocean',temperature_c:[Math.min(...temps),Math.max(...temps)],gradient,thermal_reference:band?(within?'within':'outside'):null,frame_time:frame.time,source_url:frame.sourceURL,source_date:frame.issuedAt,depth_qualified:false,exportable:false}});
  }
 }
 return areas.sort((a,b)=>b.properties.gradient-a.properties.gradient).slice(0,limit);
}
