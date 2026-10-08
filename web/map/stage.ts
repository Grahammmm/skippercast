// MapStage adapter (FE-71, docs/plans/front-end/design.md § 3A.2): one camera,
// one selection and one hour over three presentations of the same place.
// Chart is MapLibre (FE-11 adds its branch here; until then the component's
// placeholder). Terrain 2D and 3D are packages/coast's renderer through its
// embed API (mountCoast, FE-70), loaded by dynamic import on the first terrain
// choice so three never reaches the app's first paint (scripts/check_client.mjs).
// Preact components never touch a renderer: web/app/MapStage.tsx creates one
// stage while it is mounted and reads the signals exported here. One stage
// exists at a time (the shell renders either the desktop or the mobile layout).
//
// Erasable syntax only: tests/test_map_stage.mjs imports this file by type
// stripping and passes a fake terrain module, so no GPU or three is needed.
import {computed, effect, signal} from '@preact/signals';
import type {CoastHandle, CoastLocation, CoastMountOptions, CoastPerspective, CoastSelection} from '../../packages/coast/src/embed-types.ts';
import type {CoastPalette} from '../../packages/coast/src/palette.ts';
import {coastTarget, hasCoastTerrain, type CurrentLayer, type Presentation} from '../coast-context.ts';
import {PROFILE_TABLE, terrainDepthLimitFt, type Profile} from '../profile.ts';
import {
  appView, current, habitat, hour, navigate, parseHour, presentation, profile, region, setParams, species,
  stagePresentation, UNSUPPORTED, view, withParams, type AppView, type CurrentChoice,
} from '../state.ts';

/** The shared camera as `?view=` writes it: centre in degrees and a web-map zoom. */
export interface Camera {readonly latitude: number; readonly longitude: number; readonly zoom: number}

/** The zoom a region's centre opens at when the link names no camera. */
export const HOME_ZOOM = 12;
/** v1's wording (dist/coast-workspace.js). */
export const UNAVAILABLE = 'Coastal graphics are unavailable. The chart, forecasts and trip tools remain usable.';
export const NO_TERRAIN = 'No reviewed coastal terrain covers this region yet.';
/** v1's status for an unlisted ?current= (dist/coastal-current-control.js, #402). */
export const UNSUPPORTED_CURRENT = 'Unsupported surface-current source. Choose a listed source.';

const clamp = (value: number, min: number, max: number): number => Math.max(min, Math.min(max, value));
/** The span-to-zoom rule v1 uses between its chart and the terrain (§ 3A.1): zoom 12 shows 7.3 km. */
export const zoomForSpan = (span: number): number => clamp(12 - Math.log2(span / 7300), 7, 18);
/** The inverse, clamped to the spans v1 sends the renderer. */
export const spanForZoom = (zoom: number): number => clamp(7300 * 2 ** (12 - zoom), 1200, 245000);

/** "latitude,longitude,zoom" from `?view=`; null for a masthead view or anything malformed. */
export function parseCamera(value: string | null): Camera | null {
  const parts = (value ?? '').split(',');
  if (parts.length !== 3 || parts.some(p => p.trim() === '')) return null;
  const [latitude, longitude, zoom] = parts.map(Number) as [number, number, number];
  if (![latitude, longitude, zoom].every(Number.isFinite) || Math.abs(latitude) > 90 || Math.abs(longitude) > 180) return null;
  return {latitude, longitude, zoom: clamp(zoom, 0, 22)};
}
export const cameraParam = (c: Camera): string => `${c.latitude.toFixed(5)},${c.longitude.toFixed(5)},${Math.round(c.zoom * 100) / 100}`;
/** The renderer's location for a camera. */
export const locationFor = (c: Camera): CoastLocation => ({latitude: c.latitude, longitude: c.longitude, span: spanForZoom(c.zoom)});

/** The renderer's species for the store's target, or the profile's default target. */
export function coastSpecies(target: string | null, p: Profile): string {
  const id = target || PROFILE_TABLE[p].defaultTarget;
  return coastTarget(id) ?? id;
}
/** `?hour=` as a Date; without one, the current whole UTC hour (the dock's "now"). */
export function terrainHour(value: string | null, now: Date): Date {
  const seconds = parseHour(value);
  return new Date(seconds !== null ? seconds * 1000 : Math.floor(now.getTime() / 3_600_000) * 3_600_000);
}

export interface TerrainInput {
  profile: Profile; target: string | null; hour: string | null; camera: Camera | null; current: CurrentChoice;
  habitat: string | null; presentation: Presentation; appView: AppView; hidden: boolean; now: Date;
}
/** What the terrain handle is told, in the order v1 applies it (CoastInitialState). */
export interface TerrainState {
  currentLayer: CurrentLayer; species: string; depthLimit: number; location: CoastLocation | null;
  hour: Date; perspective: CoastPerspective; habitat: string | null; visible: boolean;
}

/** The store-to-renderer half of § 3A.2's flow table. `presentation` is what the stage shows. */
export function terrainState(i: TerrainInput): TerrainState {
  return {
    // An unlisted source draws nothing, as in v1; the status line says why.
    currentLayer: i.current === UNSUPPORTED ? 'off' : i.current,
    species: coastSpecies(i.target, i.profile), depthLimit: terrainDepthLimitFt(i.profile),
    location: i.camera ? locationFor(i.camera) : null, hour: terrainHour(i.hour, i.now),
    perspective: i.presentation === '2d' ? '2d' : '3d', habitat: i.habitat,
    visible: i.appView === 'coast' && !i.hidden && i.presentation !== 'chart',
  };
}

/** What the dynamic import of web/map/terrain.js provides. */
export interface TerrainModule {
  mountCoast(host: HTMLElement, options: CoastMountOptions): CoastHandle;
  readonly styles: readonly string[];
}
export type TerrainLoader = () => Promise<TerrainModule>;
const loadTerrain: TerrainLoader = () => import('./terrain.js');

export interface StageOptions {
  /** The element whose shadow root the terrain mounts into. */
  host: HTMLElement;
  load?: TerrainLoader;
  /** Renderer colours read from the tokens (web/map/palette.ts). */
  palette?: () => Partial<CoastPalette> | undefined;
  /** The region's centre; a signal read here is followed. */
  center?: () => readonly [number, number] | null;
  now?: () => Date;
  doc?: Pick<Document, 'hidden' | 'addEventListener' | 'removeEventListener'>;
  /** Milliseconds a terrain camera move waits before it is written to `?view=`. */
  viewDelay?: number;
}

/** The shared camera: `?view=` when it names one, else the region's centre at HOME_ZOOM. FE-11's Chart reads it too. */
export const camera = signal<Camera | null>(null);
/** Sticky for the page: v1 also keeps the chart after a graphics failure until a reload. */
export const terrainFailed = signal(false);
/** What the stage draws: the requested presentation where terrain exists and has not failed, else Chart. */
export const shownPresentation = computed<Presentation>(() => terrainFailed.value ? 'chart' : stagePresentation.value);
/**
 * Why the terrain choices are disabled (a graphics failure, or no terrain here), or null when they
 * are offered. The stage's status line shows it; while the terrain loads, the renderer's own
 * status (#loading) speaks instead.
 */
export const terrainBlocked = computed<string | null>(() =>
  terrainFailed.value ? UNAVAILABLE : region.value && hasCoastTerrain(region.value) ? null : NO_TERRAIN);
/** The renderer's surface-current status, for the rail's Currents entry (FE-15). */
export const currentStatus = signal('');
/** The admitted terrain habitat selection, for the mark card. */
export const terrainMark = signal<CoastSelection | null>(null);
const pageHidden = signal(false);

export interface Stage {destroy(): void}

const key = (value: unknown): string => JSON.stringify(value);
const ORDER = ['currentLayer', 'species', 'depthLimit', 'location', 'hour', 'perspective', 'habitat', 'visible'] as const;

/** Go to a presentation, with a history entry (v2 writes `presentation=chart` explicitly). */
export const choosePresentation = (next: Presentation): void => { navigate(withParams(location.href, {presentation: next})); };

export function createStage(options: StageOptions): Stage {
  const {host, load = loadTerrain, now = () => new Date(), doc = document, viewDelay = 400} = options;
  const handle = signal<CoastHandle | null>(null);
  let applied: Partial<Record<keyof TerrainState, string>> = {};
  let mounting = false, alive = true, viewTimer: ReturnType<typeof setTimeout> | undefined;

  const wanted = computed(() => terrainState({
    profile: profile.value, target: species.value, hour: hour.value, camera: camera.value, current: current.value,
    habitat: habitat.value, presentation: shownPresentation.value, appView: appView.value, hidden: pageHidden.value, now: now(),
  }));

  const apply = (h: CoastHandle, state: TerrainState): void => {
    for (const name of ORDER) {
      const value = state[name], k = key(value);
      if (applied[name] === k) continue;
      applied[name] = k;
      if (name === 'currentLayer') h.setCurrentLayer(state.currentLayer);
      else if (name === 'species') h.setSpecies(state.species);
      else if (name === 'depthLimit') h.setDepthLimit(state.depthLimit);
      else if (name === 'location') { if (state.location) h.setLocation(state.location); }
      else if (name === 'hour') h.setHour(state.hour);
      else if (name === 'perspective') h.setPerspective(state.perspective);
      else if (name === 'habitat') h.selectHabitat(state.habitat);
      else h.setVisible(state.visible);
    }
  };

  const release = (): void => {
    const h = handle.peek();
    handle.value = null; applied = {}; terrainMark.value = null;
    h?.destroy();
  };
  const fail = (error: unknown): void => {
    console.error('Coastal presentation unavailable', error);
    release();
    // A renderer that threw while mounting leaves its scene behind; the root is the stage's alone.
    host.shadowRoot?.replaceChildren();
    terrainFailed.value = true;
  };
  const home = (): Camera | null => {
    const c = options.center?.();
    return c ? {latitude: c[0], longitude: c[1], zoom: HOME_ZOOM} : null;
  };

  async function mount(): Promise<void> {
    if (mounting || handle.peek() || terrainFailed.peek()) return;
    mounting = true;
    try {
      const terrain = await load();
      if (!alive) return;
      const state = wanted.peek();
      const h = terrain.mountCoast(host, {
        styles: terrain.styles, hostCurrents: true, palette: options.palette?.(),
        forecastHref: withParams(location.href, {view: 'conditions'}),
        initial: {...state, location: state.location ?? undefined},
        onSelection: picked => {
          terrainMark.value = picked;
          if (!picked.id || picked.id === habitat.peek()) return;
          applied.habitat = key(picked.id);
          navigate(withParams(location.href, {habitat: picked.id}));
        },
        onRestoredSelection: picked => { terrainMark.value = picked; },
        // As v1: an invalidated selection leaves ?habitat= in the link; the close button clears it.
        onSelectionInvalidated: () => { terrainMark.value = null; },
        onCloseSelection: () => {
          terrainMark.value = null; applied.habitat = key(null);
          handle.peek()?.selectHabitat(null);
          setParams({habitat: null});
        },
        onReset: () => {
          const next = home();
          if (next) setParams({view: cameraParam(next)});
        },
        onCurrentStatus: text => { if (current.peek() !== UNSUPPORTED) currentStatus.value = text; },
        onView: seen => {
          if (appView.peek() !== 'coast') return;
          const next = parseCamera(cameraParam({latitude: seen.latitude, longitude: seen.longitude, zoom: zoomForSpan(seen.span)}));
          if (!next) return;
          // The renderer is already there: mark its location applied so the camera is not sent back.
          applied.location = key(locationFor(next));
          camera.value = next;
          clearTimeout(viewTimer);
          viewTimer = setTimeout(() => { if (alive && appView.peek() === 'coast') setParams({view: cameraParam(next)}); }, viewDelay);
        },
        onPerspective: mode => {
          applied.perspective = key(mode);
          if (presentation.peek() !== mode) setParams({presentation: mode});
        },
      });
      for (const name of ORDER) applied[name] = key(state[name]);
      handle.value = h;
      const ready = await h.load();
      if (alive && !ready) fail(new Error('Coastal terrain did not load'));
    } catch (error) {
      if (alive) fail(error);
    } finally {
      mounting = false;
    }
  }

  const visibility = (): void => { pageHidden.value = !!doc.hidden; };
  visibility();
  doc.addEventListener('visibilitychange', visibility);
  const disposers = [
    effect(() => { const c = parseCamera(view.value); if (c) camera.value = c; }),
    // A new region (or its centre arriving) moves the camera home unless the link names one.
    effect(() => { const next = home(); if (next && !parseCamera(view.peek())) camera.value = next; }),
    // The first terrain choice mounts the renderer; Chart only hides it (setVisible), so switching back is instant.
    effect(() => { if (shownPresentation.value !== 'chart') void mount(); }),
    effect(() => { const h = handle.value, state = wanted.value; if (h) apply(h, state); }),
    effect(() => { if (current.value === UNSUPPORTED) currentStatus.value = UNSUPPORTED_CURRENT; else if (current.value === 'off') currentStatus.value = ''; }),
  ];
  return {
    destroy() {
      if (!alive) return;
      alive = false;
      clearTimeout(viewTimer);
      for (const dispose of disposers) dispose();
      doc.removeEventListener('visibilitychange', visibility);
      release();
    },
  };
}
