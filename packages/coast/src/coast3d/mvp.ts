import * as maplibregl from 'maplibre-gl';
import type {Map as CoastMap} from 'maplibre-gl';
import {DEFAULT_COAST_PALETTE as palette} from '../palette.ts';
import {MASK_PROTOCOL, registerMaskProtocol} from './mvp-mask.ts';

/** Local C3 interchange contract. C2/C5 adapters are deliberately not assumed. */
export type MvpManifest = {
  schemaVersion: 1; region: string; synthetic: boolean;
  bounds: [number, number, number, number]; center: [number, number];
  zoom: number; tileZoom: number; tileSize: 256 | 512;
  terrain: string; contours: string; contourLayer: string;
  sources: {id: string; label: string; url: string | null; attribution: string;
    license: string; datum: string; resolutionM: number; permissionRequired: boolean}[];
};
const finite = (x: unknown): x is number => typeof x === 'number' && Number.isFinite(x);
const text = (x: unknown): x is string => typeof x === 'string' && x.trim().length > 0;
/** No remote fetches, credentials or escaping the admitted asset directory. XYZ tokens are numeric tile coordinates. */
export function localAsset(path: string, base: URL): string {
  if (!text(path) || path.startsWith('/') || path.includes('\\') || /%(?:2f|5c|25)/i.test(path)) throw Error('Asset must be relative');
  const url = new URL(path, base);
  if (url.origin !== base.origin || !url.pathname.startsWith(base.pathname) || url.search || url.hash || url.username || url.password) throw Error('Asset outside local directory');
  // URL serialisation escapes braces; restore only the three numeric XYZ tokens.
  return url.href.replace(/%7B(z|x|y)%7D/gi, '{$1}');
}
export function validateMvpManifest(value: unknown): MvpManifest {
  const m = value as MvpManifest;
  if (!m || m.schemaVersion !== 1 || !text(m.region) || typeof m.synthetic !== 'boolean' ||
      !Array.isArray(m.bounds) || m.bounds.length !== 4 || !m.bounds.every(finite) ||
      m.bounds[0] >= m.bounds[2] || m.bounds[1] >= m.bounds[3] ||
      m.bounds[0] < -180 || m.bounds[2] > 180 || m.bounds[1] < -85 || m.bounds[3] > 85 ||
      !Array.isArray(m.center) || m.center.length !== 2 || !m.center.every(finite) ||
      m.center[0] < m.bounds[0] || m.center[0] > m.bounds[2] || m.center[1] < m.bounds[1] || m.center[1] > m.bounds[3] ||
      !finite(m.zoom) || m.zoom < 0 || m.zoom > 20 || !Number.isInteger(m.tileZoom) || m.tileZoom < 0 || m.tileZoom > 20 ||
      ![256, 512].includes(m.tileSize) || !text(m.terrain) || !text(m.contours) || !text(m.contourLayer) ||
      !Array.isArray(m.sources) || !m.sources.length) throw Error('Invalid local coast manifest');
  const ids = new Set<string>();
  for (const s of m.sources) {
    if (!s || !text(s.id) || ids.has(s.id) || !text(s.label) || !text(s.attribution) || !text(s.license) ||
        !text(s.datum) || !finite(s.resolutionM) || s.resolutionM <= 0 || typeof s.permissionRequired !== 'boolean' ||
        (s.url !== null && (!text(s.url) || !/^https:\/\//.test(s.url)))) throw Error('Incomplete source attribution');
    if (s.url !== null) { const u = new URL(s.url); if (u.username || u.password) throw Error('Invalid source URL'); }
    ids.add(s.id);
  }
  return m;
}
/** Opt-in viewer only: never changes the existing production coast route. */
export class CoastMvpViewer {
  readonly map: CoastMap;
  private chrome: HTMLElement;
  private constructor(host: HTMLElement, manifest: MvpManifest, base: URL) {
    const terrain = MASK_PROTOCOL + '://' + localAsset(manifest.terrain, base), contours = localAsset(manifest.contours, base);
    // Inset exact XYZ edges to avoid admitting an adjacent tile at the boundary.
    const [w,s,e,n] = manifest.bounds;
    const tileBounds: [number,number,number,number] = [w+1e-9,s+1e-9,e-1e-9,n-1e-9];
    this.chrome = document.createElement('section');
    this.chrome.className = 'coast-mvp-chrome';
    const banner = document.createElement('strong');
    banner.textContent = 'Not for navigation · ' + (manifest.synthetic ? 'SYNTHETIC FIXTURE — not measured bathymetry' : 'Preview — unreviewed terrain');
    banner.setAttribute('role', 'note');
    const panel = document.createElement('details'); panel.open = true;
    const title = document.createElement('summary'); title.textContent = manifest.region + ' · sources & rights'; panel.append(title);
    for (const s of manifest.sources) {
      const row = document.createElement('p');
      row.textContent = `${s.label} — ${s.attribution}. ${s.license}. Datum: ${s.datum}. Source spacing: ${s.resolutionM.toFixed(1)} m. ${s.permissionRequired ? 'For-profit permission unresolved — publication held.' : ''}`;
      if (s.url) { const link = document.createElement('a'); link.href = s.url; link.textContent = ' Source'; link.target = '_blank'; link.rel = 'noopener noreferrer'; row.append(link); }
      panel.append(row);
    }
    const note = document.createElement('p'); note.textContent = 'Relief ×3 (display only). Unsupported (no-data) cells are never read as depth; they are filled flat from the nearest supported cell. Contours: feet below reference; source detail varies. No accuracy claim. Review required.'; panel.append(note);
    this.chrome.append(banner, panel); host.append(this.chrome);
    try {
      this.map = new maplibregl.Map({container: host, center: manifest.center, zoom: manifest.zoom, pitch: 45, bearing: -25,
        maxBounds: manifest.bounds, maxZoom: 18, attributionControl: false,
        style: {version: 8, sources: {
          'mvp-terrain': {type: 'raster-dem', tiles: [terrain], tileSize: manifest.tileSize, minzoom: manifest.tileZoom, maxzoom: manifest.tileZoom, bounds: tileBounds, encoding: 'mapbox'},
          'mvp-contours': {type: 'vector', tiles: [contours], minzoom: manifest.tileZoom, maxzoom: manifest.tileZoom, bounds: tileBounds}
        }, terrain: {source: 'mvp-terrain', exaggeration: 3}, layers: [
          {id: 'background', type: 'background', paint: {'background-color': palette.depthDeep}},
          {id: 'relief', type: 'hillshade', source: 'mvp-terrain', paint: {'hillshade-shadow-color': palette.depthDeep, 'hillshade-highlight-color': palette.depthShallow, 'hillshade-accent-color': palette.depthChannel, 'hillshade-exaggeration': .8}},
          {id: 'contours', type: 'line', source: 'mvp-contours', 'source-layer': manifest.contourLayer,
            paint: {'line-color': palette.sky, 'line-opacity': .8, 'line-width': ['case', ['==', ['%', ['get', 'depth_ft'], 100], 0], 2, .8]}}
        ]}});
      this.map.addControl(new maplibregl.NavigationControl());
    } catch (error) { this.chrome.remove(); throw error; }
  }
  private static maskReady = false;
  static async load(host: HTMLElement, manifestUrl: string): Promise<CoastMvpViewer> {
    if (!CoastMvpViewer.maskReady) { await registerMaskProtocol(maplibregl.addProtocol, location.origin); CoastMvpViewer.maskReady = true; }
    const url = new URL(manifestUrl, location.href);
    if (url.origin !== location.origin || url.username || url.password) throw Error('Local manifest required');
    const response = await fetch(url, {redirect: 'error', signal: AbortSignal.timeout(20000)});
    if (!response.ok) throw Error('Local manifest unavailable');
    return new CoastMvpViewer(host, validateMvpManifest(await response.json()), new URL('./', url));
  }
  destroy(): void { this.map.remove(); this.chrome.remove(); }
}
