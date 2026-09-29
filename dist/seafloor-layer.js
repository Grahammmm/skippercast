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
  habitatColor, habitatDetails, GRADE_STYLE, FIT_STYLE, UNKNOWN_COLOR,
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
  return `<div class="eyebrow">SEAFLOOR HABITAT · ${esc(getRegion().name)}</div><h2>${esc(d.title)}</h2>
    <div class="area-facts"><strong>${esc(d.depth)}</strong><span>Terrain grade ${esc(d.grade)}${view !== 'terrain' ? ' · colored by species fit' : ''}</span></div>
    <p><strong>${esc(d.depthNote)}</strong> Terrain grade describes seafloor relief from the original survey. Species fit (1–3) is a separate physical-habitat assessment, not a catch probability.</p>
    <ul class="small">${fits}</ul>
    <button id="seafloor-weather" class="primary">Conditions near this area ↗</button>
    <details class="detail-section"><summary>Survey source and screening</summary>
      <p>Source ${sources} · ${esc(String(d.source.year))} · ${esc(d.source.resolution)} cells · vertical datum ${esc(d.source.datum)}.</p>
      <p>${d.screened ? 'Whole polygon screened against current MPA, federal groundfish and security boundaries.' : 'Screening status unknown.'}${d.substrate ? ` Substrate ${d.substrate.sameSurvey === true ? 'comes from the same survey as depth' : 'source differs or is unknown'}; ${d.substrate.independent ? 'independently confirmed' : 'not independently confirmed'}.` : ''}</p>
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

export function initSeafloor(map, onSelect, { fetchImpl = globalThis.fetch } = {}) {
  const $ = (id) => document.getElementById(id);
  const toggle = $('layer-seafloor'), cellsToggle = $('layer-seafloor-cells'), viewSelect = $('seafloor-view'), status = $('seafloor-status');
  const box = $('seafloor-options');
  if (!toggle || !status) return null;
  const region = getRegion().id;
  for (const v of VIEWS) viewSelect.add(new Option(v.label, v.id));
  map.createPane('seafloorHabitat').style.zIndex = 421;   // under MPAs (440) and federal closures (438)
  const renderer = L.canvas({ pane: 'seafloorHabitat', padding: 0.3 });
  const habitatLayer = L.layerGroup(), cellsLayer = L.layerGroup();
  const legend = L.control({ position: 'bottomright' });
  legend.onAdd = () => L.DomUtil.create('div', 'seafloor-key');
  let archive = null, manifest = null, state = 'idle', loading = 0;
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
    if (!toggle.checked || state !== 'ready') return;
    const zoom = map.getZoom();
    habitatLayer.clearLayers(); cellsLayer.clearLayers();
    legend.getContainer().innerHTML = legendHTML(viewSelect.value);
    if (zoom < MIN_VIEW_ZOOM) { setStatus(`Zoom in to see seafloor habitat · ${manifest.layers?.habitat ?? 0} screened candidates in 3 assessed reaches`); return; }
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
    if (token !== loading || !toggle.checked) return;
    const habitat = dedupeById(parts.flatMap((p) => p.habitat));
    if (cellsToggle.checked) {
      for (const f of dedupeById(parts.flatMap((p) => p.cells))) {
        const assessed = Number(f.properties.tier) >= 1;
        L.geoJSON(f, { renderer, interactive: false, style: { color: assessed ? '#2f6f86' : '#8a949b', weight: 0.5, opacity: 0.5, fillOpacity: assessed ? 0.06 : 0, dashArray: assessed ? null : '2 3' } }).addTo(cellsLayer);
      }
    }
    for (const f of habitat) {
      const color = habitatColor(f.properties, viewSelect.value);
      L.geoJSON(f, { renderer, style: { color, weight: 1, fillColor: color, fillOpacity: 0.45 } })
        .bindTooltip('Habitat candidate, unverified')
        .on('click', () => {
          const c = centroid(f.geometry) || {};
          onSelect(detailsHTML(f.properties, viewSelect.value), { id: f.properties.id, name: 'Seafloor habitat candidate', ...c, geometry: f.geometry });
        })
        .addTo(habitatLayer);
    }
    setStatus(`${habitat.length} habitat candidate${habitat.length === 1 ? '' : 's'} in view · unverified; nominal depth · only 3 of 46 Central Coast reaches assessed`);
  }

  async function enable() {
    if (!toggle.checked) { show(false); setStatus('Off'); return; }
    setStatus('Checking seafloor publication…');
    const gate = await loadManifest(region, fetchImpl);
    state = gate.state;
    if (gate.state !== 'ready') { show(false); archive = null; tiles.clear(); setStatus(gate.reason); return; }
    manifest = gate.manifest;
    try {
      const pm = await loadPMTiles();
      if (!archive) archive = new pm.PMTiles(new URL(archiveURL(region), location.href).href);
      await archive.getHeader();
    } catch {
      state = 'unavailable'; archive = null; show(false); setStatus('Seafloor layer unavailable · try again later'); return;
    }
    show(true); draw();
  }

  // Only regions with a publication get the control; a 404 hides it.
  loadManifest(region, fetchImpl).then((gate) => {
    box.hidden = gate.published === false;
    setStatus(gate.state === 'ready' ? 'Off · turn on to show screened habitat candidates' : gate.reason);
  });

  toggle.addEventListener('change', enable);
  cellsToggle.addEventListener('change', draw);
  viewSelect.addEventListener('change', draw);
  map.on('moveend', draw);
  return { enable, draw, state: () => state };
}
