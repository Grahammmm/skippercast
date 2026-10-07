// First-run preference only. Port match positions are approximate and never exported.
import {navigate} from '../web/state.ts';
import {fishEntry} from '../web/fish-entry.ts';
import {readPreferences,validPreferences,forgetPreferenceHeader,HOME_PLACE_KEY} from '../packages/coast/src/coast3d/preferences.ts';
import {track} from '../web/telemetry.ts';
export {HOME_PLACE_KEY} from '../packages/coast/src/coast3d/preferences.ts';
export const HOME_PORT_KEY = 'skippercast-home-port-v1';
// Must equal FIRST_RUN_KEY in first-run.js (not imported: that module needs the region loaded).
export const FIRST_RUN_KEY = 'skippercast-first-run-v1';
let directory;

export function hasAreaLink(url) {
  const u = new URL(url);
  return ['region', 'coast', 'view', 'focus', 'spot', 'habitat', 'target', 'place', 'area', 'mode', 'species', 'hour', 'profile', 'day', 'layer', 'layers'].some(key => u.searchParams.has(key)) ||
    ['#map', '#forecast', '#export', '#guide', '#spot', '#account'].includes(u.hash);
}

export function portURL(href, port) {
  const url = new URL(href);
  for (const key of ['region', 'coast', 'view', 'focus', 'spot', 'habitat', 'place', 'area', 'target']) url.searchParams.delete(key);
  url.searchParams.set('region', port.region);
  url.searchParams.set('view', port.view.map((n, i) => i < 2 ? Number(n).toFixed(5) : n).join(','));
  url.hash = 'map';
  return url.href;
}

/**
 * The address for choosing `port` from `href`. A port in the region already
 * shown keeps the chosen target, so the forecast and species stay as they were.
 */
export function portChoiceURL(href, port) {
  const next = new URL(portURL(href, port)), target = new URL(href).searchParams.get('target');
  if (new URL(href).searchParams.has('target') && new URL(href).searchParams.get('region') === port.region) next.searchParams.set('target', target);
  return next.href;
}

export function closestPort(ports, latitude, longitude, maxNm = 75) {
  if (!Number.isFinite(latitude) || !Number.isFinite(longitude)) return null;
  const rad = Math.PI / 180;
  const ranked = ports.map(port => {
    const [lat, lon] = port.match, a = Math.sin((lat - latitude) * rad / 2) ** 2 +
      Math.cos(latitude * rad) * Math.cos(lat * rad) * Math.sin((lon - longitude) * rad / 2) ** 2;
    return {port, nm: 3440.065 * 2 * Math.asin(Math.min(1, Math.sqrt(a)))};
  }).sort((a, b) => a.nm - b.nm);
  return ranked[0]?.nm <= maxNm ? ranked[0].port : null;
}

async function loadPorts() {
  if (directory) return directory;
  const response = await fetch('data/home-ports.json', {signal: AbortSignal.timeout(10000)});
  if (!response.ok) throw Error('Port choices are unavailable');
  const data = await response.json();
  if (data.schema_version !== 1 || !Array.isArray(data.ports) || !data.ports.length) throw Error('Invalid port directory');
  directory = data.ports;
  return directory;
}

function savedPortId() { try { return localStorage.getItem(HOME_PORT_KEY); } catch { return null; } }
function savePort(id) { try { localStorage.setItem(HOME_PORT_KEY, id);localStorage.removeItem(HOME_PLACE_KEY); } catch { /* Session still navigates. */ } try{document.cookie=forgetPreferenceHeader(location.protocol==='https:');}catch{} }

/** Synthetic dependencies make migration testable without browser identity. */
export function resolveHome(ports,storage,cookies='') {
 const current=p=>{try{const mode=storage?.getItem('skippercast-profile-v1');if(['boat','shore','spear'].includes(mode))return {...p,mode};}catch{}return p;};
 try{const id=storage?.getItem(HOME_PORT_KEY),port=ports.find(item=>item.id===id);if(port)return {port};}catch{}
 try{const saved=JSON.parse(storage?.getItem(HOME_PLACE_KEY)??'null');if(validPreferences(saved))return {native:current(saved)};}catch{}
 const legacy=readPreferences(cookies);if(!legacy)return null;
 try{storage?.setItem(HOME_PLACE_KEY,JSON.stringify(legacy));if(!storage?.getItem('skippercast-profile-v1'))storage?.setItem('skippercast-profile-v1',legacy.mode);}catch{/* Visit still works if persistence is blocked. */}
 return {native:current(legacy)};
}
export function nativeHomeURL(href,p,storage) {
 let mode=p.mode;try{if(storage===undefined)storage=globalThis.localStorage;const stored=storage?.getItem('skippercast-profile-v1');if(['boat','shore','spear'].includes(stored))mode=stored;}catch{}
 const url=new URL(href);url.searchParams.set('place',p.place);if(!url.searchParams.has('profile'))url.searchParams.set('profile',mode);url.hash='map';return fishEntry(url.href).href;
}
export function forgetHome(storage,cookieJar,secure=false) {
 for(const key of [HOME_PORT_KEY,HOME_PLACE_KEY,'skippercast-profile-v1',FIRST_RUN_KEY])try{storage?.removeItem(key);}catch{}
 try{cookieJar.cookie=forgetPreferenceHeader(secure);}catch{}
}


// Choosing navigates in place while the app has not loaded a region, or when
// the port is in the region already shown; otherwise the page loads the region.
function chooser(ports, firstRun, onChosen = () => {}) {
  const previous = document.activeElement;
  const scrim = document.createElement('div');
  scrim.className = 'home-port-scrim';
  scrim.innerHTML = `<section class="home-port-card" role="dialog" aria-modal="true" aria-labelledby="home-port-title">
    <div class="home-port-kicker">${firstRun ? 'STEP 1 OF 3 · YOUR HARBOR' : 'SKIPPERCAST · CALIFORNIA'}</div>
    <h1 id="home-port-title">Where do you fish from?</h1>
    <p class="home-port-intro">Choose a launch area to open nearby fishing maps, species and the seven-day ocean forecast.</p>
    <label for="home-port-search">Find a home port</label>
    <input id="home-port-search" type="search" autocomplete="off" placeholder="Try Morro Bay, Ventura, San Diego…" />
    <div id="home-port-results" class="home-port-results" aria-live="polite"></div>
    <p id="home-port-feedback" class="home-port-feedback" role="status"></p>
    <div class="home-port-actions"><button type="button" id="home-port-near">⌖ Use my location</button><button type="button" id="home-port-explore">Explore the coast</button></div>
    <p class="home-port-fine">Your choice stays in this browser. Location matching is approximate; forecast map centers are not harbor entrances or navigation waypoints.</p>
    ${firstRun ? '' : '<button type="button" class="home-port-forget">Forget saved home</button><button type="button" class="home-port-close" aria-label="Close port chooser">×</button>'}
  </section>`;
  document.body.append(scrim);
  document.body.classList.add('choosing-home-port');
  const input = scrim.querySelector('#home-port-search');
  const results = scrim.querySelector('#home-port-results');
  const feedback = scrim.querySelector('#home-port-feedback');
  const featured = new Set(['morro-bay', 'san-diego', 'monterey', 'ventura', 'santa-cruz', 'bodega-bay']);
  let showAll = false;
  const render = (specific = null) => {
    results.replaceChildren();
    const query = input.value.trim().toLocaleLowerCase();
    let matches = specific ? [specific] : ports.filter(port =>
      port.name.toLocaleLowerCase().includes(query));
    if (!query && !showAll && !specific) matches = matches.filter(port => featured.has(port.id));
    if (!matches.length) {
      const empty = document.createElement('p'); empty.textContent = 'No matching port yet. Try a nearby harbor or explore the coast.'; results.append(empty);
    }
    for (const port of matches) {
      const button = document.createElement('button');
      button.type = 'button'; button.className = 'home-port-option';
      const name = document.createElement('strong'); name.textContent = port.name;
      const detail = document.createElement('span'); detail.textContent = `${port.status === 'active' ? 'Mapped area' : 'Regional preview'} · ${port.forecast_name}`;
      button.append(name, detail);
      button.addEventListener('click', () => { savePort(port.id); track('port_selected', {region: port.region, flush: true}); if (firstRun) { try { localStorage.setItem(FIRST_RUN_KEY, 'boat'); } catch { /* flow is optional */ } } if (navigate(portChoiceURL(location.href, port)) === 'in-place') { close(); onChosen(); } });
      results.append(button);
    }
    if (!query && !showAll && !specific) {
      const more = document.createElement('button'); more.type = 'button'; more.className = 'home-port-more';
      more.textContent = `See all ${ports.length} ports`;
      more.addEventListener('click', () => { showAll = true; render(); });
      results.append(more);
    }
  };
  input.addEventListener('input', () => { feedback.textContent = ''; render(); });
  scrim.querySelector('#home-port-explore').addEventListener('click', () => {
    const url = new URL(location.href); url.search = '?coast=central'; url.hash = 'map';
    if (navigate(url) === 'in-place') { close(); onChosen(); }
  });
  scrim.querySelector('#home-port-near').addEventListener('click', () => {
    feedback.textContent = 'Finding a nearby port…';
    if (!navigator.geolocation) { feedback.textContent = 'Location is unavailable. Search for a port instead.'; return; }
    navigator.geolocation.getCurrentPosition(position => {
      const port = closestPort(ports, position.coords.latitude, position.coords.longitude);
      if (!port) { feedback.textContent = 'No listed port is nearby. Search or explore the coast.'; return; }
      feedback.textContent = `Closest listed port: ${port.name}. Select it below to continue.`;
      render(port);
    }, () => { feedback.textContent = 'Location was unavailable. Search for a port instead.'; },
    {enableHighAccuracy: false, timeout: 10000, maximumAge: 300000});
  });
  function close() { scrim.remove(); document.body.classList.remove('choosing-home-port'); previous?.focus?.(); }
  scrim.querySelector('.home-port-close')?.addEventListener('click', close);
  scrim.querySelector('.home-port-forget')?.addEventListener('click',()=>{let storage=null;try{storage=localStorage;}catch{}forgetHome(storage,document,location.protocol==='https:');feedback.textContent='Saved home removed. This visit stays at the current selection.';buttonLabel(false);});
  scrim.addEventListener('keydown', event => {
    if (event.key === 'Escape' && !firstRun) { event.preventDefault(); close(); }
    if (event.key === 'Tab') {
      const focusable = [...scrim.querySelectorAll('button,input')].filter(el => !el.disabled);
      const i = focusable.indexOf(document.activeElement);
      if (event.shiftKey && i === 0) { event.preventDefault(); focusable.at(-1).focus(); }
      else if (!event.shiftKey && i === focusable.length - 1) { event.preventDefault(); focusable[0].focus(); }
    }
  });
  render(); input.focus();
}

function buttonLabel(saved){document.getElementById('home-port-button')?.setAttribute('aria-label',saved?'Change home port':'Choose home port');}
export async function initHomePort() {
  const button = document.getElementById('home-port-button');
  const saved = savedPortId();
  button.setAttribute('aria-label', saved ? 'Change home port' : 'Choose home port');
  button.addEventListener('click', async () => {
    try { chooser(await loadPorts(), false); }
    catch { navigate('/?coast=central#map'); }
  });
  if (hasAreaLink(location.href)) return true; // Shared links always win; never overwrite preference.
  try {
    const ports = await loadPorts();
    let storage=null,cookies='';try{storage=localStorage;}catch{}
    // Read only this origin's legacy home cookie, after shared links and current home have won.
    if(!ports.some(item=>item.id===saved))try{cookies=document.cookie;}catch{}
    const home=resolveHome(ports,storage,cookies),port=home?.port;
    if(home?.native)return navigate(nativeHomeURL(location.href,home.native,storage),{replace:true})==='in-place';
    // Nothing region-bound has loaded yet, so both paths continue in place.
    if (port) return navigate(portURL(location.href, port), {replace: true}) === 'in-place';
    return await new Promise(resolve => chooser(ports, true, () => resolve(true)));
  } catch {
    // Keep the atlas reachable even if the optional port directory fails.
    return true;
  }
}
