// Seafloor habitat layer (#22): screened original-survey habitat candidates
// from the regional PMTiles archive, drawn on the Leaflet map.
//
// Fail-closed: the layer draws only while the publication manifest is ready
// and unexpired (seafloor-data.js). Coverage cells and habitat candidates are
// separate toggles; terrain grade and species fit are separate views. The
// layer sits in a pane below the MPA boundaries so they always stay on top.
import { getRegion } from './region.js';
import { esc } from './marine-charts.js';
import {
  loadManifest, archiveURL, decodeTile, tileFeatures, dedupeById, tilesForBounds,
  habitatColor, habitatDetails, GRADE_STYLE, FIT_STYLE, UNKNOWN_COLOR, SEARCH_COLOR, CLASSIFIED_COLOR,
} from './seafloor-data.js';

export const TILE_ZOOM = 12;       // one fixed data zoom: full detail for Morro Bay reaches, few requests
export const MIN_VIEW_ZOOM = 10;   // below this, the layer asks to zoom in instead of drawing
const PMTILES_SRC = 'vendor/pmtiles-4.5.0/pmtiles.js';
const PMTILES_SRI = 'sha256-yvmBvEb2Mn7n5l1dyWTYnTimn2DtyivUxciQwhtVTGw=';

export const VIEWS = [
  { id: 'terrain', label: 'Terrain grade (A/B/C)' },
  { id: 'fit_lingcod', label: 'Lingcod physical fit (1–3)' },
  { id: 'fit_rockfish_reef', label: 'Rockfish reef physical fit (1–3)' },
];

/** Legend text for the chosen view; terrain and fit never share a key. */
export function legendHTML(view) {
  const rows = view === 'terrain'
    ? Object.values(GRADE_STYLE).map((s) => [s.color, s.label])
    : Object.values(FIT_STYLE).map((s) => [s.color, s.label]);
  rows.push([UNKNOWN_COLOR, 'Unknown']);
  rows.push([SEARCH_COLOR, 'Rough-bottom search area · unranked']);
  rows.push([CLASSIFIED_COLOR, 'Interpreted rock habitat · unranked']);
  const title = view === 'terrain' ? 'Terrain grade' : 'Physical habitat fit, not catch probability';
  return `<strong>${esc(title)}</strong>${rows.map(([c, t]) => `<span><i style="background:${c}"></i>${esc(t)}</span>`).join('')}`;
}

/** Details panel HTML for one habitat candidate. */
export function detailsHTML(properties, view = 'terrain') {
  const d = habitatDetails(properties);
  const fits = d.fits.length
    ? d.fits.map((f) => `<li>${esc(f.name)}: ${f.value === 'unknown' ? 'unknown' : `${f.value} of 3`}</li>`).join('')
    : '<li>No species fit published</li>';
  const sources = d.source.ids.length ? d.source.ids.map(esc).join(', ') : 'unknown';
  const assessment = d.classifiedArea
    ? 'Publisher interpretation · unranked habitat area'
    : d.searchArea
    ? 'Limited confidence · unranked search area'
    : `Terrain grade ${esc(d.grade)}${view !== 'terrain' ? ' · colored by species fit' : ''}`;
  const explanation = d.classifiedBedrock
    ? 'The original publisher interprets exposed bedrock within this outline. Rugosity, boulder size, terrain grade and species fit are unknown. The outline follows interpreted geology and a nominal depth mask; its edges can reflect the processed survey window rather than a reef edge. It does not establish fish presence or a precise fishing position. Explore with your sounder.'
    : d.classifiedArea
    ? 'The original publisher interprets rugose rock and boulders within this outline. Paired native survey depth supports the nominal band. Terrain grade and species fit are unknown; this interpretation does not establish fish presence or a precise fishing position. Explore with your sounder.'
    : d.searchArea
    ? 'The survey identifies a rough-bottom patch, but surrounding measurements are insufficient for a terrain grade. Explore this outline with your sounder; it does not identify an individual pile or precise fishing position.'
    : 'Terrain grade describes seafloor relief from the original survey. Species fit (1–3) is a separate physical-habitat assessment, not a catch probability.';
  const targets = d.searchArea
    ? `<p class="small">Potential habitat for ${d.searchTargets.map(t => esc(t.replace(/-/g, ' '))).join(', ')}. No species-fit rank is assigned.</p>`
    : `<ul class="small">${fits}</ul>`;
  return `<div class="eyebrow">SEAFLOOR HABITAT · ${esc(getRegion().name)}</div><h2>${esc(d.title)}</h2>
    <div class="area-facts"><strong>${esc(d.depth)}</strong><span>${assessment}</span></div>
    <p><strong>${esc(d.depthNote)}</strong> ${explanation}</p>
    ${targets}
    <button id="seafloor-weather" class="primary">Conditions near this area ↗</button>
    <details class="detail-section"><summary>Survey source and screening</summary>
      <p>Source ${sources} · ${esc(String(d.source.year))} · ${esc(d.source.resolution)} cells · vertical datum ${esc(d.source.datum)}.</p>
      <p>${d.screened ? 'Whole polygon screened against current MPA, federal groundfish and security boundaries.' : 'Screening status unknown.'}${d.substrate ? ` Substrate ${d.substrate.sameSurvey === true ? 'comes from the same survey as depth' : 'source differs or is unknown'}; ${d.substrate.independent ? 'independently confirmed' : 'not independently confirmed'}.` : ''}</p>
      ${d.rights.map(r => `<p class="small"><strong>Source credit</strong>: ${esc(r.credit)} ${esc(r.notice)}${r.policyURL ? ` <a href="${esc(r.policyURL)}" target="_blank" rel="noopener noreferrer">Publisher terms ↗</a>` : ''}</p>`).join('')}
      <p>${esc(d.displayNote)} ${esc(d.notice)}</p>
    </details>`;
}

function centroid(geometry) {
  let x = 0, y = 0, n = 0;
  for (const poly of geometry.coordinates) for (const [lng, lat] of poly[0]) { x += lng; y += lat; n++; }
  return n ? { longitude: x / n, latitude: y / n } : null;
}

let pmtilesLoad;
function loadPMTiles() {
  if (globalThis.pmtiles) return Promise.resolve(globalThis.pmtiles);
  pmtilesLoad ||= new Promise((resolve, reject) => {
    const s = document.createElement('script');
    s.src = PMTILES_SRC; s.integrity = PMTILES_SRI; s.crossOrigin = 'anonymous';
    s.onload = () => (globalThis.pmtiles ? resolve(globalThis.pmtiles) : reject(Error('PMTiles reader missing')));
    s.onerror = () => { pmtilesLoad = null; reject(Error('PMTiles reader failed to load')); };
    document.head.append(s);
  });
  return pmtilesLoad;
}

export function habitatDefaults(target) {
  return { enabled: ['reef', 'rockfish', 'lingcod'].includes(target),
    view: target === 'lingcod' ? 'fit_lingcod' : 'fit_rockfish_reef' };
}

export function publishedReachCount(manifest) {
  return Object.keys(manifest?.reach_inputs || {}).length;
}

export function initSeafloor(map, onSelect, { fetchImpl = globalThis.fetch,
  setTimeoutImpl = globalThis.setTimeout, clearTimeoutImpl = globalThis.clearTimeout,
  now = Date.now } = {}) {
  const $ = (id) => document.getElementById(id);
  const toggle = $('layer-seafloor'), cellsToggle = $('layer-seafloor-cells'), viewSelect = $('seafloor-view'), status = $('seafloor-status');
  const box = $('seafloor-options');
  if (!toggle || !status) return null;
  const region = getRegion().id, species = $('species-select');
  let explicitChoice = null, enabling = 0;
  for (const v of VIEWS) viewSelect.add(new Option(v.label, v.id));
  map.createPane('seafloorHabitat').style.zIndex = 421;   // under MPAs (440) and federal closures (438)
  const renderer = L.canvas({ pane: 'seafloorHabitat', padding: 0.3 });
  const habitatLayer = L.layerGroup(), cellsLayer = L.layerGroup();
  const legend = L.control({ position: 'bottomright' });
  legend.onAdd = () => L.DomUtil.create('div', 'seafloor-key');
  let archive = null, manifest = null, state = 'idle', loading = 0;
  let timer = null, retryAttempt = 0, disposed = false;
  const retryDelays = [30000, 60000, 120000, 240000, 300000];
  const cancelTimer = () => { if (timer !== null) clearTimeoutImpl(timer); timer = null; };
  function schedule(delay) {
    if (disposed) return;
    cancelTimer();
    timer = setTimeoutImpl(() => { timer = null; enable({ retry: true }); }, delay);
    timer?.unref?.(); // Node-only fixture handles must not keep the test process alive.
  }
  function currentPublication() {
    if (state !== 'ready') return false;
    if (Date.parse(manifest?.expires_at) > now()) return true;
    state = 'expired'; ++loading; archive = null; tiles.clear(); show(false);
    setStatus('Seafloor screening has expired and is being refreshed');
    return false;
  }
  const tiles = new Map();   // "z/x/y" -> {habitat, cells} | Promise

  const setStatus = (text) => { status.textContent = text; };
  const show = (on) => { if (on) { habitatLayer.addTo(map); cellsLayer.addTo(map); legend.addTo(map); } else { habitatLayer.remove(); cellsLayer.remove(); legend.remove(); } };

  async function tile(z, x, y) {
    const key = `${z}/${x}/${y}`;
    if (!tiles.has(key)) tiles.set(key, archive.getZxy(z, x, y).then((t) => {
      if (!t) return { habitat: [], cells: [] };
      const decoded = decodeTile(new Uint8Array(t.data));
      return { habitat: tileFeatures(decoded, 'habitat', z, x, y), cells: tileFeatures(decoded, 'cells', z, x, y) };
    }).catch((error) => { tiles.delete(key); throw error; }));
    return tiles.get(key);
  }

  async function draw() {
    if (disposed || !toggle.checked || !currentPublication()) return;
    const zoom = map.getZoom();
    habitatLayer.clearLayers(); cellsLayer.clearLayers();
    legend.getContainer().innerHTML = legendHTML(viewSelect.value);
    if (zoom < MIN_VIEW_ZOOM) { setStatus(`Zoom in to see seafloor habitat · ${manifest.layers?.habitat ?? 0} screened candidates across ${publishedReachCount(manifest)} published reach inputs`); return; }
    const b = map.getBounds(), header = await archive.getHeader();
    const view = [Math.max(b.getWest(), header.minLon), Math.max(b.getSouth(), header.minLat), Math.min(b.getEast(), header.maxLon), Math.min(b.getNorth(), header.maxLat)];
    if (view[0] >= view[2] || view[1] >= view[3]) { setStatus('No published seafloor survey in this view · the rest of the coast is not assessed'); return; }
    const wanted = tilesForBounds(view, Math.min(TILE_ZOOM, header.maxZoom));
    if (wanted.length > 64) { setStatus('Zoom in to load seafloor habitat'); return; }
    const token = ++loading;
    setStatus('Loading seafloor habitat…');
    let parts;
    try { parts = await Promise.all(wanted.map(([z, x, y]) => tile(z, x, y))); }
    catch { if (token === loading) setStatus('Seafloor habitat could not load · try again'); return; }
    if (token !== loading || !toggle.checked || !currentPublication()) return;
    const habitat = dedupeById(parts.flatMap((p) => p.habitat));
    if (cellsToggle.checked) {
      for (const f of dedupeById(parts.flatMap((p) => p.cells))) {
        const assessed = Number(f.properties.tier) >= 1;
        L.geoJSON(f, { renderer, interactive: false, style: { color: assessed ? '#2f6f86' : '#8a949b', weight: 0.5, opacity: 0.5, fillOpacity: assessed ? 0.06 : 0, dashArray: assessed ? null : '2 3' } }).addTo(cellsLayer);
      }
    }
    for (const f of habitat) {
      const color = habitatColor(f.properties, viewSelect.value);
      const search = f.properties.status === 'search-area';
      const classified = f.properties.status === 'classified-area';
      const unranked = search || classified;
      L.geoJSON(f, { renderer, style: { color, weight: unranked ? 1.5 : 1, dashArray: unranked ? '5 4' : null, fillColor: color, fillOpacity: unranked ? 0.15 : 0.45 } })
        .bindTooltip(classified ? 'Interpreted rugose-rock area · unranked' : search ? 'Rough-bottom search area · unranked' : 'Habitat candidate, unverified')
        .on('click', () => {
          const c = centroid(f.geometry) || {};
          onSelect(detailsHTML(f.properties, viewSelect.value), { id: f.properties.id, name: classified ? 'Interpreted rugose-rock area' : search ? 'Rough-bottom search area' : 'Seafloor habitat candidate', ...c, geometry: f.geometry });
        })
        .addTo(habitatLayer);
    }
    const searches = habitat.filter(f => f.properties.status === 'search-area').length;
    const classified = habitat.filter(f => f.properties.status === 'classified-area').length;
    const ranked = habitat.length - searches - classified;
    setStatus(`${ranked} habitat candidate${ranked === 1 ? '' : 's'} in view${searches ? ` · ${searches} unranked search areas` : ''}${classified ? ` · ${classified} unranked interpreted areas` : ''} · unverified; nominal depth · ${publishedReachCount(manifest)} published reach inputs in this region`);
  }

  async function enable({ retry = false } = {}) {
    if (disposed) return;
    cancelTimer();
    // A pending refresh must never leave an old publication visible past expiry.
    state = 'checking'; show(false);
    if (!retry) retryAttempt = 0;
    const request = ++enabling; ++loading;
    if (!toggle.checked) { show(false); setStatus('Off'); return; }
    setStatus('Checking seafloor publication…');
    const gate = await loadManifest(region, fetchImpl, now());
    if (request !== enabling || !toggle.checked) return;
    box.hidden = gate.published === false;
    state = gate.state;
    if (gate.state !== 'ready') {
      show(false); archive = null; tiles.clear(); setStatus(gate.reason);
      if (gate.published !== false && ['updating', 'unavailable'].includes(gate.state)) {
        const delay = retryDelays[retryAttempt++];
        if (delay) { setStatus(`${gate.reason} · retrying in ${delay / 1000}s`); schedule(delay); }
        else setStatus(`${gate.reason} · toggle layer to retry`);
      }
      return;
    }
    retryAttempt = 0;
    if (manifest?.archive_sha256 !== gate.manifest.archive_sha256) { archive = null; tiles.clear(); }
    manifest = gate.manifest;
    try {
      const pm = await loadPMTiles();
      if (!archive) archive = new pm.PMTiles(new URL(archiveURL(region), location.href).href);
      await archive.getHeader();
      if (request !== enabling || !toggle.checked) return;
    } catch {
      if (request !== enabling || !toggle.checked) return;
      state = 'unavailable'; archive = null; show(false); setStatus('Seafloor layer unavailable · try again later'); return;
    }
    if (!currentPublication()) return;
    // Hide/recheck when the reviewed publication expires, even without map movement.
    schedule(Math.min(Date.parse(manifest.expires_at) - now(), 2147483647));
    show(true); draw();
  }

  // Only regions with a publication get the control; a 404 hides it.
  loadManifest(region, fetchImpl).then((gate) => {
    if (disposed) return;
    box.hidden = gate.published === false;
    if (!toggle.checked) setStatus(gate.state === 'ready' ? 'Off · turn on to show screened habitat candidates' : gate.reason);
  });

  function toggleChanged() { if (disposed) return; explicitChoice = toggle.checked; enable(); }
  toggle.addEventListener('change', toggleChanged);
  function targetChanged() {
    if (disposed) return;
    const defaults = habitatDefaults(species?.value);
    toggle.checked = explicitChoice ?? defaults.enabled;
    if (defaults.enabled) viewSelect.value = defaults.view;
    enable();
  }
  species?.addEventListener('change', targetChanged);
  targetChanged();
  cellsToggle.addEventListener('change', draw);
  viewSelect.addEventListener('change', draw);
  map.on('moveend', draw);
  function dispose() {
    if (disposed) return;
    disposed = true; cancelTimer(); ++enabling; ++loading; state = 'disposed'; show(false);
    archive = null; tiles.clear();
    toggle.removeEventListener?.('change', toggleChanged);
    species?.removeEventListener?.('change', targetChanged);
    cellsToggle.removeEventListener?.('change', draw);
    viewSelect.removeEventListener?.('change', draw);
    map.off?.('moveend', draw); map.off?.('unload', dispose);
  }
  map.on('unload', dispose);
  return { enable, draw, dispose, state: () => state };
}
