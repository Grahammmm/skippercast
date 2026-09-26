import {assetURL} from "./region.js?v=8.12";
import { POINTS, readConditions, distanceNm, directionTo } from "./marine-data.js?v=8.12";
import { esc, num, full, from } from "./marine-charts.js?v=8.12";
export function offsetPosition(p, direction, metres) {
  const a=direction*Math.PI/180;
  return [p.longitude+Math.sin(a)*metres/(111320*Math.cos(p.latitude*Math.PI/180)),p.latitude+Math.cos(a)*metres/111320];
}
export function makeDriftGuide(target,speed,toward,minutes=6) {
  if (![target.latitude,target.longitude,speed,toward,minutes].every(Number.isFinite)||speed<0.1||speed>5||toward<0||toward>=360||minutes<=0) return null;
  const half=speed*1852*minutes/120;
  return {type:"LineString",coordinates:[offsetPosition(target,(toward+180)%360,half),[target.longitude,target.latitude],offsetPosition(target,toward,half)]};
}
export function initDriftGuides(map,{targets,selected,protectedAreas,selectTarget}) {
  const layer=L.layerGroup().addTo(map);
  const host=document.getElementById("drift-options");
  host.innerHTML=`<strong>Drift setup guides</strong><label>Direction source<select id="drift-mode"><option value="model">Modeled surface current</option><option value="measured">My measured boat drift</option><option value="off">Structure lines only</option></select></label><div class="drift-inputs" id="measured-drift" hidden><label>Speed (kt)<input id="drift-speed" type="number" min="0.1" max="5" step="0.1" inputmode="decimal" placeholder="0.5"></label><label>Course toward (° true)<input id="drift-course" type="number" min="0" max="359" step="1" inputmode="numeric" placeholder="180"></label></div><p id="drift-status" class="small">Zoom in for blue current-guided setup lines.</p><p class="small">Blue: 6-minute surface-current projection through a target, with a trial start 3 minutes upstream. Wind arrow shown separately. Surface flow includes modeled wave/tidal effects; local windage, bottom current and depth along the line are unverified. Make a test drift before dropping gear. Brown: fixed structure alignment.</p>`;
  const key=L.control({position:"bottomright"});
  key.onAdd=()=>{const el=L.DomUtil.create("div","drift-map-key");el.textContent="Pink: MPAs · brown: structure";L.DomEvent.disableClickPropagation(el);return el;};
  if(!assetURL("survey_habitat"))key.addTo(map);
  let context=null, measuredAt=null, measuredTargetId=null;
  const mode=()=>document.getElementById("drift-mode").value;
  function draw() {
    layer.clearLayers();
    const status=document.getElementById("drift-status");
    const enabled=document.getElementById("layer-drifts").checked&&mode()!=="off";
    if(key.getContainer())key.getContainer().textContent="Pink: MPAs · brown: structure";
    if(!targets().length){status.textContent="No depth-qualified drift targets in this region. Habitat context does not authorize an automatic drift line.";return;}
    if(!enabled) {status.textContent="Current-guided overlay off.";return;}
    const t=context?.time;
    if(!context?.bundle) {status.textContent="Loading current forecast…";return;}
    if(Date.now()-context.bundle.retrieved>3*3600000) {status.textContent="Current forecast stale; setup guides withheld.";return;}
    const meta=context.bundle.models.meteofrance_currents?.meta;
    if(mode()==="model" && (!Number.isFinite(meta?.last_run_initialisation_time)||Date.now()/1000-meta.last_run_initialisation_time>48*3600)) {status.textContent="Current-model run unavailable or stale; guides withheld.";return;}
    if(mode()==="measured" && (!measuredAt || Date.now()-measuredAt>30*60000 || Math.abs(t-Date.now()/1000)>3600)) {status.textContent="Enter a fresh test-drift speed/course at the current hour. Measurements expire after 30 minutes.";return;}
    const focus=selected();
    if(mode()==="measured" && (!focus || focus.id!==measuredTargetId)) {status.textContent="Select the reef where you made the test drift, then enter its speed/course. A measurement applies only to that reef.";return;}
    const nearby=targets().filter(p=>mode()==="measured"?p.id===measuredTargetId:(map.getZoom()>=13&&map.getBounds().contains([p.latitude,p.longitude]))||p.id===focus?.id).slice(0,18);
    let count=0;
    for(const target of nearby) {
      const i=POINTS.reduce((best,p,j)=>distanceNm(p,target)<distanceNm(POINTS[best],target)?j:best,0);
      const c=readConditions(context.bundle,i,t,context.family);
      const speed=mode()==="measured"?Number(document.getElementById("drift-speed").value):c.current;
      const toward=mode()==="measured"?Number(document.getElementById("drift-course").value):c.currentTo;
      if(mode()==="measured" && (!document.getElementById("drift-speed").value||!document.getElementById("drift-course").value)) continue;
      const geometry=makeDriftGuide(target,speed,toward);
      if(!geometry||!protectedAreas.pointAllowed(target)||!protectedAreas.geometryAllowed(geometry)) continue;
      const coords=geometry.coordinates.map(p=>[p[1],p[0]]);
      const label=`${mode()==="measured"?"Measured boat drift":"Surface-current guide"} · ${num(speed)} kt toward ${from(toward)} · ${full(t)}`;
      L.polyline(coords,{color:"#216fc1",weight:3,dashArray:mode()==="model"?"5 5":null})
        .bindTooltip(esc(label)).on("click",()=>selectTarget(target.id)).addTo(layer);
      L.circleMarker(coords[0],{radius:5,color:"#216fc1",fillColor:"#fff",fillOpacity:1,weight:2})
        .bindTooltip(`Trial start · 3 minutes upstream. ${esc(label)}. Confirm sonar depth and actual drift.`).addTo(layer);
      L.marker(coords[2],{interactive:false,icon:L.divIcon({className:"drift-arrow",html:`<span style="transform:rotate(${toward}deg)">↑</span>`,iconSize:[26,26],iconAnchor:[13,13]})}).addTo(layer);
      if(target.id===focus?.id && Number.isFinite(c.windFrom)) {
        L.marker(coords[1],{interactive:false,icon:L.divIcon({className:"drift-arrow",html:`<span style="color:#53717a;transform:rotate(${directionTo(c.windFrom)}deg)">⇡</span>`,iconSize:[26,26],iconAnchor:[-12,13]})}).addTo(layer);
      }
      count++;
    }
    status.textContent=count?`${count} setup guide${count===1?"":"s"} · ${full(t)} · ${mode()==="model"?"coarse surface-current model, not boat drift":"your measured boat drift"}`:map.getZoom()<13?"Zoom in to show setup guides. Tap a reef to inspect one at any zoom.":"No valid guides in this view/hour. Missing current, near-zero flow or MPA crossings are withheld.";
    if(count && key.getContainer()) key.getContainer().textContent=`Blue: ${mode()==="model"?"current-only trial drift":"measured drift"} · pink: MPAs`;
  }
  for(const id of ["drift-mode","drift-speed","drift-course","layer-drifts"]) document.getElementById(id).addEventListener("change",()=>{
    document.getElementById("measured-drift").hidden=mode()!=="measured";
    if(id==="drift-speed"||id==="drift-course") {measuredAt=Date.now();measuredTargetId=selected()?.id;}
    draw();
  });
  map.on("zoomend moveend",draw);
  return {draw,update(next){context=next;draw();}};
}
