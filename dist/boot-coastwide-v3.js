try {
  const {initHomePort}=await import('./home-port.js?v=1');
  if(!await initHomePort()) {
    // First visit is choosing a port, or a saved port is navigating to its region.
  } else {
  const {initRegion}=await import('./region.js?v=8.14');
  const {loadCoasts,coastForPackage,initCoastSelector,initCoastalContext}=await import('./coasts.js?v=8.26');
  const {initRecentDiscussions}=await import('./recent-discussions.js?v=8.14');
  const catalog=await loadCoasts(),url=new URL(location.href),requested=url.searchParams.get('coast');
  if(requested) {
    const coast=catalog.regions.find(r=>r.id===requested);if(!coast)throw Error('Unknown coastal region');
    const {initCoastalDiscovery}=await import('./coastal-discovery-v4.js?v=8.49');
    await initCoastalDiscovery(catalog,coast);
  } else {
    await initRegion();
    const coast=coastForPackage(url.searchParams.get('region')||'morro-bay',catalog);
    initCoastSelector(catalog,coast);
    void initCoastalContext(catalog,coast);
    void initRecentDiscussions(url.searchParams.get('region')||'morro-bay');
    await import("./app.js?v=8.15");
  }
  }
} catch(error) {
  const panel=document.getElementById("map-empty");panel.hidden=false;
  panel.replaceChildren();const title=document.createElement("strong");title.textContent="This region could not load";
  const reason=document.createElement("p");reason.textContent=error.message;
  const retry=document.createElement("a");retry.href="/?region=morro-bay#map";retry.textContent="Open Morro Bay";
  panel.append(title,reason,retry);console.error(error);
}
