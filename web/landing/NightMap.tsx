// The landing's live night map (FE-25, docs/plans/front-end/design.md § 7 and
// § 13, concept D · Open water): FE-72's night basemap through FE-11's engine
// as a still backdrop (no gesture, key or control), the region's NOAA CUSP
// shoreline with the landing's glow, and FE-15's streamlines from the latest
// fresh surface-current frame. main.tsx imports this module after first paint
// and only where WebGL2 works; the module loads MapLibre itself by dynamic
// import (web/map/maplibre.js), as the Chart does. The FE-07 shoreline SVG is
// the first paint and stays on top until this map has drawn every tile in
// view; without a basemap archive, the region, the coastline or MapLibre it
// stays alone. The map is decorative (hidden from assistive technology): the
// readout carries the readings, and the footer credits the basemap and gives
// the drawn currents' source and age (D13).
import {signal} from '@preact/signals';
import {useEffect, useRef} from 'preact/hooks';
import type * as MapLibre from 'maplibre-gl';
import type {ReportLocalArea} from '../../packages/coast/src/state/report-binding.ts';
import {coastOcean} from '../coast-data.ts';
import {DEFAULT_PROFILE} from '../profile.ts';
import type {CurrentChoice} from '../state.ts';
import {COASTLINE_GLOW, coastlineLayers, coastlineSource} from '../map/coastline.ts';
import {createCurrents, currentsState, regionPlace, type Currents} from '../map/currents.ts';
import {createEngine, type Engine, type EngineCamera, type MapLibraryModule} from '../map/engine.ts';
import {chosenCurrent} from '../map/frames.ts';
import {COASTLINE_SOURCE} from '../map/layers.ts';
import {readPalette, type Palette} from '../map/palette.ts';
import {terrainHour} from '../map/stage.ts';
import {BASEMAP_ATTRIBUTION, basemapArchive, basemapStyle} from '../map/style.ts';

/** The order the landing looks for a fresh frame in: the forecast (the app's proposed boat default, #482), then observed HF radar. */
export const NIGHT_SOURCES = ['wcofs', 'hfr-6', 'hfr-1'] as const satisfies readonly CurrentChoice[];
/** design § 6's desktop breakpoint: the hero takes the left half there, so the harbor sits further right. */
const WIDE = 1024;

/** The first listed source with a fresh frame for the current hour (the app's own gates, web/map/frames.ts); the forecast while none has. */
export function nightSource(fields: unknown, now: Date): CurrentChoice {
  const at = terrainHour(null, now);
  return NIGHT_SOURCES.find(id => chosenCurrent(fields, id, at, now) !== null) ?? NIGHT_SOURCES[0];
}

/** What the night map reads from regions/<id>/region.json. */
export interface NightRegion {
  readonly id: string;
  readonly center: readonly [number, number];
  readonly timezone: string;
  /** [west, south, east, north]. */
  readonly bounds: readonly [number, number, number, number];
  readonly harbor: {readonly latitude: number; readonly longitude: number};
  readonly localAreas: readonly ReportLocalArea[];
}

const finite = (n: unknown): n is number => typeof n === 'number' && Number.isFinite(n);

/** The region's frame, harbor and reviewed local areas, or null when region.json lacks the centre or bounds. */
export async function nightRegion(id: string, fetchFn: typeof fetch, page: string): Promise<NightRegion | null> {
  try {
    const response = await fetchFn(new URL(`regions/${encodeURIComponent(id)}/region.json`, page).href, {signal: AbortSignal.timeout(15000)});
    if (!response.ok) return null;
    const r = await response.json() as {timezone?: unknown; bounds?: unknown; harbor?: {latitude?: unknown; longitude?: unknown}; map?: {center?: unknown; local_areas?: unknown}};
    const c = Array.isArray(r.map?.center) ? r.map.center : [], b = Array.isArray(r.bounds) ? r.bounds : [];
    const [lat, lon] = c, [west, south, east, north] = b;
    if (c.length !== 2 || !finite(lat) || !finite(lon) || b.length !== 4 || !finite(west) || !finite(south) || !finite(east) || !finite(north)) return null;
    const h = r.harbor, areas = Array.isArray(r.map?.local_areas) ? r.map.local_areas as ReportLocalArea[] : [];
    return {
      id, center: [lat, lon], timezone: typeof r.timezone === 'string' ? r.timezone : 'America/Los_Angeles', bounds: [west, south, east, north],
      harbor: finite(h?.latitude) && finite(h?.longitude) ? {latitude: h.latitude, longitude: h.longitude} : {latitude: lat, longitude: lon},
      localAreas: areas.filter(a => typeof a?.id === 'string' && Array.isArray(a.bounds)),
    };
  } catch { return null; }
}

/**
 * The camera (`?view=` zoom) that shows the region's bounds from top to bottom with its harbor
 * right of centre, so the hero sits over open water on the left (§ 7): 72% across on a wide
 * screen, 62% on a phone, where the text covers the whole width anyway.
 */
export function nightCamera(region: Pick<NightRegion, 'bounds' | 'harbor'>, width: number, height: number): EngineCamera {
  const [, south, , north] = region.bounds, latitude = (south + north) / 2;
  // Longitude degrees per CSS pixel at that latitude: Mercator keeps a pixel square.
  const perPx = (north - south) / Math.max(1, height) / Math.cos(latitude * Math.PI / 180);
  const harborAt = width >= WIDE ? 0.72 : 0.62;
  return {latitude, longitude: region.harbor.longitude - (harborAt - 0.5) * width * perPx, zoom: Math.log2(360 / (256 * perPx))};
}

/** FE-11's coastline with the landing's glow (the SVG's treatment in landing.css): a wide depth-0 glow under a fine flow-coloured line. */
export function nightCoastline(p: Palette) {
  return coastlineLayers(p).map(layer => layer.id === COASTLINE_GLOW
    ? {...layer, paint: {...layer.paint, 'line-color': p.depth0, 'line-opacity': 0.45}}
    : {...layer, paint: {...layer.paint, 'line-color': p.flow, 'line-opacity': 0.9}});
}

/** FE-72's night variant with the coastline drawn last. */
export function nightStyle(p: Palette, archive: string, page: string, region: string): MapLibre.StyleSpecification {
  const style = basemapStyle(p, {archive, assets: new URL('basemap/', page).href, variant: 'night'});
  return {...style, sources: {...style.sources, [COASTLINE_SOURCE]: coastlineSource(region, page)}, layers: [...style.layers, ...nightCoastline(p)]} as unknown as MapLibre.StyleSpecification;
}

export type NightState = 'loading' | 'ready' | 'failed';
/** 'ready' once the map has drawn every tile in view; 'failed' leaves the static shoreline alone. */
export const nightState = signal<NightState>('loading');

export interface NightMapProps {
  /** The page URL feeds and regions resolve against. */
  page: string;
  region: string;
  onState?: (state: NightState) => void;
  load?: () => Promise<MapLibraryModule>;
  fetchFn?: typeof fetch;
}

const loadLibrary = (): Promise<MapLibraryModule> => import('../map/maplibre.js');

export function NightMap({page, region, onState, load = loadLibrary, fetchFn = (...a) => fetch(...a)}: NightMapProps) {
  const host = useRef<HTMLDivElement>(null);
  useEffect(() => {
    let alive = true, engine: Engine | null = null, currents: Currents | null = null;
    const set = (state: NightState): void => { nightState.value = state; onState?.(state); };
    const stop = (): void => { currents?.destroy(); engine?.destroy(); currents = null; engine = null; };
    // Off MapLibre's own event stack: a source error may arrive while it is still dispatching.
    const fail = (why: unknown): void => {
      if (!alive) return;
      alive = false;
      console.warn('Night map unavailable; the static shoreline stays.', why);
      setTimeout(stop, 0);
      set('failed');
    };
    void (async () => {
      try {
        const [library, archive, info] = await Promise.all([load(), basemapArchive(fetchFn, page), nightRegion(region, fetchFn, page)]);
        const el = host.current;
        if (!alive || !el) return;
        if (!archive || !info) { fail(!archive ? 'no basemap archive' : `no region frame for ${region}`); return; }
        const palette = readPalette();
        let drawn = false;
        engine = createEngine(library, {
          host: el, still: true, style: nightStyle(palette, archive, page, region),
          camera: nightCamera(info, el.clientWidth || innerWidth, el.clientHeight || innerHeight),
          onMove() { /* a still map never moves */ },
          onLayerError: (layer, error) => { if (layer === 'basemap' || layer === 'coastline') fail(error); },
          onIdle: () => { if (alive && !drawn) { drawn = true; set('ready'); } },
        });
        // A resized window (a phone turned) is framed again; the streamlines rebuild once it settles.
        engine.view.on('resize', () => { if (el.clientWidth && el.clientHeight) engine?.setCamera(nightCamera(info, el.clientWidth, el.clientHeight)); });
        currents = createCurrents({
          view: engine.view, palette: () => palette, zone: () => info.timezone, place: () => regionPlace(info, DEFAULT_PROFILE, ''),
          source: () => nightSource(coastOcean.value?.data.currents, new Date()), shown: () => true,
        });
      } catch (error) { fail(error); }
    })();
    return () => { alive = false; stop(); };
  }, []);
  return <div class="landing-night" ref={host} data-state={nightState.value} aria-hidden="true" />;
}

/** The footer's credit for what the night map draws, once it has drawn: the basemap, and the drawn currents' basis (source, age and what the motion means). */
export function NightCredit() {
  if (nightState.value !== 'ready') return null;
  const currents = currentsState.value;
  return (
    <>
      <p class="landing-credit" data-credit="basemap">Basemap: {BASEMAP_ATTRIBUTION}.</p>
      {currents.drawn ? <p class="landing-credit" data-credit="currents">Currents: {currents.basis}</p> : null}
    </>
  );
}
