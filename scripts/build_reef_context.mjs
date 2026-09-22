// Repeatable historical-context import. Never promotes approximate records to targets.
import fs from 'node:fs';
import path from 'node:path';
import {geometryIntersects} from '../dist/geo-screen.js';
export function buildContext(records, region, exclusions) {
  const features=[], withheld=[];
  const dms=a=>a[0]+a[1]/60+a[2]/3600;
  for(const r of records.records) {
    if(r.withheld_reason){withheld.push({id:r.id,reason:r.withheld_reason});continue;}
    const points=r.positions.map(p=>[-dms(p.longitude_west_dms),dms(p.latitude_dms)]);
    if(!points.length||points.some(p=>!p.every(Number.isFinite)))throw Error('Invalid historical coordinates');
    const latitude=points.reduce((s,p)=>s+p[1],0)/points.length;
    const dy=records.envelope_padding_m/111320, dx=dy/Math.cos(latitude*Math.PI/180);
    const b=[Math.min(...points.map(p=>p[0]))-dx,Math.min(...points.map(p=>p[1]))-dy,Math.max(...points.map(p=>p[0]))+dx,Math.max(...points.map(p=>p[1]))+dy];
    const geometry={type:'Polygon',coordinates:[[[b[0],b[1]],[b[2],b[1]],[b[2],b[3]],[b[0],b[3]],[b[0],b[1]]]]};
    const limit=region.fishing_bounds;
    const excluded=exclusions.features.filter(f=>geometryIntersects(geometry,f.geometry));
    if(b[0]<limit[0]||b[1]<limit[1]||b[2]>limit[2]||b[3]>limit[3]||excluded.length){withheld.push({id:r.id,reason:excluded.length?'Envelope touches a closure':'Envelope outside region',closures:excluded.map(f=>f.properties.NAME)});continue;}
    features.push({type:'Feature',geometry,properties:{id:r.id,name:r.name,latitude:(b[1]+b[3])/2,longitude:(b[0]+b[2])/2,species:['reef'],evidence_class:'historical-context',exportable:false,rank:null,depth_verified:false,reported_depth_ft:r.reported_depth_ft,material:r.historical_material,source_id:records.source_id,source_url:records.source_url,source_date:records.source_date}});
  }
  return {type:'FeatureCollection',region_id:region.id,source:{url:records.source_url,date:records.source_date,datum:records.horizontal_datum,derivation:`One envelope per reef complex with ${records.envelope_padding_m} m padding. Padding is a display/search convention, not a measured position error or habitat boundary.`},features,withheld};
}
if(process.argv[1]&&path.resolve(process.argv[1])===path.resolve(new URL(import.meta.url).pathname)) {
  const id=process.argv[2];if(!/^[a-z][a-z0-9-]+$/.test(id||''))throw Error('Provide a region ID');
  const read=p=>JSON.parse(fs.readFileSync(p,'utf8'));
  const region=read(`regions/${id}/region.json`), records=read(`regions/${id}/reef-records.json`);
  const exclusions={features:['protected_areas','closures'].flatMap(k=>region.assets[k]?read('dist/'+region.assets[k]).features:[])};
  const data=buildContext(records,region,exclusions);
  fs.writeFileSync('dist/'+region.assets.regional_context,JSON.stringify(data)+'\n');
  console.log(JSON.stringify({region:id,areas:data.features.length,withheld:data.withheld}));
}
