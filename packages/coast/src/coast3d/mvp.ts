import * as maplibregl from 'maplibre-gl';
import type {Map as CoastMap} from 'maplibre-gl';
import {DEFAULT_COAST_PALETTE as palette} from '../palette.ts';

/**
 * Local C3 contract; W11A producer: research/scripts/coast_mvp/coast_manifest.py (held only).
 * A release manifest (admitRelease, M9) is reviewed and rights-cleared: status 'reviewed', no publicationHeld key,
 * every source cleared with a catalog/sources.json catalogId. validateMvpManifest never admits one.
 */
export type MvpManifest = {
  schemaVersion: 1; region: string; synthetic: boolean;
  bounds: [number, number, number, number]; center: [number, number];
  zoom: number; tileZoom: number; tileSize: 256 | 512;
  terrain: string; contours: string; contourLayer: string;
  status?: 'review_required' | 'reviewed'; publicationHeld?: true; navigation?: string; limitations?: string[];
  provenance?: {c1Sha256: string; rightsSha256: string; c2Sha256: string; contoursSha256: string;
    assets: Record<string, string>};
  sources: {id: string; label: string; url: string | null; attribution: string;
    license: string; datum: string; resolutionM: number; permissionRequired: boolean;
    sha256?: string; termsUrl?: string; contributedCells?: number; datumNote?: string;
    csumbInvolved?: boolean; rightsStatus?: 'review_required' | 'needs_permission' | 'cleared'; catalogId?: string}[];
};
type MvpSource = MvpManifest['sources'][number];
type MapLib = Pick<typeof maplibregl, 'Map' | 'NavigationControl'>;
const finite = (x: unknown): x is number => typeof x === 'number' && Number.isFinite(x);
const text = (x: unknown): x is string => typeof x === 'string' && x.trim().length > 0;
const digest = (v: unknown): v is string => typeof v === 'string' && /^[a-f0-9]{64}$/.test(v);
const https = (v: unknown): boolean => {
  if (!text(v) || !v.startsWith('https://')) return false;
  try { const u = new URL(v); return u.protocol === 'https:' && !u.username && !u.password; }
  catch { return false; }
};
const notices = (m: MvpManifest): boolean => Array.isArray(m.limitations) && m.limitations.length > 0 && m.limitations.every(text);
/** No remote fetches, credentials or escaping the admitted asset directory. XYZ tokens are numeric tile coordinates. */
export function localAsset(path: string, base: URL): string {
  if (!text(path) || path.startsWith('/') || path.includes('\\') || /%(?:2f|5c|25)/i.test(path)) throw Error('Asset must be relative');
  const url = new URL(path, base);
  if (url.origin !== base.origin || !url.pathname.startsWith(base.pathname) || url.search || url.hash || url.username || url.password) throw Error('Asset outside local directory');
  // URL serialisation escapes braces; restore only the three numeric XYZ tokens.
  return url.href.replace(/%7B(z|x|y)%7D/gi, '{$1}');
}
/** Four digests and a non-empty map of local asset paths to digests; a bad path or digest throws. */
function provenance(p: MvpManifest['provenance']): boolean {
  if (!p || ![p.c1Sha256, p.rightsSha256, p.c2Sha256, p.contoursSha256].every(digest) ||
      !p.assets || typeof p.assets !== 'object' || Array.isArray(p.assets) || !Object.keys(p.assets).length) return false;
  for (const [path, hash] of Object.entries(p.assets)) {
    localAsset(path, new URL('http://localhost/manifest/'));
    if (!digest(hash)) throw Error('Invalid asset digest');
  }
  return true;
}
/** The shape both contracts share. `group` runs after the manifest checks; `held` checks each source before its attribution. */
function checkShape(m: MvpManifest, group: () => void, held: (s: MvpSource) => void): void {
  if (!m || m.schemaVersion !== 1 || !text(m.region) || typeof m.synthetic !== 'boolean' ||
      !Array.isArray(m.bounds) || m.bounds.length !== 4 || !m.bounds.every(finite) ||
      m.bounds[0] >= m.bounds[2] || m.bounds[1] >= m.bounds[3] ||
      m.bounds[0] < -180 || m.bounds[2] > 180 || m.bounds[1] < -85 || m.bounds[3] > 85 ||
      !Array.isArray(m.center) || m.center.length !== 2 || !m.center.every(finite) ||
      m.center[0] < m.bounds[0] || m.center[0] > m.bounds[2] || m.center[1] < m.bounds[1] || m.center[1] > m.bounds[3] ||
      !finite(m.zoom) || m.zoom < 0 || m.zoom > 20 || !Number.isInteger(m.tileZoom) || m.tileZoom < 0 || m.tileZoom > 20 ||
      ![256, 512].includes(m.tileSize) || !text(m.terrain) || !text(m.contours) || !text(m.contourLayer) ||
      !Array.isArray(m.sources) || !m.sources.length) throw Error('Invalid local coast manifest');
  group();
  const ids = new Set<string>();
  for (const s of m.sources) {
    held(s);
    if (!s || !text(s.id) || ids.has(s.id) || !text(s.label) || !text(s.attribution) || !text(s.license) ||
        !text(s.datum) || !finite(s.resolutionM) || s.resolutionM <= 0 || typeof s.permissionRequired !== 'boolean' ||
        (s.url !== null && (!text(s.url) || !/^https:\/\//.test(s.url)))) throw Error('Incomplete source attribution');
    if (s.url !== null) { const u = new URL(s.url); if (u.username || u.password) throw Error('Invalid source URL'); }
    ids.add(s.id);
  }
}
export function validateMvpManifest(value: unknown): MvpManifest {
  const m = value as MvpManifest;
  let group = false;
  checkShape(m, () => {
    group = ['status', 'publicationHeld', 'provenance'].some(key => key in m) ||
      m.sources.some(s => s && ['sha256', 'termsUrl', 'rightsStatus'].some(key => key in s));
    if (group && (m.status !== 'review_required' || m.publicationHeld !== true || !text(m.navigation) ||
        !notices(m) || !provenance(m.provenance))) throw Error('Incomplete held provenance');
  }, s => {
    if (!m.synthetic && s?.permissionRequired !== true) throw Error('Measured publication must stay held');
    if (group && (!s || !digest(s.sha256) || !https(s.termsUrl) ||
        !Number.isInteger(s.contributedCells) || s.contributedCells! <= 0 || !text(s.datumNote) ||
        typeof s.csumbInvolved !== 'boolean' || !['review_required', 'needs_permission'].includes(s.rightsStatus!) ||
        (s.csumbInvolved && s.rightsStatus !== 'needs_permission') || s.permissionRequired !== true)) throw Error('Incomplete held source');
  });
  return m;
}
/** The release contract (M9): the first refusal in a fixed order, before any tile request. It never throws. */
export function admitRelease(value: unknown): {manifest: MvpManifest} | {refused: string} {
  const m = value as MvpManifest;
  if (!m || typeof m !== 'object' || Array.isArray(m)) return {refused: 'invalid manifest'};
  if ('publicationHeld' in m) return {refused: 'publication held'};
  if (m.status !== 'reviewed') return {refused: 'not reviewed'};
  if (m.synthetic !== false) return {refused: 'synthetic fixture'};
  try { checkShape(m, () => {}, () => {}); } catch (error) { return {refused: 'invalid manifest: ' + (error as Error).message}; }
  if (m.terrain !== 'terrain/{z}/{x}/{y}.png' || m.contours !== 'vector/{z}/{x}/{y}.pbf') return {refused: 'invalid tile templates'};
  if (!text(m.navigation) || !m.navigation.includes('Not for navigation')) return {refused: 'missing navigation notice'};
  if (!notices(m)) return {refused: 'missing limitations'};
  let traced = false;
  try { traced = provenance(m.provenance); } catch { traced = false; }
  if (!traced) return {refused: 'incomplete provenance'};
  const held = m.sources.find(s => s.permissionRequired !== false || s.rightsStatus !== 'cleared' || s.csumbInvolved !== false ||
    !digest(s.sha256) || !https(s.termsUrl) || !Number.isInteger(s.contributedCells) || s.contributedCells! <= 0 ||
    !text(s.datumNote) || !text(s.catalogId));
  return held ? {refused: 'rights not cleared: ' + held.id} : {manifest: m};
}
export function previewManifestUrl(search: string, root: URL, fallback: string): string {
  const path = new URLSearchParams(search).get('manifest');
  if (path === null) return fallback;
  if (!path.endsWith('.json') || /[\u0000-\u0020\u007f]/.test(path) || /^[a-z][a-z0-9+.-]*:/i.test(path) ||
      path.split('/').some(part => /^(?:\.|%2e){2}$/i.test(part))) throw Error('Relative JSON manifest required');
  return localAsset(path, root);
}
export function sourceRightsText(source: MvpSource): string {
  const rights = source.rightsStatus === 'needs_permission' ? 'Permission required — CSUMB involved; publication held.' :
    source.rightsStatus === 'review_required' ? 'Rights review required — publication held.' : '';
  return [rights, source.datumNote].filter(Boolean).join(' ');
}
export function manifestHoldLines(manifest: MvpManifest): string[] {
  return [...(manifest.publicationHeld || !manifest.synthetic ? ['Publication held · review required'] : []),
    ...(manifest.navigation ? [manifest.navigation] : []), ...(manifest.limitations ?? [])];
}
/** The viewer's notice and sources panel, from text nodes only. A release has no hold line and no review note. */
export function mvpChrome(doc: Pick<Document, 'createElement' | 'createTextNode'>, manifest: MvpManifest, mode: 'preview' | 'release'): HTMLElement {
  const release = mode === 'release';
  const chrome = doc.createElement('section');
  chrome.className = 'coast-mvp-chrome';
  const banner = doc.createElement('strong');
  banner.textContent = 'Not for navigation · ' + (release ? 'Reviewed terrain · source detail varies' :
    manifest.synthetic ? 'SYNTHETIC FIXTURE — not measured bathymetry' : 'Preview — unreviewed terrain');
  banner.setAttribute('role', 'note');
  const panel = doc.createElement('details'); panel.open = true;
  const title = doc.createElement('summary'); title.textContent = manifest.region + ' · sources & rights'; panel.append(title);
  for (const s of manifest.sources) {
    const row = doc.createElement('p');
    row.textContent = `${s.label} — ${s.attribution}. ${s.license}. Datum: ${s.datum}. Source spacing: ${s.resolutionM.toFixed(1)} m. ${s.permissionRequired ? 'For-profit permission unresolved — publication held.' : ''}`;
    row.append(doc.createTextNode(' ' + sourceRightsText(s)));
    if (s.url) { const link = doc.createElement('a'); link.href = s.url; link.textContent = ' Source'; link.target = '_blank'; link.rel = 'noopener noreferrer'; row.append(link); }
    if (s.termsUrl) { const link = doc.createElement('a'); link.href = s.termsUrl; link.textContent = ' Terms'; link.target = '_blank'; link.rel = 'noopener noreferrer'; row.append(link); }
    panel.append(row);
  }
  for (const line of release ? [manifest.navigation!, ...manifest.limitations!] : manifestHoldLines(manifest)) {
    const hold = doc.createElement('p'); hold.textContent = line; panel.append(hold);
  }
  const note = doc.createElement('p');
  note.textContent = 'Relief ×3 (display only). Contours: feet below reference; source detail varies. No accuracy claim.' + (release ? '' : ' Review required.');
  panel.append(note);
  chrome.append(banner, panel);
  return chrome;
}
/** Opt-in viewer only: never changes the existing production coast route. */
export class CoastMvpViewer {
  readonly map: CoastMap;
  private chrome: HTMLElement;
  private constructor(host: HTMLElement, manifest: MvpManifest, base: URL, lib: MapLib = maplibregl, mode: 'preview' | 'release' = 'preview') {
    const terrain = localAsset(manifest.terrain, base), contours = localAsset(manifest.contours, base);
    // Inset exact XYZ edges to avoid admitting an adjacent tile at the boundary.
    const [w,s,e,n] = manifest.bounds;
    const tileBounds: [number,number,number,number] = [w+1e-9,s+1e-9,e-1e-9,n-1e-9];
    this.chrome = mvpChrome(document, manifest, mode); host.append(this.chrome);
    try {
      this.map = new lib.Map({container: host, center: manifest.center, zoom: manifest.zoom, pitch: 45, bearing: -25,
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
      this.map.addControl(new lib.NavigationControl());
    } catch (error) { this.chrome.remove(); throw error; }
  }
  static async load(host: HTMLElement, manifestUrl: string): Promise<CoastMvpViewer> {
    const url = new URL(manifestUrl, location.href);
    if (url.origin !== location.origin || url.username || url.password) throw Error('Local manifest required');
    const response = await fetch(url, {redirect: 'error', signal: AbortSignal.timeout(20000)});
    if (!response.ok) throw Error('Local manifest unavailable');
    return new CoastMvpViewer(host, validateMvpManifest(await response.json()), new URL('./', url));
  }
  /** A release manifest (M9): the viewer is built, so tiles are requested, only after admitRelease admits it. */
  static async loadRelease(host: HTMLElement, manifestUrl: string, deps: {fetch?: typeof fetch; lib?: MapLib} = {}): Promise<{viewer: CoastMvpViewer} | {refused: string}> {
    const url = new URL(manifestUrl, location.href);
    if (url.origin !== location.origin || url.username || url.password) throw Error('Local manifest required');
    let value: unknown;
    try {
      const response = await (deps.fetch ?? fetch)(url, {redirect: 'error', signal: AbortSignal.timeout(20000)});
      if (!response.ok) return {refused: 'manifest unavailable'};
      value = await response.json();
    } catch { return {refused: 'manifest unavailable'}; }
    const admitted = admitRelease(value);
    if ('refused' in admitted) return admitted;
    return {viewer: new CoastMvpViewer(host, admitted.manifest, new URL('./', url), deps.lib ?? maplibregl, 'release')};
  }
  destroy(): void { this.map.remove(); this.chrome.remove(); }
}
