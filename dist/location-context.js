import { getRegion, getRegionDirectory, renderTargetOptions } from './region.js?v=8.12';
import { positions } from './geo-screen.js?v=8.12';
import {coastAt,coastURL} from './coasts.js?v=8.12';

// Discovery extents select a reviewed package. They are not legal boundaries.
export const contains = (b, p) => !!b && Number.isFinite(p?.longitude) && Number.isFinite(p?.latitude) && p.longitude >= b[0] && p.longitude <= b[2] && p.latitude >= b[1] && p.latitude <= b[3];
const size = b => (b[2]-b[0])*(b[3]-b[1]);
const overlaps = (a,b) => a[0]<=b[2] && a[2]>=b[0] && a[1]<=b[3] && a[3]>=b[1];
export function locationExtent(point) {
  const coords=positions(point?.geometry);
  if (!coords.length) return [point.longitude,point.latitude,point.longitude,point.latitude];
  return coords.reduce((b,p)=>[Math.min(b[0],p[0]),Math.min(b[1],p[1]),Math.max(b[2],p[0]),Math.max(b[3],p[1])],[Infinity,Infinity,-Infinity,-Infinity]);
}
export function resolveLocation(point, directory, activeId) {
  const matches=directory.filter(r=>contains(r.fishing_bounds,point)).sort((a,b)=>size(a.fishing_bounds)-size(b.fishing_bounds)||a.id.localeCompare(b.id));
  const discovery=directory.filter(r=>contains(r.discovery_bounds,point)).sort((a,b)=>(a.id===activeId?-1:b.id===activeId?1:size(a.discovery_bounds)-size(b.discovery_bounds)));
  const region=point.offshore && discovery[0]?.id===activeId ? discovery[0] : matches[0];
  if(!region && discovery.length)return {coverage:'discovery',regionId:discovery[0].id,name:discovery[0].name,point};
  if(!region)return {coverage:'outside',regionId:activeId,name:'Outside mapped regions',point};
  const b=locationExtent(point), extent=region.fishing_bounds;
  const whole=b[0]>=extent[0] && b[1]>=extent[1] && b[2]<=extent[2] && b[3]<=extent[3];
  const edge=[Math.abs(point.longitude-extent[0]),Math.abs(point.latitude-extent[1]),Math.abs(point.longitude-extent[2]),Math.abs(point.latitude-extent[3])].some(d=>d<0.00001);
  return {coverage:!whole?(point.offshore?'discovery':'mixed'):edge?'edge':'covered',regionId:region.id,name:region.name,point};
}
export function enrichLocation(base, region, protectedAreas) {
  if(base.coverage==='outside' || base.regionId!==region.id)return base;
  const areas=region.map?.local_areas || [];
  const extent=locationExtent(base.point);
  const nearby=areas.filter(a=>overlaps(a.bounds,extent));
  const focus=nearby.filter(a=>contains(a.bounds,base.point)).sort((a,b)=>size(a.bounds)-size(b.bounds)||a.id.localeCompare(b.id))[0];
  // For an area crossing contexts, show all regional targets, never over-filter.
  const insideFocus=focus && extent[0]>=focus.bounds[0] && extent[1]>=focus.bounds[1] && extent[2]<=focus.bounds[2] && extent[3]<=focus.bounds[3];
  return {...base,name:focus?.name||region.name,localId:focus?.id||null,
    noticeIds:[...new Set([...(region.map?.region_notice_ids||[]),...nearby.flatMap(a=>a.notice_ids||[])])],
    hiddenTargets:insideFocus?(focus.hidden_targets||[]):[],
    protection:protectedAreas?.inspect(base.point) || {status:'unavailable',names:[]}};
}
export function targetsForLocation(region, context) {
  if(!['covered','discovery'].includes(context.coverage) || context.regionId!==region.id)return [];
  const hidden=new Set((context.hiddenTargets||[]).map(t=>t.id));
  return region.target_options.filter(t=>!hidden.has(t.id) && (context.coverage!=='discovery'||t.kind==='offshore'));
}
export function viewFromURL(url) {
  const value=new URL(url).searchParams.get('view');
  if(!value || !/^-?\d+(?:\.\d+)?,-?\d+(?:\.\d+)?,\d+(?:\.\d+)?$/.test(value))return null;
  const [latitude,longitude,zoom]=value.split(',').map(Number);
  return Math.abs(latitude)<=85 && Math.abs(longitude)<=180 && zoom>=7 && zoom<=18 ? {latitude,longitude,zoom}:null;
}
export function locationURL(url,regionId,point,zoom,target) {
  const next=new URL(url);next.searchParams.set('region',regionId);
  next.searchParams.delete('coast');
  next.searchParams.set('view',`${point.latitude.toFixed(5)},${point.longitude.toFixed(5)},${zoom}`);
  if(target)next.searchParams.set('target',target);
  next.searchParams.delete('focus');next.searchParams.delete('spot');next.hash='map';return next;
}

export function initLocationContext(map,{select,protectedAreas,onLocation,onSpeciesChange}) {
  const region=getRegion(), directory=getRegionDirectory();
  let context=null, selected=null, selectionCenter=null, timer, navigating=false;
  let desired=new URL(location.href).searchParams.get('target') || select.value;
  const caption=document.getElementById('location-caption');
  const same=(a,b)=>a && b && Math.abs(a.latitude-b.latitude)<0.00001 && Math.abs(a.longitude-b.longitude)<0.00001;
  const center=()=>{const p=map.getCenter();return {latitude:p.lat,longitude:p.lng};};
  function update() {
    const point=selected||center();
    let next=resolveLocation(point,directory,region.id);
    next=enrichLocation(next,region,protectedAreas);
    next.source=selected?'Selected spot':'Map center';
    const coastal=coastAt(point);
    if(!selected && next.coverage==='outside' && coastal && !navigating) {
      navigating=true;caption.textContent=`Opening ${coastal.name} coastal guide…`;
      location.replace(coastURL(location.href,coastal,{point,zoom:map.getZoom(),target:desired,overview:true}));return;
    }
    if(next.regionId!==region.id && ['covered','discovery'].includes(next.coverage)) {
      if(navigating)return; navigating=true;
      next.coverage='loading';context=next;
      document.dispatchEvent(new CustomEvent('skippercast:location',{detail:next}));
      caption.textContent=`Loading ${next.name}…`;
      location.replace(locationURL(location.href,next.regionId,point,map.getZoom(),desired));return;
    }
    const choices=targetsForLocation(region,next), old=select.value;
    const chosen=choices.some(t=>t.id===desired)?desired:choices.some(t=>t.id===old)?old:choices[0]?.id;
    if(choices.length) {
      renderTargetOptions(select,choices,chosen);select.disabled=false;
      next.targetNote=chosen!==desired ? (region.map?.unavailable_targets?.[desired] || next.hiddenTargets?.find(t=>t.id===desired)?.reason || 'The previous target is not in this area’s target list.') : null;
      next.targetSource=next.targetNote?(region.map?.unavailable_target_sources?.[desired]||next.hiddenTargets?.find(t=>t.id===desired)?.source_url):null;
    } else {
      select.replaceChildren(new Option('Targets not mapped here',old));select.disabled=true;
    }
    context=next;
    document.body.dataset.locationCoverage=next.coverage;
    caption.textContent=`${next.source} · ${next.name}${next.coverage==='discovery'?' · search context':''}`;
    caption.title=`${point.latitude.toFixed(5)}, ${point.longitude.toFixed(5)} · ${next.targetNote||'Targets reflect regional habitat; they do not indicate an open season.'}`;
    document.dispatchEvent(new CustomEvent('skippercast:location',{detail:next}));
    if(chosen && chosen!==old)onSpeciesChange();
    if(['covered','discovery'].includes(next.coverage))onLocation(point);
  }
  function move() {
    if(selected && !same(center(),selectionCenter) && !same(center(),selected))selected=null;
    const url=new URL(location.href),p=center();url.searchParams.set('view',`${p.latitude.toFixed(5)},${p.longitude.toFixed(5)},${map.getZoom()}`);url.searchParams.delete('focus');history.replaceState(history.state,'',url);
    clearTimeout(timer);timer=setTimeout(update,250);
  }
  map.on('moveend',move);
  document.addEventListener('skippercast:boundaries',()=>{clearTimeout(timer);timer=setTimeout(update,50);});
  select.addEventListener('change',event=>{if(!event.detail?.location){desired=select.value;selected=null;const url=new URL(location.href);url.searchParams.set('target',desired);history.replaceState(history.state,'',url);update();}});
  const result={
    get:()=>context,
    resolve(value){return value?{...value,...enrichLocation(resolveLocation(value.point,directory,region.id),region,protectedAreas)}:value;},
    select(point){if(!Number.isFinite(point?.latitude)||!Number.isFinite(point?.longitude))return;selected=point;selectionCenter=center();clearTimeout(timer);update();},
    clear(){selected=null;clearTimeout(timer);update();},
    refresh:update,
  };
  update();return result;
}
