import { fetchJSON } from "./forecast.js?v=6.0";
import { pointInGeometry, geometryIntersects } from "./geo-screen.js?v=6.0";
import { esc } from "./marine-charts.js?v=6.0";
export const MPA_SERVICE = "https://services2.arcgis.com/Uq9r85Potqm3MfRV/arcgis/rest/services/biosds582_fpu/FeatureServer/0/query";
export const MPA_QUERY = MPA_SERVICE+"?"+new URLSearchParams({where:"1=1",geometry:"-121.9,34.95,-120.55,35.85",geometryType:"esriGeometryEnvelope",inSR:"4326",spatialRel:"esriSpatialRelIntersects",outFields:"NAME,FULLNAME,Type,CCR",returnGeometry:"true",outSR:"4326",f:"geojson"});
export function validMPAs(data) {
  return data?.type === "FeatureCollection" && !data.exceededTransferLimit && data.features?.length >= 8 && data.features.every(f=>typeof f.properties?.NAME === "string" && ["Polygon","MultiPolygon"].includes(f.geometry?.type));
}
const sourceFor = (name) => "https://wildlife.ca.gov/Conservation/Marine/MPAs/" + (name.includes("Buchon") ? "Point-Buchon" : name.includes("Morro") ? "Morro-Bay" : name.includes("Piedras") ? "Piedras-Blancas" : "Cambria");
export async function initProtectedAreas(map, onChange) {
  const layer=L.layerGroup().addTo(map);
  const status=document.getElementById("mpa-status");
  let data=null, checked=null, live=false;
  map.createPane("protectedAreas").style.zIndex=440;
  function draw() {
    layer.clearLayers();
    for (const f of data?.features || []) {
      const p=f.properties;
      L.geoJSON(f,{pane:"protectedAreas",style:{color:"#bd3869",weight:2.5,fillColor:"#bd3869",fillOpacity:0.13,dashArray:p.Type==="SMR"?null:"7 4"}})
        .bindTooltip(esc(p.NAME),{permanent:map.getZoom()>=11,className:"mpa-label",direction:"center"})
        .bindPopup(`<strong>${esc(p.FULLNAME||p.NAME)}</strong><p>Fishing targets are excluded from every MPA in SkipperCast, including conservation areas with species exceptions.</p><p>${esc(p.CCR)} · ${live?"Boundary checked this session":"Saved boundary snapshot"} ${esc(checked?.slice(0,10))}</p><a href="${sourceFor(p.NAME)}" target="_blank" rel="noopener">Official CDFW map & rules ↗</a>`).addTo(layer);
    }
    status.textContent = data ? `MPAs shown · targets excluded · ${live?"checked now":"snapshot "+checked?.slice(0,10)}` : "MPA boundaries unavailable · fishing targets withheld";
    status.classList.toggle("error",!data);
  }
  try {
    const saved=await fetchJSON("data/protected-areas.geojson");
    if (!validMPAs(saved)) throw Error("Invalid MPA snapshot");
    data=saved; checked=saved.checked_at;
  } catch { /* Without a boundary dataset, fail closed for target layers. */ }
  draw();
  map.on("zoomend",draw);
  const screen={
    ready:()=>!!data,
    pointAllowed:p=>!!data && !data.features.some(f=>pointInGeometry([p.longitude,p.latitude],f.geometry)),
    geometryAllowed:g=>!!data && !data.features.some(f=>geometryIntersects(g,f.geometry)),
    async refresh() {
      try {
        const fresh=await fetchJSON(MPA_QUERY);
        if (!validMPAs(fresh)) throw Error("Incomplete MPA response");
        data=fresh; checked=new Date().toISOString(); live=true;
        draw(); onChange();
      } catch { status.textContent += " · live check unavailable"; }
    },
  };
  return screen;
}
