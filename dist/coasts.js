// The five coastal browse regions are separate from survey-qualified packages.
// Keep this module independent of regional modules: boot uses it before a package is selected.
const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let directory;
export async function loadCoasts() {
  if(directory)return directory;
  const r=await fetch('data/coasts.json',{signal:AbortSignal.timeout(10000)});
  if(!r.ok)throw Error('Coastal directory unavailable');
  const data=await r.json();
  if(data.schema_version!==1 || data.regions?.length!==5)throw Error('Invalid coastal directory');
  directory=data;return data;
}
export function coastAt(point,catalog=directory) {
  if(!Number.isFinite(point?.latitude)||!Number.isFinite(point?.longitude))return null;
  // Half-open latitude bands make every boundary deterministic. These are browsing extents, not marine borders.
  return catalog?.regions.find(r=>point.longitude>=r.bounds[0]&&point.longitude<=r.bounds[2]&&point.latitude>=r.latitude[0]&&(point.latitude<r.latitude[1]||point.latitude===42&&r.id==='northern')) || null;
}
export function coastForPackage(id,catalog=directory) {return catalog?.regions.find(r=>r.packages.includes(id)) || null;}
export function coastURL(href,coast,{point,zoom,target,packageId,overview=false}={}) {
  const url=new URL(href);
  for(const key of ['region','coast','focus','spot','view','target'])url.searchParams.delete(key);
  const id=packageId || (!overview && coast.default_package);
  if(id && coast.packages.includes(id))url.searchParams.set('region',id);else url.searchParams.set('coast',coast.id);
  if(target && [...coast.targets,...coast.watch].includes(target))url.searchParams.set('target',target);
  if(point && Number.isFinite(point.latitude)&&Number.isFinite(point.longitude)&&Number.isFinite(zoom))url.searchParams.set('view',`${point.latitude.toFixed(5)},${point.longitude.toFixed(5)},${zoom}`);
  url.hash='map';return url;
}
export function sourceFresh(record,maxHours=36,now=Date.now()) {
  const age=(now-Date.parse(record?.data_retrieved_at))/3600000;
  return record?.status==='ok' && Number.isFinite(age) && age>=-0.1 && age<=maxHours;
}
export function ensoCurrent(record,catalog,now=Date.now()) {
  const days=(now-Date.parse(record?.data?.published_date+'T00:00:00Z'))/86400000;
  return sourceFresh(record,catalog.policy.source_check_max_age_hours,now)&&Number.isFinite(days)&&days>=-1&&days<=catalog.policy.enso_max_age_days;
}
export function coastalTargetOptions(coast,status,now=Date.now()) {
  const options=coast.target_options.map(t=>({...t}));
  if(!sourceFresh({status:'ok',data_retrieved_at:status?.completed_at},36,now))return options;
  const supported=(status?.regions?.[coast.id]?.watch||[]).filter(w=>w.status==='recent-located-reports').map(w=>w.target);
  for(const target of coast.watch_options||[])if(supported.includes(target.id)&&!options.some(t=>t.id===target.id))options.push({...target,name:target.name+' · recent reports',seasonal:true});
  return options;
}
export function initCoastSelector(catalog,coast) {
  const select=document.getElementById('coast-select');
  select.replaceChildren(...catalog.regions.map(r=>new Option(r.name,r.id)));select.value=coast.id;select.disabled=false;
  select.addEventListener('change',()=>{
    const next=catalog.regions.find(r=>r.id===select.value);
    location.assign(coastURL(location.href,next,{target:document.getElementById('species-select').value}));
  });
}
export async function loadCoastalStatus(catalog) {
  for(const url of [catalog.feed_url.replace('/latest.json','/status.json'),'data/coastal-status.json']) {
    try {
      const r=await fetch(url,{cache:'no-cache',signal:AbortSignal.timeout(10000)});if(!r.ok)continue;
      const data=await r.json();if(data.schema_version===1 && data.scope==='california-coast-directory')return data;
    }catch{/* The saved snapshot keeps its actual retrieval time. */}
  }
  return null;
}
export function seasonalMarkup(catalog,coast,status) {
  const record=status?.sources?.enso,current=ensoCurrent(record,catalog),data=record?.data;
  const rules=status?.sources?.[coast.id+'-rules'];
  const groundfish=status?.sources?.[coast.id+'-groundfish-table'];
  const watch=status?.regions?.[coast.id]?.watch || coast.watch.map(target=>({target,status:'watch-only',evidence:[]}));
  const fresh=sourceFresh({status:'ok',data_retrieved_at:status?.completed_at});
  return `<p>${esc(coast.limits)}. ${esc(coast.note)}</p>
    <p><a href="${esc(catalog.enso_url)}" target="_blank" rel="noopener">NOAA seasonal outlook ↗</a>: ${data?`${esc(data.status)} · issued ${esc(data.published_date)}${current?'':' · current check unavailable'}`:'check unavailable'}.</p>
    <p>${watch.length?'Seasonal watch: '+watch.map(w=>`${esc(catalog.target_names[w.target]||w.target)}${fresh&&w.status==='recent-located-reports'?' · recent located reports':''}`).join('; ')+'.':''} A watch is a reason to check local water and reports; it does not establish fish presence.</p>
    ${watch.filter(w=>fresh&&w.status==='recent-located-reports').map(w=>`<p>${esc(catalog.target_names[w.target])}: ${w.evidence.filter(e=>/^https:\/\//.test(e.url)).map(e=>`<a href="${esc(e.url)}" target="_blank" rel="noopener">${esc(e.date)} · ${esc(e.publisher)}</a>`).join(' · ')}</p>`).join('')}
    <p class="small">CDFW summary: ${rules?.data?.published_date?'updated '+esc(rules.data.published_date):'update date unavailable'} · ${sourceFresh(rules)?'source checked '+esc(rules.data_retrieved_at.slice(0,10)):'current source check unavailable'}${rules?.changed_since_previous?' · document changed; read the latest rules':''}. Daily source checks do not approve legal changes automatically.</p>
    ${coast.groundfish_table_url?`<p class="small">CDFW groundfish table: ${sourceFresh(groundfish)?'PDF checked '+esc(groundfish.data_retrieved_at.slice(0,10)):'current PDF check unavailable'}${groundfish?.changed_since_previous?' · document changed; review needed':''}. <a href="${esc(coast.groundfish_table_url)}" target="_blank" rel="noopener">Open official table ↗</a></p>`:''}
    <p class="small">NOAA temperature, currents and ocean-color layers in mapped areas retain their own dates and coverage. Unlocated port totals cannot promote a fishing location.</p>
    <p><a href="${esc(coast.rules_url)}" target="_blank" rel="noopener">${esc(coast.name)} CDFW rules ↗</a> · <a href="${esc(catalog.seasonal_source)}" target="_blank" rel="noopener">Why species can shift ↗</a></p>`;
}
export async function initCoastalContext(catalog,coast) {
  const root=document.getElementById('coastal-seasonal');
  root.innerHTML='<summary>Regional species & seasonal watch</summary><div class="coastal-notes">Loading source checks…</div>';
  const status=await loadCoastalStatus(catalog);
  root.querySelector('div').innerHTML=seasonalMarkup(catalog,coast,status);
  return status;
}
