import {assetURL,getRegion} from './region.js?v=8.9';
import {esc} from './marine-charts.js?v=8.9';
export async function initRegionalContext(map,screen,onSelect) {
  if(!assetURL('regional_context'))return;
  const response=await fetch(assetURL('regional_context'),{signal:AbortSignal.timeout(10000)});
  if(!response.ok)throw Error('Regional context unavailable');
  const data=await response.json();if(data.region_id!==getRegion().id)throw Error('Context region mismatch');
  const layer=L.layerGroup().addTo(map);
  const draw=()=>{
    layer.clearLayers();const species=document.getElementById('species-select').value;
    if(map.getZoom()<11 || !document.getElementById('layer-areas').checked)return;
    for(const f of data.features){
      const p=f.properties;
      if(!p.species.includes(species)||!screen.geometryAllowed(f.geometry))continue;
      L.geoJSON(f,{onEachFeature:(_,shape)=>shape.on('add',()=>{const el=shape.getElement();if(el){el.setAttribute('role','button');el.setAttribute('tabindex','0');el.setAttribute('aria-label',p.name+' historical reef area');el.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();shape.fire('click');}});}}),style:{color:'#b07b30',weight:1.3,dashArray:'6 4',fillColor:'#d6aa65',fillOpacity:.08}})
        .bindTooltip(esc(p.name)+' · historical reef area')
        .on('click',()=>onSelect(`<div class="eyebrow">HISTORICAL REEF AREA · ${esc(p.source_date)}</div><h2>${esc(p.name)}</h2><p>${esc(p.material)} · historically reported ${p.reported_depth_ft.join('–')} ft</p><p class="evidence-note">Approximate search context. Present depth, relief and fish presence are unverified. No charter AIS or catch claim supports this outline.</p><p>The outline groups the old reef records. It is not the seabed footprint or a recommended drift. Use current charts and sonar; check the selected date’s Southern California groundfish restrictions.</p><button class="primary" id="regional-weather">Local conditions ↗</button><details><summary>Source and uncertainty</summary><p>${esc(data.source.datum)}</p><p>${esc(data.source.derivation)}</p><p>No measured bottom image or A/B/C grade is available for this area.</p><a href="${esc(p.source_url)}" target="_blank" rel="noopener">CDFW reef inventory ↗</a></details>`,{...p,geometry:f.geometry})).addTo(layer);
    }
  };
  document.getElementById('species-select').addEventListener('change',draw);
  document.getElementById('layer-areas').addEventListener('change',draw);map.on('zoomend',draw);
  document.addEventListener('skippercast:boundaries',draw);draw();
}
