import * as maplibregl from 'maplibre-gl';
import type {Map as CoastMap} from 'maplibre-gl';
import {DEFAULT_COAST_PALETTE as palette} from '../palette.ts';

/** Local C3 interchange contract. C5 rights inventories enter only via adaptC5Rights (mvp-rights.ts). */
export type MvpSourceRights = {sha256: string; termsUrl: string; contributedCells: number;
  csumbInvolved: boolean; status: 'needs_permission' | 'review_required'};
export type MvpSource = {id: string; label: string; url: string | null; attribution: string;
  license: string; datum: string | null; resolutionM: number | null; permissionRequired: boolean;
  rights?: MvpSourceRights};
export type MvpManifest = {
  schemaVersion: 1; region: string; synthetic: boolean;
  bounds: [number, number, number, number]; center: [number, number];
  zoom: number; tileZoom: number; tileSize: 256 | 512;
  terrain: string; contours: string; contourLayer: string;
  sources: MvpSource[];
  /** Tile-export datum/spacing, used when per-source values are not in the rights inventory. */
  mosaic?: {datum: string; resolutionM: number};
  rightsInventory?: {schemaVersion: 1; sha256: string; page: string; status: 'review_required'; caveats: string[]};
};
// Notices follow the reviewed C5 rights export wording. None of them grants permission.
export const NOT_FOR_NAVIGATION = 'Not for navigation or any purpose involving safety at sea. Research preview only; not an official nautical chart.';
export const RIGHTS_REVIEW = 'Rights status: review_required. Recorded terms are not legal advice, permission to publish or commercial-use clearance.';
export const NO_ENDORSEMENT = 'Use does not imply endorsement by any source, GEBCO, the IHO or the IOC. Do not misrepresent the original data or these derivatives.';
export const CSUMB_NOTICE = 'needs_permission: CSUMB Seafloor Mapping Lab policy permits non-profit use with acknowledgment. ' +
  'For-profit permission is unresolved; owner/counsel must resolve it. A public-domain or CC0 release label does not resolve this question. ' +
  'Commercial use and publication are held.';
export const GEBCO_CAVEAT = 'GEBCO: the recorded version-specific citation is retained verbatim; GEBCO, the IHO and the IOC do not endorse this preview.';
/** Same backstop as C5: explicit CSUMB references keep the hold even if csumb_involved is wrongly false. */
export function mentionsCsumb(fields: string[]): boolean {
  const e = fields.join(' ').toLowerCase();
  return e.includes('csumb') || e.includes('seafloor mapping lab') ||
    /\bcalifornia\s+state\s+university(?:\s*,\s*|\s+)monterey\s+bay\b/.test(e);
}
export const mentionsGebco = (fields: string[]): boolean => fields.join(' ').toLowerCase().includes('gebco');
const HEX64 = /^[0-9a-f]{64}$/;
const finite = (x: unknown): x is number => typeof x === 'number' && Number.isFinite(x);
const text = (x: unknown): x is string => typeof x === 'string' && x.trim().length > 0;
const evidence = (s: MvpSource) => [s.id, s.label, s.url ?? '', s.license, s.rights?.termsUrl ?? '', s.attribution];
/** No remote fetches, credentials or escaping the admitted asset directory. XYZ tokens are numeric tile coordinates. */
export function localAsset(path: string, base: URL): string {
  if (!text(path) || path.startsWith('/') || path.includes('\\') || /%(?:2f|5c|25)/i.test(path)) throw Error('Asset must be relative');
  const url = new URL(path, base);
  if (url.origin !== base.origin || !url.pathname.startsWith(base.pathname) || url.search || url.hash || url.username || url.password) throw Error('Asset outside local directory');
  // URL serialisation escapes braces; restore only the three numeric XYZ tokens.
  return url.href.replace(/%7B(z|x|y)%7D/gi, '{$1}');
}
/**
 * Pure, offline form of localAsset: true iff the viewer would load `path` as a file inside its manifest directory.
 * Stricter than localAsset on purpose: the raw token must be a plain relative path of `[A-Za-z0-9._-]` segments
 * joined by `/`. That excludes schemes (`https:`, `file:`), `?`, `#`, `%`, backslashes and every whitespace or
 * control character the URL parser would strip or rewrite, so the URL path and the on-disk file name are identical
 * and the placeholder base below can never be matched by an absolute input.
 */
const PLAIN_RELATIVE = /^(?!\/)[A-Za-z0-9._-]+(?:\/[A-Za-z0-9._-]+)*$/;
export function isLocalAssetPath(path: unknown): path is string {
  if (typeof path !== 'string' || !PLAIN_RELATIVE.test(path)) return false;
  // Placeholder origin/directory only; nothing is fetched. Same function as the viewer, so the rules cannot drift.
  const base = new URL('https://coast-mvp.invalid/assets/manifest/');
  try { return !localAsset(path, base).endsWith('/'); } catch { return false; }
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
  if (m.mosaic !== undefined && (!m.mosaic || !text(m.mosaic.datum) || !finite(m.mosaic.resolutionM) || m.mosaic.resolutionM <= 0)) {
    throw Error('Invalid mosaic datum/spacing');
  }
  const ids = new Set<string>();
  for (const s of m.sources) {
    if (!s || !text(s.id) || ids.has(s.id) || !text(s.label) || !text(s.attribution) || !text(s.license) ||
        !(text(s.datum) || (s.datum === null && m.mosaic)) ||
        !((finite(s.resolutionM) && s.resolutionM > 0) || (s.resolutionM === null && m.mosaic)) ||
        typeof s.permissionRequired !== 'boolean' ||
        (s.url !== null && (!text(s.url) || !/^https:\/\//.test(s.url)))) throw Error('Incomplete source attribution');
    if (s.url !== null) { const u = new URL(s.url); if (u.username || u.password) throw Error('Invalid source URL'); }
    ids.add(s.id);
  }
  const adapted = m.sources.filter(s => s.rights !== undefined);
  if (m.rightsInventory === undefined && !adapted.length) return m;
  // Adapted C5 rights: every row keeps its hash, terms link and an explicit, uncleared status.
  const r = m.rightsInventory;
  // The rights page passes the viewer's own containment rules, so a manifest that validates can always link it.
  if (!r || r.schemaVersion !== 1 || !HEX64.test(String(r.sha256)) || r.status !== 'review_required' ||
      !isLocalAssetPath(r.page) || !Array.isArray(r.caveats) ||
      adapted.length !== m.sources.length) throw Error('Incomplete rights inventory link');
  for (const s of m.sources) {
    const x = s.rights;
    if (!x || !HEX64.test(String(x.sha256)) || !text(x.termsUrl) || !/^https:\/\//.test(x.termsUrl) ||
        !Number.isSafeInteger(x.contributedCells) || x.contributedCells <= 0 || typeof x.csumbInvolved !== 'boolean' ||
        !['needs_permission', 'review_required'].includes(x.status)) throw Error('Incomplete source rights');
    const u = new URL(x.termsUrl); if (u.username || u.password) throw Error('Invalid terms URL');
    const csumb = x.csumbInvolved || mentionsCsumb(evidence(s));
    // Never infer permission: a CSUMB row cannot lose its hold, and the hold is not invented for others.
    if (csumb !== x.csumbInvolved || (x.status === 'needs_permission') !== csumb || s.permissionRequired !== csumb) {
      throw Error('Unresolved CSUMB permission must stay needs_permission');
    }
  }
  const required = [NOT_FOR_NAVIGATION, RIGHTS_REVIEW, NO_ENDORSEMENT];
  if (m.sources.some(s => s.rights!.csumbInvolved)) required.push(CSUMB_NOTICE);
  if (m.sources.some(s => mentionsGebco(evidence(s)))) required.push(GEBCO_CAVEAT);
  if (!required.every(c => r.caveats.includes(c))) throw Error('Rights caveats missing');
  return m;
}
/** Opt-in viewer only: never changes the existing production coast route. */
export class CoastMvpViewer {
  readonly map: CoastMap;
  private chrome: HTMLElement;
  private constructor(host: HTMLElement, manifest: MvpManifest, base: URL) {
    const terrain = localAsset(manifest.terrain, base), contours = localAsset(manifest.contours, base);
    const rightsPage = manifest.rightsInventory ? localAsset(manifest.rightsInventory.page, base) : null;
    // Inset exact XYZ edges to avoid admitting an adjacent tile at the boundary.
    const [w,s,e,n] = manifest.bounds;
    const tileBounds: [number,number,number,number] = [w+1e-9,s+1e-9,e-1e-9,n-1e-9];
    this.chrome = document.createElement('section');
    this.chrome.className = 'coast-mvp-chrome';
    const banner = document.createElement('strong');
    const held = manifest.rightsInventory !== undefined && manifest.sources.some(s => s.permissionRequired);
    // Persistent, outside the collapsible panel: unresolved permission stays visible.
    banner.textContent = 'Not for navigation · ' + (manifest.synthetic ? 'SYNTHETIC FIXTURE — not measured bathymetry' : 'Preview — unreviewed terrain') +
      (manifest.rightsInventory ? ' · Rights review required' : '') + (held ? ' · For-profit permission unresolved (needs_permission)' : '');
    banner.setAttribute('role', 'note');
    const panel = document.createElement('details'); panel.open = true;
    const title = document.createElement('summary'); title.textContent = manifest.region + ' · sources & rights'; panel.append(title);
    const external = (row: HTMLElement, href: string, label: string) => {
      const link = document.createElement('a'); link.href = href; link.textContent = label; link.target = '_blank'; link.rel = 'noopener noreferrer'; row.append(link);
    };
    if (manifest.mosaic) {
      const row = document.createElement('p');
      row.textContent = `Terrain tiles — datum: ${manifest.mosaic.datum}. Tile spacing: ${manifest.mosaic.resolutionM.toFixed(1)} m.`;
      panel.append(row);
    }
    for (const s of manifest.sources) {
      const row = document.createElement('p');
      const x = s.rights;
      if (!x) {
        row.textContent = `${s.label} — ${s.attribution}. ${s.license}. Datum: ${s.datum}. Source spacing: ${s.resolutionM?.toFixed(1)} m. ${s.permissionRequired ? 'For-profit permission unresolved — publication held.' : ''}`;
        if (s.url) external(row, s.url, ' Source');
      } else {
        row.className = 'coast-mvp-source'; row.dataset.sourceId = s.id; row.dataset.rightsStatus = x.status;
        const spacing = s.datum === null || s.resolutionM === null ? 'Source datum/spacing: not in rights inventory.'
          : `Datum: ${s.datum}. Source spacing: ${s.resolutionM.toFixed(1)} m.`;
        row.textContent = `${s.label} — ${s.attribution}. Licence / terms: ${s.license}. ${spacing} Rights: ${x.status}` +
          (x.status === 'needs_permission' ? ' — for-profit permission unresolved; publication held.' : ' — recorded terms are not a clearance decision.') +
          ` Contributed cells: ${x.contributedCells}. Input SHA-256: ${x.sha256}. `;
        if (s.url) external(row, s.url, 'Source');
        row.append(' · '); external(row, x.termsUrl, 'Terms');
      }
      panel.append(row);
    }
    if (manifest.rightsInventory && rightsPage) {
      for (const c of manifest.rightsInventory.caveats) { const p = document.createElement('p'); p.className = 'coast-mvp-caveat'; p.textContent = c; panel.append(p); }
      const p = document.createElement('p');
      p.textContent = `Rights inventory SHA-256: ${manifest.rightsInventory.sha256}. `;
      const link = document.createElement('a'); link.className = 'coast-mvp-rights-page'; link.href = rightsPage;
      link.textContent = 'Complete rights and attribution page'; link.target = '_blank'; link.rel = 'noopener';
      p.append(link); panel.append(p);
    }
    const note = document.createElement('p'); note.textContent = 'Relief ×3 (display only). Contours: feet below reference; source detail varies. No accuracy claim. Review required.'; panel.append(note);
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
  static async load(host: HTMLElement, manifestUrl: string): Promise<CoastMvpViewer> {
    const url = new URL(manifestUrl, location.href);
    if (url.origin !== location.origin || url.username || url.password) throw Error('Local manifest required');
    const response = await fetch(url, {redirect: 'error', signal: AbortSignal.timeout(20000)});
    if (!response.ok) throw Error('Local manifest unavailable');
    return new CoastMvpViewer(host, validateMvpManifest(await response.json()), new URL('./', url));
  }
  destroy(): void { this.map.remove(); this.chrome.remove(); }
}
