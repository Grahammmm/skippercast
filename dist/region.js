import defaultRegion from "./region-default.js?v=7.0";
let active = defaultRegion;
export const getRegion = () => active;
export const assetURL = (key) => active.assets[key] || null;
export function setRegion(region) {
  if (region?.schema_version !== 1 || !/^[a-z][a-z0-9-]{1,63}$/.test(region.id) || !region.forecast_points?.length) throw new Error("Invalid regional configuration");
  active = region;
}
export function acceptsFeed(data, region=active) {
  return data?.region_id === region.id || (!data?.region_id && region.id === "morro-bay");
}
export async function initRegion() {
  const response = await fetch("regions/index.json");
  if (!response.ok) throw new Error("Region directory unavailable");
  const index = await response.json();
  const requested = new URL(location.href).searchParams.get("region") || index.default_region;
  const entry = index.regions.find(r=>r.id===requested);
  if (!entry) throw new Error("Unknown region. Choose Morro Bay or Cambria–San Simeon.");
  const r = await fetch(entry.config);if(!r.ok) throw new Error("Region package unavailable");
  setRegion(await r.json());
  const chooser=document.getElementById("region-select");
  for(const region of index.regions){const option=document.createElement("option");option.value=region.id;option.textContent=region.name+(region.status==="preview"?" · preview":"");chooser.append(option);}
  chooser.value=active.id;
  chooser.addEventListener("change",()=>{const url=new URL(location.href);url.searchParams.set("region",chooser.value);url.hash="map";location.assign(url);});
  const area=document.getElementById("area");area.replaceChildren(new Option("All areas","all"));
  for(const [id,name] of Object.entries(active.source_names))area.add(new Option(name,id));
  const note=document.getElementById("region-note");
  note.hidden=active.status!=="preview";note.textContent=active.name+" preview · geological context; surveyed fishing spots pending";
  const coverage=await fetch(`regions/${active.id}/coverage.json`).then(r=>r.json());
  const panel=document.getElementById("region-coverage");
  const p=document.createElement("p");p.textContent=`${active.name}: ${coverage.published_targets} surveyed targets, ${coverage.published_bottom_views} bottom views. ${active.coverage_note}`;panel.append(p);
  const table=document.createElement("table");table.className="coverage-table";
  const head=table.createTHead().insertRow();for(const value of ["Data need","Coverage","What it supports"]){const th=document.createElement("th");th.textContent=value;head.append(th);}
  const body=table.createTBody();
  for(const need of coverage.needs){const row=body.insertRow();for(const value of [need.name,need.status,need.reason])row.insertCell().textContent=value;}
  panel.append(table);
  const link=document.createElement("a");link.href="https://github.com/Grahammmm/skippercast/blob/main/docs/regions.md";link.textContent="Regional setup and data contracts ↗";link.target="_blank";link.rel="noopener";panel.append(link);
}
