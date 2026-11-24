// MB-08: chart-only research depth shading. E2E-17 verifies each returned tile.
import {computed, effect, signal as cell} from '@preact/signals';
import type {AddProtocolAction, LayerSpecification} from 'maplibre-gl';
import {PMTiles, TileType} from 'pmtiles';
import {waypointPlacement} from '../waypoint-placement.ts';
import {chartMark} from './chart.ts';
import type {Engine} from './engine.ts';
import {BOTTOM_RELIEF} from './layers.ts';
import {chartPick} from './marks.ts';
import {fieldDesaturation} from './nearshore-paint.ts';
import {language, t, type StringId} from '../i18n.ts';
import {readPalette, type Palette} from './palette.ts';
import {resolveRelief} from './relief-data.ts';
import {reliefVerifier} from './relief-verify.ts';
import {BASEMAP_SOURCE, basemapStyle} from './style.ts';
import {decodeSurveyDetail, surveyDetailLayers, surveyHatchPattern} from './survey-detail.ts';
import {paintEdits} from './theme-restyle.ts';

export interface SurveyDetailView {
  readonly classes: ReadonlySet<string>;
  readonly shown: boolean;
  toggle(): void;
}

const SCHEME = 'bottom-relief';
const readers = new Map<string, (z: number, x: number, y: number, signal: AbortSignal) => ReturnType<AddProtocolAction>>();
const libraries = new WeakSet<object>();
let serial = 0;
const tileMissing = () => Object.assign(new Error('No relief tile at this zoom'), {status: 404});
const readTile: AddProtocolAction = ({url}, {signal}) => {
  const parts = /^bottom-relief:\/\/([0-9]+)\/(\d+)\/(\d+)\/(\d+)$/.exec(url);
  const read = parts && readers.get(parts[1]!);
  if (!read) throw tileMissing();
  return read(Number(parts[2]), Number(parts[3]), Number(parts[4]), signal);
};

interface ReliefOptions {
  engine: Engine;
  region: string;
  library?: {addProtocol(name: string, action: AddProtocolAction): void};
  seafloorOn(): boolean;
  fieldOn(): boolean;
  unavailable(error: unknown): void;
  /** Fires once the overlay is drawn, with the look its tiles were baked with (relief-data.ts `reliefLook`) for the legend. */
  ready?(look: string | null): void;
  page?: string;
  fetchFn?: typeof fetch;
  /** Already verified against the selected archive's release binding. Until
   * that handoff exists only the synthetic acceptance fixture supplies this. */
  surveyDetail?: unknown;
  surveyView?(view: SurveyDetailView | null): void;
}

/** The caller creates this on the Chart (web/map/layers.ts `reliefWanted`; signed-out users included) and destroys it on a
 * region/gate/presentation change. No fallback pointer. Nothing is drawn, and no archive or tile is requested, unless the
 * region's pointer resolves `ready`; `ready` fires once the overlay is drawn, `unavailable` on any failure. */
export function attachBottomRelief(o: ReliefOptions): {destroy(): void} {
  const page = o.page ?? location.href, fetchFn = o.fetchFn ?? fetch;
  const abort = new AbortController(), token = String(++serial), source = `${BOTTOM_RELIEF}-${token}`;
  const survey = `${source}-survey`, pattern = `${survey}-pattern`, hit = `${survey}-hit`;
  const isLight = () => document.documentElement.dataset.theme === 'light';
  let disposePaint: (() => void) | undefined, disposeSurvey: (() => void) | undefined, drawn = false;
  function destroy() {
    abort.abort();
    readers.delete(token);
    disposePaint?.();
    disposeSurvey?.();
    o.surveyView?.(null);
    if (drawn) { drawn = false; o.engine.setOverlay(BOTTOM_RELIEF, null); }
    if (chartMark.peek()?.id === survey) chartMark.value = null;
  }
  function fail(error: unknown) {
    if (abort.signal.aborted) return;
    destroy();
    o.unavailable(error);
  }

  async function start() {
    const signal = abort.signal;
    const path = `catalog/relief/${encodeURIComponent(o.region)}.json`;
    const response = await fetchFn(new URL(path, page), {signal, redirect: 'error'});
    if (!response.ok) throw new Error(`Relief pointer unavailable (HTTP ${response.status})`);
    const pointer = await response.json();
    const selected = resolveRelief(o.region, pointer);
    if (selected.status !== 'ready') throw new Error(`Relief unavailable: ${selected.reason}`);
    signal.throwIfAborted();
    const a = selected.archive;
    const url = new URL(`feeds/${a.object_key}`, page).href;
    const archive = new PMTiles({getKey: () => url, async getBytes(offset, length, request, etag) {
      const combined = request ? AbortSignal.any([signal, request]) : signal;
      // PMTiles initially asks for 16 KiB even if the archive is smaller.
      const end = (offset === 0 && length === 16384 ? Math.min(a.bytes, length) : offset + length) - 1;
      if (!Number.isSafeInteger(offset) || offset < 0 || !Number.isSafeInteger(end) || end < offset || end >= a.bytes) throw new Error('Invalid relief range');
      const result = await fetchFn(url, {headers: {Range: `bytes=${offset}-${end}`}, signal: combined, redirect: 'error'});
      if (result.status !== 206 || result.headers.get('Content-Range') !== `bytes ${offset}-${end}/${a.bytes}`) {
        void result.body?.cancel();
        throw new Error('Relief server did not return the requested range');
      }
      const data = await result.arrayBuffer(), tag = result.headers.get('ETag') ?? undefined;
      if (data.byteLength !== end - offset + 1 || (etag && tag !== etag)) throw new Error('Relief range changed');
      return {data, etag: tag};
    }});
    // MapLibre uses the pointer's bounds and zoom limits, not a loose TileJSON
    // returned by the object. The header is read only when the first tile is wanted.
    // Load through the same deferred renderer boundary as the Chart. The
    // running Chart already has this module; Reports never loads it.
    const library = o.library ?? (await import('./maplibre.js')).lib;
    signal.throwIfAborted();
    if (!libraries.has(library)) {
      library.addProtocol(SCHEME, readTile);
      libraries.add(library);
    }
    const verify = reliefVerifier(a, page, fetchFn, signal);
    let checked: ReturnType<typeof archive.getHeader> | undefined;
    readers.set(token, async (z, x, y, request) => {
      if (z < a.minzoom || z > a.maxzoom) throw tileMissing();
      request.throwIfAborted();
      signal.throwIfAborted();
      let tile;
      try {
        const h = await (checked ??= archive.getHeader());
        if (h.tileType !== TileType.Png || h.minZoom !== a.minzoom || h.maxZoom !== a.maxzoom) throw new Error('Relief header does not match the pointer');
        request.throwIfAborted();
        signal.throwIfAborted();
        tile = await archive.getZxy(z, x, y, AbortSignal.any([signal, request]));
        request.throwIfAborted();
        signal.throwIfAborted();
      } catch (error) {
        if (!request.aborted) fail(error);
        throw error;
      }
      try {
        await verify(z, x, y, tile?.data);
      } catch (error) {
        // The index is shared across tile requests; a pan's cancellation
        // cannot mask an integrity failure. Region teardown still cancels it.
        fail(error);
        throw error;
      }
      request.throwIfAborted();
      signal.throwIfAborted();
      // Only an authenticated hole allows MapLibre to use a parent tile.
      if (!tile) throw tileMissing();
      return {data: tile.data};
    });

    const b = pointer.survey_detail;
    const rep = (r: unknown, max: number): r is {bytes: number; sha256: string} => {
      if (!r || typeof r !== 'object') return false;
      const {bytes, sha256} = r as {bytes: number; sha256: unknown};
      return Object.keys(r).sort().join() === 'bytes,sha256' && Number.isSafeInteger(bytes) && bytes > 0 && bytes <= max &&
        typeof sha256 === 'string' && /^[a-f0-9]{64}$/.test(sha256);
    };
    const binding = pointer.status === 'reviewed' && b && Object.keys(b).sort().join() === 'decoded,wire' &&
      rep(b.wire, 5 * 1024 * 1024) && rep(b.decoded, 16 * 1024 * 1024) ? b as {wire: {bytes:number; sha256:string}; decoded: {bytes:number; sha256:string}} : null;
    async function verifiedSurvey(): Promise<unknown> {
      if (!binding) return undefined;
      try {
        const response = await fetchFn(new URL(`feeds/tiles/relief/${o.region}/${a.envelope_sha256}/survey/${binding.wire.sha256}.geojson.br`, page),
          {signal, redirect: 'error'});
        if (!response.ok || !response.body || response.headers.get('Content-Encoding') !== 'br' ||
            response.headers.get('Content-Length') !== String(binding.wire.bytes)) {
          void response.body?.cancel(); return undefined;
        }
        const stream = response.body.getReader(), bytes = new Uint8Array(binding.decoded.bytes);
        let size = 0;
        try {
          while (true) {
            const {done, value} = await stream.read();
            if (done) break;
            if (size + value.length > bytes.length) { await stream.cancel(); return undefined; }
            bytes.set(value, size); size += value.length;
          }
        } finally { stream.releaseLock(); }
        if (size !== bytes.length) return undefined;
        const digest = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', bytes)),
          n => n.toString(16).padStart(2, '0')).join('');
        signal.throwIfAborted();
        if (digest !== binding.decoded.sha256) return undefined;
        return JSON.parse(new TextDecoder('utf-8', {fatal: true}).decode(bytes));
      } catch { return undefined; }
    }
    const decode = (raw: unknown) => raw === undefined ? null : decodeSurveyDetail(o.region, raw, new Set(a.sources.map(s => s.id)));
    const detail = cell(decode(o.surveyDetail));
    const available = () => !!detail.peek()?.features.length && !!surveyHatchPattern(pattern, readPalette(), isLight()).length;
    let pending = false, refused = false, detailOn = false, detailIds: string[] = [];
    const control = available() && !o.surveyView ? document.createElement('div') : null;
    const setDetail = () => { for (const id of detailIds) o.engine.setVisible(id, detailOn); };
    const updateView = () => {
      if (!o.surveyView || signal.aborted) return;
      if (!available() && (!binding || refused)) { o.surveyView(null); return; }
      const classes = new Set(available() ? o.engine.renderedValues(hit, 'tier') : []);
      if (available()) for (const grid of o.engine.renderedValues(hit, 'grid_tier')) classes.add(grid);
      o.surveyView({classes, shown: detailOn, toggle});
    };
    function toggle() {
      if (signal.aborted || pending || refused) return;
      if (available()) { detailOn = !detailOn; setDetail(); updateView(); return; }
      if (!binding) return;
      pending = true;
      void verifiedSurvey().then(raw => {
        if (signal.aborted) return;
        pending = false;
        const parsed = decode(raw);
        refused = !parsed?.features.length;
        if (parsed?.features.length) { detailOn = true; detail.value = parsed; }
        updateView();
      });
    }
    if ((available() || binding) && o.surveyView) disposeSurvey = o.engine.view.on('idle', updateView);
    if (control) {
      control.className = 'maplibregl-ctrl';
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'ui-button ui-button--ghost';
      button.textContent = 'Show survey detail';
      button.setAttribute('aria-pressed', 'false');
      button.onclick = () => { toggle(); button.setAttribute('aria-pressed', String(detailOn)); };
      control.append(button);
    }
    const buildLayers = (p: Palette, light: boolean, seafloor: boolean, field: boolean) => {
      const land = basemapStyle(p, {archive: '', assets: ''}).layers.filter(l => l.id === 'earth' || l.id === 'parks');
      // MSK-2 (kit overlays.base_desaturation_when_field_on): a colour field desaturates the relief rather than fading it, so
      // the relief keeps its shape under the field. Seafloor type's stronger dimming (MAP-DESIGN-LOCK § 2.2/§ 10.2) still wins.
      const layers: LayerSpecification[] = [{id: source, type: 'raster', source, minzoom: a.minzoom - 1,
        paint: {'raster-resampling': 'linear', 'raster-fade-duration': 0, 'raster-opacity': 1,
          'raster-saturation': seafloor ? -0.8 : field ? fieldDesaturation() : 0, 'raster-brightness-min': seafloor && light ? 0.30 : 0,
          'raster-brightness-max': seafloor && !light ? 0.75 : 1}}];
      const hasDetail = available();
      const detailLayers = hasDetail ? surveyDetailLayers(survey, survey, pattern, p, light) : [];
      if (hasDetail) layers.push(...detailLayers, {id: hit, type: 'fill', source: survey, paint: {'fill-opacity': 0}});
      layers.push(...land.map(l => ({...l, id: `${source}-${l.id}`} as LayerSpecification)),
      {id: `${source}-coast`, type: 'line', source: BASEMAP_SOURCE, 'source-layer': 'earth',
        paint: {'line-color': p.mapCoast, 'line-width': ['interpolate', ['linear'], ['zoom'], 6, light ? 0.7 : 0.5, 13, light ? 1.8 : 1.4],
          'line-opacity': light ? 1 : 0.85}});
      return {layers, detailLayers};
    };

    const seafloorOn = computed(() => o.seafloorOn()), fieldOn = computed(() => o.fieldOn());
    disposePaint = effect(() => {
      if (signal.aborted) return;
      const seafloor = seafloorOn.value, field = fieldOn.value;
      const current = detail.value, hasDetail = available();
      const {layers, detailLayers} = buildLayers(readPalette(), isLight(), seafloor, field);
      detailIds = detailLayers.slice(1).map(l => l.id); // The hatch stays visible.
      drawn = true;
      // Settings resubmit paints against the same IDs. On a theme switch the
      // engine calls only the providers, using the current effective theme.
      // No source or attribution text on the map (G 2026-11-18); credits live on the sources page.
      o.engine.setOverlay(BOTTOM_RELIEF, {stopOnError: true, sources: {[source]: {type: 'raster', tileSize: 256,
        tiles: [`${SCHEME}://${token}/{z}/{x}/{y}`], minzoom: a.minzoom, maxzoom: a.maxzoom, bounds: [...a.bounds]},
        ...hasDetail && current ? {[survey]: {type: 'geojson', data: current}} : {}}, layers,
        themePaint: p => paintEdits(buildLayers(p, isLight(), seafloor, field).layers),
        ...control ? {control} : {},
        ...hasDetail ? {themePatterns: p => surveyHatchPattern(pattern, p, isLight()),
          inspect: {layer: hit, show(properties) {
            // Refused waypoints remain armed; successful ones change the
            // engine's pick context. Neither may open a survey card instead.
            if (chartMark.peek() || waypointPlacement.peek() || typeof properties.tier !== 'string') return;
            const lang = language.peek();
            const reading = properties.tier === 'estimated' && typeof properties.grid_m === 'number'
              ? t('legend.surveyDetail.estimateGrid', lang, {grid: properties.grid_m})
              : t(`legend.surveyDetail.chip.${properties.tier}` as StringId, lang);
            chartMark.value = chartPick(null, null, {id: survey, name: t('legend.surveyDetail.title', lang), kind: '', reading,
              source: '',
              basis: typeof properties.date === 'string' ? properties.date : ''});
          }}} : {}}, 'boundaries');
      setDetail();
    });
    updateView();
    if (!signal.aborted) o.ready?.(a.look);
  }
  void start().catch(fail);
  return {destroy};
}
