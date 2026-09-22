import defaultRegion from "./region-default.js?v=8.4";
let active = defaultRegion;
let directory = [];
export const getRegion = () => active;
export const getRegionDirectory = () => directory;
export function renderTargetOptions(select, options, value) {
  if([...select.options].map(o=>o.value).join('|')!==options.map(o=>o.id).join('|')) {
    select.replaceChildren();
    const groups=new Map();
    for(const target of options) {
      if(!groups.has(target.group)){const group=document.createElement('optgroup');group.label=target.group;groups.set(target.group,group);select.append(group);}
      groups.get(target.group).append(new Option(target.name,target.id));
    }
  }
  select.value=value;
}
export const assetURL = (key) => active.assets[key] || null;
export function setRegion(region) {
  if (region?.schema_version !== 1 || !/^[a-z][a-z0-9-]{1,63}$/.test(region.id) || !region.forecast_points?.length) throw new Error("Invalid regional configuration");
  active = region;
}
export function acceptsFeed(data, region=active) {
  return data?.region_id === region.id || (!data?.region_id && region.id === "morro-bay");
}
export async function initRegion() {
  const response = await fetch("regions/index.json",{cache:"no-cache"});
  if (!response.ok) throw new Error("Region directory unavailable");
  const index = await response.json();
  directory=index.regions;
  const requested = new URL(location.href).searchParams.get("region") || index.default_region;
  const entry = index.regions.find(r=>r.id===requested);
  if (!entry) throw new Error("Unknown region. Open the region menu to choose an available coast.");
  const r = await fetch(entry.config,{cache:"no-cache"});if(!r.ok) throw new Error("Region package unavailable");
  setRegion(await r.json());
  const species=document.getElementById('species-select');
  species.replaceChildren();
  const groups=new Map();
  for(const target of active.target_options || []) {
    if(!groups.has(target.group)) {const group=document.createElement('optgroup');group.label=target.group;groups.set(target.group,group);species.append(group);}
    groups.get(target.group).append(new Option(target.name,target.id));
  }
  if(!species.options.length) throw Error('Regional species definitions unavailable');
  const target=new URL(location.href).searchParams.get('target');
  species.value=active.species.includes(target)?target:active.species[0];
  const chooser=document.getElementById("region-select");
  for(const region of index.regions){const option=document.createElement("option");option.value=region.id;option.textContent=region.name+(region.status==="preview"?" · preview":"");chooser.append(option);}
  chooser.value=active.id;
  chooser.addEventListener("change",()=>{const url=new URL(location.href);url.searchParams.set("region",chooser.value);url.searchParams.set('target',species.value);for(const key of ['view','focus','spot'])url.searchParams.delete(key);url.hash="map";location.assign(url);});
  const area=document.getElementById("area");area.replaceChildren(new Option("All areas","all"));
  for(const [id,name] of Object.entries(active.source_names))area.add(new Option(name,id));
  const note=document.getElementById("region-note");
  note.hidden=active.status!=="preview";note.textContent=active.name+" · "+(active.preview_label || "geological context; surveyed fishing spots pending");
  const panel=document.getElementById("region-coverage");
  let coverage;
  try {
    const response=await fetch(`regions/${active.id}/coverage.json`,{signal:AbortSignal.timeout(10000)});
    if(!response.ok) throw new Error('Coverage unavailable');
    coverage=await response.json();
    if(coverage.region_id!==active.id||!Array.isArray(coverage.needs)) throw new Error('Coverage mismatch');
  } catch {
    panel.textContent='The data coverage summary could not load. The map can still open; each layer retains its own source and legal checks.';
    return;
  }
  const p=document.createElement("p");p.textContent=`${active.name}: ${coverage.published_targets} surveyed targets, ${coverage.published_bottom_views} bottom views. ${active.coverage_note}`;panel.append(p);
  const table=document.createElement("table");table.className="coverage-table";
  const head=table.createTHead().insertRow();for(const value of ["Data need","Coverage","What it supports"]){const th=document.createElement("th");th.textContent=value;head.append(th);}
  const body=table.createTBody();
  for(const need of coverage.needs){const row=body.insertRow();for(const value of [need.name,need.status,need.reason])row.insertCell().textContent=value;}
  panel.append(table);
  const link=document.createElement("a");link.href="https://github.com/Grahammmm/skippercast/blob/main/docs/regions.md";link.textContent="Regional setup and data contracts ↗";link.target="_blank";link.rel="noopener";panel.append(link);
}

// Geographic observation/advisory bindings are data, shared by any large region.
export function localContext(point, region=active) {
  const p=typeof point === 'number' ? region.forecast_points[point] : typeof point === 'string' ? region.forecast_points.find(p=>p.id===point) : point;
  const id=p?.context;
  return id && region.contexts?.[id] ? {id,...region.contexts[id]} : {id:'default',name:region.name,stations:region.stations,marine_zones:region.marine_zones};
}
export function pointBundle(bundle, point) {
  if(!bundle) return bundle;
  const context=localContext(point), data=bundle.contexts?.[context.id];
  // A missing local request stays missing, never inherited from another coast.
  return bundle.contexts ? {...bundle,...(data||{tides:[],extremes:[],alerts:{},water:null}),stations:context.stations,marine_zones:context.marine_zones} : bundle;
}
