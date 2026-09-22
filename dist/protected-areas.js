import { getRegion, assetURL, acceptsFeed } from "./region.js?v=8.5";
import { fetchJSON } from "./forecast.js?v=8.5";
import { pointInGeometry, geometryIntersects } from "./geo-screen.js?v=8.5";
import { esc } from "./marine-charts.js?v=8.5";
export const MPA_SERVICE = "https://services2.arcgis.com/Uq9r85Potqm3MfRV/arcgis/rest/services/biosds582_fpu/FeatureServer/0/query";
export const MPA_QUERY = MPA_SERVICE+"?"+new URLSearchParams({where:"1=1",geometry:getRegion().mpa.bounds.join(","),geometryType:"esriGeometryEnvelope",inSR:"4326",spatialRel:"esriSpatialRelIntersects",outFields:"NAME,FULLNAME,Type,CCR",returnGeometry:"true",outSR:"4326",f:"geojson"});
export function validMPAs(data) {
  return data?.type === "FeatureCollection" && !data.exceededTransferLimit && data.features?.length >= getRegion().mpa.minimum_features && data.features.every(f=>typeof f.properties?.NAME === "string" && ["Polygon","MultiPolygon"].includes(f.geometry?.type));
}
const sourceFor = (name) => !["Buchon","Morro","Piedras","Cambria"].some(x=>name.includes(x)) ? "https://wildlife.ca.gov/Conservation/Marine/MPAs/Network/Southern-California" : "https://wildlife.ca.gov/Conservation/Marine/MPAs/" + (name.includes("Buchon") ? "Point-Buchon" : name.includes("Morro") ? "Morro-Bay" : name.includes("Piedras") ? "Piedras-Blancas" : "Cambria");
export async function initProtectedAreas(map, onChange) {
  const layer=L.layerGroup().addTo(map);
  const status=document.getElementById("mpa-status");
  let data=null, checked=null, live=false, extra=null, extraChecked=null;
  const extraFresh=()=>!assetURL("closures") || !!extra && Date.now()-Date.parse(extraChecked)>=-300000 && Date.now()-Date.parse(extraChecked)<=36*3600000;
  const freshEnough=()=>extraFresh() && !!data && Number.isFinite(Date.parse(checked)) && Date.now()-Date.parse(checked) >= -300000 && Date.now()-Date.parse(checked) <= 36*3600000;
  map.createPane("protectedAreas").style.zIndex=440;
  function draw() {
    layer.clearLayers();
    for (const f of [...(data?.features || []),...(extra?.features||[])]) {
      const p=f.properties;
      L.geoJSON(f,{pane:"protectedAreas",style:{color:"#bd3869",weight:2.5,fillColor:"#bd3869",fillOpacity:0.13,dashArray:p.Type==="SMR"?null:"7 4"}})
        .bindTooltip(esc(p.NAME),{permanent:map.getZoom()>=11,className:"mpa-label",direction:"center"})
        .bindPopup(`<strong>${esc(p.FULLNAME||p.NAME)}</strong><p>${p.Type==="GEA"?"NOAA groundfish closure. SkipperCast excludes all target species here as a conservative planning rule. Federal regulations control over this supplemental map.":"Fishing targets are excluded from every MPA, including conservation areas with species exceptions."}</p><p>${esc(p.CCR)} · ${p.Type==="GEA"?"NOAA coordinate check":live?"Boundary checked this session":"Saved boundary snapshot"} ${esc((p.Type==="GEA"?extraChecked:checked)?.slice(0,10)||"unavailable")}</p><a href="${p.Type==="GEA"?"https://www.fisheries.noaa.gov/west-coast/sustainable-fisheries/west-coast-groundfish-closed-areas":sourceFor(p.NAME)}" target="_blank" rel="noopener">Official boundary & rules ↗</a>`).addTo(layer);
    }
    status.textContent = data ? `MPAs${extra?" + groundfish exclusions":""} shown · targets excluded · ${live?"checked now":"snapshot "+checked?.slice(0,10)}` : "MPA boundaries unavailable · fishing targets withheld";
    if(data && !freshEnough()) status.textContent += " · boundary check stale; fishing targets withheld";
    status.classList.toggle("error",!freshEnough());
    document.dispatchEvent(new CustomEvent("skippercast:boundaries"));
  }
  try {
    const saved=await fetchJSON(assetURL("protected_areas"));
    if (!validMPAs(saved)) throw Error("Invalid MPA snapshot");
    data=saved; checked=saved.checked_at;
    if(assetURL("closures")) {
      const candidate=await fetchJSON(assetURL("closures"));
      if(candidate.region_id!==getRegion().id || candidate.type!=="FeatureCollection" || !candidate.features?.length || !candidate.features.every(f=>["Polygon","MultiPolygon"].includes(f.geometry?.type)))throw Error("Invalid additional closures");
      extra=candidate;extraChecked=candidate.checked_at;
    }
  } catch { /* Without a boundary dataset, fail closed for target layers. */ }
  draw();
  map.on("zoomend",draw);
  const screen={
    ready:()=>freshEnough(),
    revision:()=>`${checked}|${extraChecked}|${freshEnough()}`,
    exportExclusions:()=>freshEnough()?{checked_at:extra?new Date(Math.min(Date.parse(checked),Date.parse(extraChecked))).toISOString():checked,features:[...data.features,...(extra?.features||[])]}:null,
    inspect(p){
      const matches=[...(data?.features||[]),...(extra?.features||[])].filter(f=>p.geometry?geometryIntersects(p.geometry,f.geometry):pointInGeometry([p.longitude,p.latitude],f.geometry));
      return {status:matches.length?'excluded':freshEnough()?'clear':'unavailable',fresh:freshEnough(),names:matches.map(f=>f.properties.FULLNAME||f.properties.NAME)};
    },
    snapshot:()=>freshEnough()?{revision:`${checked}|${extraChecked}|true`,geometries:[...data.features,...(extra?.features||[])].map(f=>f.geometry)}:null,
    pointAllowed:p=>freshEnough() && ![...data.features,...(extra?.features||[])].some(f=>pointInGeometry([p.longitude,p.latitude],f.geometry)),
    geometryAllowed:g=>freshEnough() && ![...data.features,...(extra?.features||[])].some(f=>geometryIntersects(g,f.geometry)),
    async refresh() {
      if(assetURL('closures')) {
        try {
          const feed=await fetchJSON(getRegion().daily_feed), record=feed.sources?.['additional-closures'];
          if(acceptsFeed(feed)&&record?.status==='ok'&&record.data?.sha256!==extra?.source_sha256)extraChecked=null;
          if(!acceptsFeed(feed)||record?.status!=='ok'||record.data?.sha256!==extra?.source_sha256)throw Error('Additional closure check missing or changed');
          extraChecked=record.data_retrieved_at;
        } catch { /* Keep original time; stale checks withhold context and targets. */ }
      }
      try {
        const fresh=await fetchJSON(MPA_QUERY);
        if (!validMPAs(fresh)) throw Error("Incomplete MPA response");
        data=fresh; checked=new Date().toISOString(); live=true;
        draw(); onChange();
      } catch {
        try {
          const feed=await fetchJSON(getRegion().daily_feed);
          const record=feed.sources?.["mpa-boundaries"];
          if(!acceptsFeed(feed) || record?.status!=="ok" || !validMPAs(record.data?.geojson)) throw Error();
          data=record.data.geojson;checked=record.data_retrieved_at;live=false;
          draw();onChange();
        } catch {status.textContent += " · live check unavailable";onChange();}
      }
    },
  };
  return screen;
}
