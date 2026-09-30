// Canonical day-plan geometry and numbered priorities; never a navigation route.
import {esc} from './marine-charts.js';
import {fitLabel} from './spot-ranking.js';
import {manifestState,loadManifest} from './seafloor-data.js';
export function initTripRanking(map,screen,onSelect) {
  const layer=L.layerGroup(), renderer=L.canvas({padding:.3});
  let plan={targets:[],areas:[]};const rejected=new Map();
  function draw(){
    layer.clearLayers();
    if(!screen.ready()){layer.remove();return;}
    if(!plan.targets.length){layer.remove();return;}
    const hash=plan.publication?.export_sha256,heldAt=rejected.get(hash);
    if(heldAt&&!(Date.parse(plan.publication.verified_at)>heldAt)){layer.remove();return;}
    if(heldAt)rejected.delete(hash);
    if(plan.invalid||manifestState(plan.publication,plan.publication?.region).state!=='ready'){layer.remove();return;}
    layer.addTo(map);
    for(const a of plan.areas){
      if(!screen.geometryAllowed(a.geometry))continue;
      L.geoJSON(a.geometry,{renderer,style:{color:'#075f63',weight:2,fillOpacity:.12}}).addTo(layer);
    }
    const groups=[];
    for(const t of [...plan.targets].sort((a,b)=>a.trip_rank-b.trip_rank)){
      if(!t.trip_rank||!screen.pointAllowed(t)||!t.area_ids?.every(id=>plan.areas.some(a=>a.id===id&&screen.geometryAllowed(a.geometry))))continue;
      const point=map.latLngToLayerPoint([t.latitude,t.longitude]),near=groups.find(g=>g.point.distanceTo(point)<44);
      if(near)near.targets.push(t);else groups.push({point,targets:[t]});
    }
    for(const group of groups){
      const t=group.targets[0],cluster=group.targets.length>1;
      L.marker([t.latitude,t.longitude],{icon:L.divIcon({className:'trip-rank-pin'+(cluster?' trip-rank-cluster':''),
        html:`<span>${t.trip_rank}</span>${cluster?`<small>+${group.targets.length-1}</small>`:''}`,iconSize:[44,44],iconAnchor:[22,22]}),title:t.name,zIndexOffset:1000-t.trip_rank})
        .bindTooltip(esc(`${t.name} · ${fitLabel(t.trip_fit)}${cluster?' · '+(group.targets.length-1)+' nearby spots; tap to zoom':''}`))
        .on('click',()=>cluster?map.fitBounds(group.targets.map(s=>[s.latitude,s.longitude]),{padding:[65,120],maxZoom:18}):onSelect(t)).addTo(layer);
    }
  }
  document.addEventListener('skippercast:trip-ranked',event=>{plan=event.detail;draw();
    if(plan.fit&&plan.targets.length)requestAnimationFrame(()=>{
      map.invalidateSize();map.fitBounds(plan.targets.map(t=>[t.latitude,t.longitude]),{padding:[60,80],maxZoom:13});
    });});
  document.addEventListener('skippercast:boundaries',draw);
  map.on('moveend',draw);
  setInterval(async()=>{
    draw();if(!plan.targets.length||!plan.publication)return;
    const current=plan,gate=await loadManifest(current.publication.region);
    if(plan!==current)return;
    if(gate.state!=='ready'||gate.manifest.export_sha256!==current.publication.export_sha256){rejected.set(current.publication.export_sha256,Date.now());plan.invalid=true;draw();}
  },60000);
  return {clear(){plan={targets:[],areas:[]};draw();}};
}
