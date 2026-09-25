import { initRegion } from "./region.js?v=8.11";
import {loadCoasts,coastForPackage,initCoastSelector,initCoastalContext} from './coasts.js?v=8.11';
import {initRecentDiscussions} from './recent-discussions.js?v=8.12';
try {
  const catalog=await loadCoasts(),url=new URL(location.href),requested=url.searchParams.get('coast');
  if(requested) {
    const coast=catalog.regions.find(r=>r.id===requested);if(!coast)throw Error('Unknown coastal region');
    const {initCoastalDiscovery}=await import('./coastal-discovery.js?v=8.15');
    await initCoastalDiscovery(catalog,coast);
  } else {
    await initRegion();
    const coast=coastForPackage(url.searchParams.get('region')||'morro-bay',catalog);
    initCoastSelector(catalog,coast);
    void initCoastalContext(catalog,coast);
    void initRecentDiscussions(url.searchParams.get('region')||'morro-bay');
    await import("./app.js?v=8.11");
  }
} catch(error) {
  const panel=document.getElementById("map-empty");panel.hidden=false;
  panel.replaceChildren();const title=document.createElement("strong");title.textContent="This region could not load";
  const reason=document.createElement("p");reason.textContent=error.message;
  const retry=document.createElement("a");retry.href="/?region=morro-bay#map";retry.textContent="Open Morro Bay";
  panel.append(title,reason,retry);console.error(error);
}
