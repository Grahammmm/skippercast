import { assetURL } from "./region.js?v=8.7";
import { esc, num } from "./marine-charts.js?v=8.7";
export async function initCommercialAIS(map,{protectedAreas,onSelect,showMap}) {
  const layer=L.layerGroup();
  const checkbox=document.getElementById("layer-commercial");
  const focus=document.getElementById("show-commercial-ais");
  const status=document.getElementById("commercial-ais-status");
  if(!assetURL("commercial_ais")){status.textContent="No reviewed commercial AIS layer for this region.";checkbox.disabled=true;focus.disabled=true;return {draw(){}};}
  let features=[];
  try {
    const r=await fetch(assetURL("commercial_ais"),{signal:AbortSignal.timeout(10000)});
    if(!r.ok) throw Error();
    features=(await r.json()).features;
  } catch {status.textContent="Historical commercial AIS unavailable.";checkbox.disabled=true;focus.disabled=true;return {draw(){}};}
  function select(f) {
    const p=f.properties;
    onSelect(`<div class="eyebrow">COMMERCIAL AIS · HISTORICAL 2024</div><h2>${esc(p.label)}</h2><p class="evidence-note"><strong>Apparent fishing activity, not a verified catch spot.</strong><br>Depth and target species unknown. This offshore context is not qualified for the 200-foot fishing limit.</p><div class="stats"><div class="stat"><span>Days with activity</span><strong>${p.days_with_apparent_fishing}</strong></div><div class="stat"><span>Apparent fishing time</span><strong>${num(p.apparent_fishing_hours)} hr</strong></div></div><p>${esc(p.resolution_note)}</p><p>Gear classification: ${esc(p.gear_label)}. ${esc(p.fishing_location_confidence)}. Local sportfishing-charter identity remains unverified.</p><button id="commercial-weather" class="primary">Conditions near this grid cell ↗</button><details class="detail-section"><summary>Dates, coverage & method</summary><p>Reviewed all 61 daily files in July and September 2024. Cells need at least 15 apparent fishing minutes on each of two dates, and at least one hour total. Other months were not analyzed.</p><p>Activity dates (UTC): ${p.active_dates_utc.map(esc).join(", ")}</p><p>${esc(p.vessel_count_note)} AIS coverage is incomplete, especially for smaller vessels. Model classifications can be wrong. There is no species, catch-rate or exact lingering-position evidence.</p></details><details class="detail-section"><summary>Source & license</summary><p>${esc(p.attribution)}</p><p>Changes: local geographic extraction, repeat-day selection and MPA exclusion. No boat tracks or personal vessel identifiers are published in this layer.</p><a href="${p.source_url}" target="_blank" rel="noopener">Global Fishing Watch source dataset ↗</a> · <a href="https://creativecommons.org/licenses/by-nc/4.0/" target="_blank" rel="noopener">CC BY-NC 4.0 ↗</a><p><a href="commercial-ais.html">Research method and complete coverage ↗</a></p></details>`,{...p,geometry:f.geometry});
  }
  function current() {return features.filter(f=>protectedAreas.pointAllowed(f.properties)&&protectedAreas.geometryAllowed(f.geometry));}
  function draw() {
    layer.clearLayers();
    const rows=current();
    status.textContent=`${rows.length} historical grid cells · Jul & Sep 2024 · depth unknown`;
    if(!checkbox.checked) {map.removeLayer(layer);return;}
    layer.addTo(map);
    for(const f of rows) {
      const p=f.properties;
      L.geoJSON(f,{style:{color:"#ad7715",weight:2.5,fillColor:"#e5bb45",fillOpacity:.23}}).on("click",()=>select(f)).addTo(layer);
      L.marker([p.latitude,p.longitude],{keyboard:true,title:`${p.label} · ${p.days_with_apparent_fishing} days · 2024 AIS · depth unknown`,icon:L.divIcon({className:"commercial-label",html:`<span>AIS ${p.id.slice(-3)} · ${p.days_with_apparent_fishing} days</span>`,iconSize:[125,32],iconAnchor:[62,16]})}).on("click",()=>select(f)).addTo(layer);
    }
  }
  checkbox.addEventListener("change",draw);
  focus.addEventListener("click",()=>{
    checkbox.checked=true;draw();document.getElementById("map-options").close();showMap();
    const rows=current();if(rows.length) map.fitBounds(L.geoJSON({type:"FeatureCollection",features:rows}).getBounds(),{padding:[65,135],maxZoom:12});
  });
  draw();return {draw};
}
