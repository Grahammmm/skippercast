import { assetURL } from "./region.js?v=8.11";
import { esc } from "./marine-charts.js?v=8.11";
export async function initGeology(map, protectedAreas, onSelect) {
  if(!assetURL("geology")) return;
  const layer=L.layerGroup().addTo(map);
  try {
    const response=await fetch(assetURL("geology"),{signal:AbortSignal.timeout(10000)});if(!response.ok) throw new Error("Geology unavailable");
    const data=await response.json();
    const draw=()=>{
      layer.clearLayers();const species=document.getElementById("species-select").value;
      if(map.getZoom()<10 || !document.getElementById('layer-areas').checked || !["reef","halibut","dungeness"].includes(species)) return;
      for(const f of data.features){
        const p=f.properties;
        if(species==="reef" ? p.kind==="sediment" : p.kind!=="sediment") continue;
        if(!protectedAreas.geometryAllowed(f.geometry)) continue;
        const color=p.kind==="rock"?"#28786d":p.kind==="mixed"?"#648070":"#b28951";
        L.geoJSON(f,{style:{color,weight:1.2,dashArray:"6 5",fillColor:color,fillOpacity:.08}})
          .bindTooltip(`${esc(p.label)} · geology only`)
          .on("click",()=>onSelect(`<div class="eyebrow">GEOLOGICAL CONTEXT · EXPANSION PREVIEW</div><h2>${esc(p.label)}</h2><p>${p.area_km2} km² · USGS map unit ${esc(p.unit)}</p><p class="evidence-note"><strong>Depth and fish presence are unverified.</strong> This is a mapped geological area, not a qualified fishing spot. The 200-foot depth limit has not been checked across this polygon.</p><p>${p.kind==="mixed"?"A sediment layer overlies bedrock here; exposed rough rock is not established.":p.kind==="rock"?"Mapped bedrock may offer structure, but this geological interpretation does not resolve individual rocks or fish.":"Mapped marine sediment is useful habitat context for soft-bottom species; substrate alone does not establish a productive location."}</p><button class="primary" id="geology-weather">Regional conditions ↗</button><details><summary>Source and interpretation</summary><p>${esc(data.source.attribution)}. ${esc(data.source.derivation)}</p><p>${esc(data.source.limitations)}</p><a href="${p.source_url}" target="_blank" rel="noopener">USGS publication and metadata ↗</a></details>`,{...p,geometry:f.geometry})).addTo(layer);
      }
    };
    document.getElementById("species-select").addEventListener("change",draw);document.getElementById('layer-areas').addEventListener('change',draw);map.on("zoomend",draw);draw();
  } catch { document.getElementById("region-note").textContent="Expansion preview · geological context unavailable; no surveyed fishing targets published."; }
}
