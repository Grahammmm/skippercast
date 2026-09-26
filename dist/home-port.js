// First-run preference only. Port match positions are approximate and never exported.
export const HOME_PORT_KEY = 'skippercast-home-port-v1';
let directory;

export function hasAreaLink(url) {
  const u = new URL(url);
  return ['region', 'coast', 'view', 'focus', 'spot', 'target'].some(key => u.searchParams.has(key)) ||
    ['#map', '#forecast', '#export', '#guide', '#spot'].includes(u.hash);
}

export function portURL(href, port) {
  const url = new URL(href);
  for (const key of ['region', 'coast', 'view', 'focus', 'spot', 'target']) url.searchParams.delete(key);
  url.searchParams.set('region', port.region);
  url.searchParams.set('view', port.view.map((n, i) => i < 2 ? Number(n).toFixed(5) : n).join(','));
  url.hash = 'map';
  return url.href;
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
function savePort(id) { try { localStorage.setItem(HOME_PORT_KEY, id); } catch { /* Session still navigates. */ } }

function chooser(ports, firstRun) {
  const previous = document.activeElement;
  const scrim = document.createElement('div');
  scrim.className = 'home-port-scrim';
  scrim.innerHTML = `<section class="home-port-card" role="dialog" aria-modal="true" aria-labelledby="home-port-title">
    <div class="home-port-kicker">SKIPPERCAST · CALIFORNIA</div>
    <h1 id="home-port-title">Where do you fish from?</h1>
    <p class="home-port-intro">Choose a launch area to open nearby fishing maps, species and the seven-day ocean forecast.</p>
    <label for="home-port-search">Find a home port</label>
    <input id="home-port-search" type="search" autocomplete="off" placeholder="Try Morro Bay, Ventura, San Diego…" />
    <div id="home-port-results" class="home-port-results" aria-live="polite"></div>
    <p id="home-port-feedback" class="home-port-feedback" role="status"></p>
    <div class="home-port-actions"><button type="button" id="home-port-near">⌖ Use my location</button><button type="button" id="home-port-explore">Explore the coast</button></div>
    <p class="home-port-fine">Your choice stays in this browser. Location matching is approximate; forecast map centers are not harbor entrances or navigation waypoints.</p>
    ${firstRun ? '' : '<button type="button" class="home-port-close" aria-label="Close port chooser">×</button>'}
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
      button.addEventListener('click', () => { savePort(port.id); location.assign(portURL(location.href, port)); });
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
    const url = new URL(location.href); url.search = '?coast=central'; url.hash = 'map'; location.assign(url.href);
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

export async function initHomePort() {
  const button = document.getElementById('home-port-button');
  const saved = savedPortId();
  button.setAttribute('aria-label', saved ? 'Change home port' : 'Choose home port');
  button.addEventListener('click', async () => {
    try { chooser(await loadPorts(), false); }
    catch { location.assign('/?coast=central#map'); }
  });
  if (hasAreaLink(location.href)) return true; // Shared links always win; never overwrite preference.
  try {
    const ports = await loadPorts();
    const port = ports.find(item => item.id === saved);
    if (port) { location.replace(portURL(location.href, port)); return false; }
    chooser(ports, true);
  } catch {
    // Keep the atlas reachable even if the optional port directory fails.
    return true;
  }
  return false;
}
