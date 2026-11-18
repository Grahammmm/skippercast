// MB-08: chart-only research depth shading. E2E-17 verifies each returned tile.
import {effect} from '@preact/signals';
import type {AddProtocolAction, LayerSpecification} from 'maplibre-gl';
import {PMTiles, TileType} from 'pmtiles';
import {waypointPlacement} from '../waypoint-placement.ts';
import {chartMark} from './chart.ts';
import type {Engine} from './engine.ts';
import {BOTTOM_RELIEF} from './layers.ts';
import {chartPick} from './marks.ts';
import {readPalette} from './palette.ts';
import {resolveRelief} from './relief-data.ts';
import {reliefVerifier} from './relief-verify.ts';
import {BASEMAP_SOURCE, basemapStyle} from './style.ts';
import {decodeSurveyDetail, surveyDetailLayers, surveyHatch, SURVEY_HATCH_PIXEL_RATIO} from './survey-detail.ts';

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
  page?: string;
  fetchFn?: typeof fetch;
  /** Already verified against the selected archive's release binding. Until
   * that handoff exists only the synthetic acceptance fixture supplies this. */
  surveyDetail?: unknown;
}

/** The caller creates this only on the visible, explicitly enabled admin Chart,
 * and destroys it on a region/gate/presentation change. No fallback pointer. */
export function attachBottomRelief(o: ReliefOptions): {destroy(): void} {
  const page = o.page ?? location.href, fetchFn = o.fetchFn ?? fetch;
  const abort = new AbortController(), token = String(++serial), source = `${BOTTOM_RELIEF}-${token}`;
  const survey = `${source}-survey`;
  const root = document.documentElement;
  let disposePaint: (() => void) | undefined, observer: MutationObserver | undefined, drawn = false;
  function destroy() {
    abort.abort();
    readers.delete(token);
    observer?.disconnect();
    disposePaint?.();
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
    const selected = resolveRelief(o.region, await response.json());
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

    // Do not read a pointer field or infer a footprint from a blank raster tile.
    const detail = o.surveyDetail === undefined ? null : decodeSurveyDetail(o.region, o.surveyDetail, new Set(a.sources.map(s => s.id)));
    const control = detail?.type === 'FeatureCollection' && detail.features.length ? document.createElement('div') : null;
    let detailOn = false, detailIds: string[] = [];
    const setDetail = () => { for (const id of detailIds) o.engine.setVisible(id, detailOn); };
    if (control) {
      control.className = 'maplibregl-ctrl';
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'ui-button ui-button--ghost';
      button.textContent = 'Show survey detail';
      button.setAttribute('aria-pressed', 'false');
      button.onclick = () => { detailOn = !detailOn; button.setAttribute('aria-pressed', String(detailOn)); setDetail(); };
      control.append(button);
    }
    let painted = '', raster: string;
    const draw = (seafloor: boolean, field: boolean) => {
      if (signal.aborted) return;
      const light = root.dataset.theme === 'light';
      const paintKey = `${light ? 'light' : 'dark'}-${seafloor}`;
      const opacity = field ? 0.6 : 1;
      if (painted === paintKey) { o.engine.setRasterOpacity(raster, opacity); return; }
      painted = paintKey;
      const p = readPalette();
      const land = basemapStyle(p, {archive: '', assets: ''}).layers.filter(l => l.id === 'earth' || l.id === 'parks');
      raster = `${source}-${paintKey}`;
      // Engine keeps sources by id. Replace only the paint-bearing layer(s)
      // when needed; the raster source, loaded tiles and camera stay put.
      const layers: LayerSpecification[] = [{id: raster, type: 'raster', source, minzoom: a.minzoom - 1,
        paint: {'raster-resampling': 'linear', 'raster-fade-duration': 0, 'raster-opacity': opacity,
          'raster-saturation': seafloor ? -0.8 : 0, 'raster-brightness-min': seafloor && light ? 0.30 : 0,
          'raster-brightness-max': seafloor && !light ? 0.75 : 1}}];
      const themed = `${survey}-${paintKey}`, pattern = `${themed}-pattern`;
      const hatch = control && surveyHatch(p, light);
      const hit = `${themed}-hit`;
      if (hatch) {
        const [gap, ...optional] = surveyDetailLayers(survey, themed, pattern, p, light);
        detailIds = optional.map(l => l.id);
        layers.push(gap!, ...optional, {id: hit, type: 'fill', source: survey, paint: {'fill-opacity': 0}});
      }
      layers.push(...land.map(l => ({...l, id: `${BOTTOM_RELIEF}-${l.id}-${paintKey}`} as LayerSpecification)),
      {id: `${BOTTOM_RELIEF}-coast-${paintKey}`, type: 'line', source: BASEMAP_SOURCE, 'source-layer': 'earth',
        paint: {'line-color': p.mapCoast, 'line-width': ['interpolate', ['linear'], ['zoom'], 6, light ? 0.7 : 0.5, 13, light ? 1.8 : 1.4],
          'line-opacity': light ? 1 : 0.85}});

      drawn = true;
      o.engine.setOverlay(BOTTOM_RELIEF, {stopOnError: true, sources: {[source]: {type: 'raster', tileSize: 256,
        tiles: [`${SCHEME}://${token}/{z}/{x}/{y}`], minzoom: a.minzoom, maxzoom: a.maxzoom, bounds: [...a.bounds],
        attribution: a.sources.map(s => s.attribution).join(' · ')},
        ...hatch && detail ? {[survey]: {type: 'geojson', data: detail}} : {}}, layers,
        ...hatch && control ? {pattern: {id: pattern, image: hatch, pixelRatio: SURVEY_HATCH_PIXEL_RATIO}, control,
          inspect: {layer: hit, show(properties) {
            // Refused waypoints remain armed; successful ones change the
            // engine's pick context. Neither may open a survey card instead.
            if (chartMark.peek() || waypointPlacement.peek() || typeof properties.label !== 'string') return;
            chartMark.value = chartPick(null, null, {id: survey, name: 'Survey detail', kind: '', reading: properties.label,
              source: typeof properties.source === 'string' ? properties.source : '',
              basis: typeof properties.date === 'string' ? properties.date : ''});
          }}} : {}}, 'boundaries');
      setDetail();
    };
    disposePaint = effect(() => draw(o.seafloorOn(), o.fieldOn()));
    observer = new MutationObserver(() => draw(o.seafloorOn(), o.fieldOn()));
    observer.observe(root, {attributes: true, attributeFilter: ['data-theme']});
  }
  void start().catch(fail);
  return {destroy};
}
