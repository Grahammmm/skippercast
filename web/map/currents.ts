// The Chart's Currents layer (FE-15, docs/plans/front-end/design.md § 9): the
// surface-current source chosen in the rail (`?current=`) drawn as dashed,
// animated streamlines (web/map/flow.ts) on two canvases over the Chart, a
// still one (faint paths, arrowheads, source cells) and one for the dashes.
//
// - Data: the ocean packet of the coast data client (web/coast-data.ts, FE-74),
//   requested only while a source is chosen, for the region's place when it
//   binds a local report (Morro Bay and Cambria today). Elsewhere the rail says
//   no packet covers the region and nothing draws.
// - Frames: exactly the chosen product at the dock's hour through frames.ts
//   (packages/coast `selectedCurrent`, `selectCurrentFrame`). Without a fresh
//   frame nothing draws and the rail and legend give the reason and the last
//   frame the source published at or before that hour. A drawn frame is
//   withdrawn at its own deadline (`expiresAt`) without any interaction.
// - Land: paths, arrowheads and source dots stop at the basemap's land, read
//   from the tiles in view once the map is idle.
// - Motion: paths are rebuilt only when the map settles, and the dashes advance
//   20 times a second while the page is visible, the Chart is shown and the
//   map is still. Under prefers-reduced-motion they stand still.
//
// Erasable syntax only: tests/test_flow.mjs drives it with a fake map view.
import {computed, effect, signal} from '@preact/signals';
import {coastData, type CoastData, type CoastStatus} from '../coast-data.ts';
import type {OceanData} from '../../packages/coast/src/ocean-types.ts';
import type {CoastReportContext, ReportLocalArea} from '../../packages/coast/src/state/report-binding.ts';
import type {Profile} from '../profile.ts';
import {appView, current, day, hour, UNSUPPORTED, type CurrentChoice} from '../state.ts';
import type {ChartMark} from './coastline.ts';
import type {MapView} from './engine.ts';
import {drawBase, drawDashes, fastSpeed, flowPaths, frameField, screenVector, type FlowPath} from './flow.ts';
import {chosenCurrent, type CurrentField, type CurrentFrame} from './frames.ts';
import {layerEntry} from './layers.ts';
import type {Palette} from './palette.ts';
import {shownPresentation, terrainHour, UNSUPPORTED_CURRENT} from './stage.ts';
import {vectorReading, type SurfaceField} from './surface-field.js';

type Drawn = {field: CurrentField; frame: CurrentFrame; expiresAt: number};
export interface CurrentsStatus {
  /** The frame drawn, or null: nothing draws. */
  readonly drawn: Drawn | null;
  /** The rail's short note. */
  readonly note: string;
  /** Why nothing draws, for the legend; '' when a frame draws or the source is off. */
  readonly reason: string;
  /** One sentence: product, resolution, age, and what the arrows mean (D13). */
  readonly basis: string;
}

/** The rail's source choices, with v1's labels (dist/coastal-current-control.js). */
export const CURRENT_SOURCES = [
  {value: 'off', label: 'Off'}, {value: 'wcofs', label: 'NOAA WCOFS forecast'},
  {value: 'hfr-1', label: 'Observed HF radar · 1 km'}, {value: 'hfr-6', label: 'Observed HF radar · 6 km'},
] as const;
const MOTION = 'arrows follow the toward-bearing and their motion is illustrative';
export const CURRENTS_BASIS = layerEntry('currents').basis;
const OFF: CurrentsStatus = {drawn: null, note: '', reason: '', basis: CURRENTS_BASIS};
/**
 * The dashes move 20 times a second (fish's rate): a display's frames arrive a few ms early or
 * late, so a frame within 4 ms of the budget paints. Measured in headless Chromium (software
 * rendering, 63 paths): under 1 ms of script per paint.
 */
export const FRAME_MS = 50;
const HOUR_MS = 3_600_000;

/** "4 min", "3 h", "2 d". */
const age = (ms: number): string => { const m = Math.max(0, Math.floor(ms / 60000)); return m < 60 ? `${m} min` : m < 2880 ? `${Math.floor(m / 60)} h` : `${Math.floor(m / 1440)} d`; };
/** "Tue 2 pm" in the region's zone, as the dock reads. */
export const frameTime = (iso: string, tz: string): string =>
  new Intl.DateTimeFormat('en-US', {timeZone: tz, weekday: 'short', hour: 'numeric'}).format(new Date(iso)).replace(',', '').replace('AM', 'am').replace('PM', 'pm');
const km = (value: number): string => String(Math.round(value * 10) / 10);

/** The basis of a drawn source: forecast cycle or observation time, with its age at `now`. */
export function sourceBasis(d: Drawn, now: Date): string {
  const {field, frame} = d;
  return field.kind === 'forecast'
    ? `NOAA WCOFS surface forecast, about ${km(field.nativeResolutionKm)} km, issued ${age(now.getTime() - Date.parse(field.issuedAt ?? ''))} ago; ${MOTION}.`
    : `HF radar surface observation, ${km(field.nativeResolutionKm)} km, observed ${age(now.getTime() - Date.parse(frame.validAt))} ago; ${MOTION}.`;
}

/** The latest frame the chosen product lists at or before `at`, or null. */
function lastFrame(fields: readonly unknown[], choice: string, at: Date): string | null {
  const field = fields.filter(f => (f as {id?: unknown})?.id === choice);
  const frames = field.length === 1 ? (field[0] as {frames?: unknown}).frames : null;
  if (!Array.isArray(frames)) return null;
  const times = frames.map(f => (f as {validAt?: unknown})?.validAt).filter((t): t is string => typeof t === 'string' && Date.parse(t) <= at.getTime());
  return times.sort((a, b) => Date.parse(a) - Date.parse(b)).at(-1) ?? null;
}

/** What the layer shows for a source choice, the packet's state and the dock's hour `at`. */
export function currentsStatus(choice: CurrentChoice, status: CoastStatus, ocean: OceanData | null, at: Date, now: Date, tz: string): CurrentsStatus {
  if (choice === 'off') return OFF;
  if (choice === UNSUPPORTED) return {...OFF, note: 'unsupported source', reason: UNSUPPORTED_CURRENT};
  if (status === 'unbound') return {...OFF, note: 'no packet for this region', reason: 'Currents unavailable: no local surface-current packet covers this region yet.'};
  if (status === 'error' || status === 'invalid') return {...OFF, note: 'unavailable', reason: 'Currents unavailable: the surface-current packet failed to load, and no other source is shown.'};
  if (status === 'expired') return {...OFF, note: 'expired', reason: 'Currents unavailable: the surface-current packet passed its age limit, and no other source is shown.'};
  if (!ocean) return {...OFF, note: 'loading', reason: 'Loading the surface-current packet.'};
  const drawn = chosenCurrent(ocean.currents, choice, at, now);
  if (drawn) return {drawn, note: `${drawn.field.kind === 'forecast' ? 'forecast' : 'observed'} ${frameTime(drawn.frame.validAt, tz)}`, reason: '', basis: sourceBasis(drawn, now)};
  const last = lastFrame(ocean.currents, choice, at), name = CURRENT_SOURCES.find(s => s.value === choice)?.label ?? choice;
  return {...OFF, note: `no fresh frame${last ? ` · last ${frameTime(last, tz)}` : ''}`,
    reason: `Currents unavailable: no fresh ${name} frame for this hour${last ? `; the last was valid ${frameTime(last, tz)}` : ''}.`};
}

/** The mark card's reading at a clicked point inside the drawn field, or null outside it. */
export function currentMark(d: Drawn, field: SurfaceField, at: {lon: number; lat: number}, tz: string, now: Date): ChartMark | null {
  const v = field.sample(at.lon, at.lat);
  if (!v) return null;
  const r = vectorReading(v), forecast = d.field.kind === 'forecast';
  return {
    id: `current:${d.field.id}:${d.frame.validAt}`, name: 'Surface current',
    kind: `${forecast ? 'Forecast' : 'Observed'} · valid ${frameTime(d.frame.validAt, tz)}`,
    reading: `${r.speedKnots.toFixed(2)} kt toward ${Math.round(r.towardDeg)}° true`,
    source: `${d.field.label} · ${forecast ? `issued ${age(now.getTime() - Date.parse(d.field.issuedAt ?? ''))}` : `observed ${age(now.getTime() - Date.parse(d.frame.validAt))}`} ago`,
    basis: `${sourceBasis(d, now)} Blended from adjacent wet cells; surface flow, not bottom current or boat drift.`,
  };
}

/**
 * The report place for a region: its centre among its reviewed local areas, so the packet binds
 * for the region as a whole (Morro Bay's centre lies in Estero Bay), not wherever the map is panned.
 */
export function regionPlace(region: {id: string; center: readonly [number, number]; localAreas?: readonly ReportLocalArea[]} | null, profile: Profile, target: string): CoastReportContext | null {
  return region ? {regionId: region.id, point: {latitude: region.center[0], longitude: region.center[1]}, localAreas: region.localAreas ?? [], profile, target, at: new Date()} : null;
}

/** What the rail and legend show while the Chart draws the layer. */
export const currentsState = signal<CurrentsStatus>(OFF);

type Doc = Pick<Document, 'hidden' | 'addEventListener' | 'removeEventListener' | 'createElement'>;
export interface CurrentsOptions {
  view: MapView;
  palette: () => Palette;
  zone?: () => string;
  /** The region's report context, or null until the region is known. */
  place?: () => CoastReportContext | null;
  data?: Pick<CoastData, 'coastOcean' | 'coastStatus' | 'setPlace' | 'load'>;
  doc?: Doc;
  motion?: Pick<MediaQueryList, 'matches' | 'addEventListener' | 'removeEventListener'> | null;
  frames?: {request(step: (t: number) => void): number; cancel(id: number): void};
  now?: () => Date;
}
export interface Currents {reading(at: {lon: number; lat: number}): ChartMark | null; destroy(): void}

/** Land as a coarse raster (quarter scale) of the basemap's land polygons in view. */
function landMask(view: MapView, width: number, height: number, doc: Doc): (x: number, y: number) => boolean {
  const rings = view.land(), w = Math.ceil(width / 4), h = Math.ceil(height / 4);
  const ctx = rings.length && w && h ? Object.assign(doc.createElement('canvas'), {width: w, height: h}).getContext('2d', {willReadFrequently: true}) : null;
  if (!ctx) return () => false;
  ctx.beginPath();
  for (const ring of rings) ring.forEach(([lon = 0, lat = 0], i) => { const p = view.project(lon, lat); if (i) ctx.lineTo(p.x / 4, p.y / 4); else ctx.moveTo(p.x / 4, p.y / 4); });
  ctx.fill('nonzero');
  const alpha = ctx.getImageData(0, 0, w, h).data;
  return (x, y) => (alpha[(Math.floor(y / 4) * w + Math.floor(x / 4)) * 4 + 3] ?? 0) > 127;
}

export function createCurrents(o: CurrentsOptions): Currents {
  const {view, data = coastData, now = () => new Date(), zone = () => 'America/Los_Angeles'} = o;
  const doc = o.doc ?? (typeof document === 'undefined' ? null : document);
  const motion = o.motion !== undefined ? o.motion : typeof matchMedia === 'function' ? matchMedia('(prefers-reduced-motion: reduce)') : null;
  const frames = o.frames ?? {request: step => requestAnimationFrame(step), cancel: id => cancelAnimationFrame(id)};
  const tick = signal(0), hidden = signal(!!doc?.hidden), reduced = signal(!!motion?.matches);
  const status = computed(() => {
    void tick.value;
    const at = terrainHour(hour.value, now(), day.value, zone()), known = o.place?.() !== null;
    return currentsStatus(current.value, known ? data.coastStatus.value.ocean : 'loading', data.coastOcean.value?.data ?? null, at, now(), zone());
  });
  const shown = computed(() => status.value.drawn !== null && shownPresentation.value === 'chart' && appView.value === 'coast');
  const drawnKey = computed(() => { const d = status.value.drawn; return d ? `${d.field.id}|${d.field.fetchedAt}|${d.frame.validAt}` : ''; });
  const field = computed(() => { void drawnKey.value; const d = status.peek().drawn; return d ? frameField(d.field, d.frame) : null; });

  let base: HTMLCanvasElement | null = null, dash: HTMLCanvasElement | null = null, paths: FlowPath[] = [];
  let frameId = 0, last = 0, moving = false, timer: ReturnType<typeof setTimeout> | undefined, unlisten: (() => void)[] = [];
  const dpr = (): number => Math.min(2, (typeof devicePixelRatio === 'number' && devicePixelRatio) || 1);
  const colours = () => { const p = o.palette(); return {flow: p.flow, fast: p.flowFast}; };
  const context = (c: HTMLCanvasElement): CanvasRenderingContext2D | null => {
    const ctx = c.getContext('2d');
    ctx?.setTransform(dpr(), 0, 0, dpr(), 0, 0);
    ctx?.clearRect(0, 0, c.width, c.height);
    return ctx;
  };
  const mark = (state: 'animated' | 'still' | 'paused'): void => { if (dash) { dash.dataset.motion = state; dash.dataset.paths = String(paths.length); } };
  const running = (): boolean => shown.peek() && !hidden.peek() && !moving && !reduced.peek() && paths.length > 0;

  function stop(): void { if (frameId) frames.cancel(frameId); frameId = 0; mark('paused'); }
  function paint(seconds: number): void { const ctx = dash && context(dash); if (ctx) drawDashes(ctx, paths, colours(), seconds); }
  function step(t: number): void {
    frameId = 0;
    if (!running()) { stop(); return; }
    frameId = frames.request(step);
    if (t - last < FRAME_MS - 4) return;
    last = t;
    paint(t / 1000);
  }
  function start(): void {
    if (reduced.peek() && paths.length) { stop(); paint(0); mark('still'); return; }
    if (running() && !frameId) frameId = frames.request(step);
    mark(running() ? 'animated' : 'paused');
  }
  function clear(): void {
    stop();
    paths = [];
    for (const c of [base, dash]) if (c) context(c);
    mark('paused');
  }
  function rebuild(): void {
    const d = status.peek().drawn, f = field.peek();
    if (!d || !f || !doc || !shown.peek() || moving) { clear(); return; }
    if (!base || !dash) {
      const make = (kind: string): HTMLCanvasElement => {
        const c = doc.createElement('canvas');
        c.className = `chart-flow chart-flow--${kind}`;
        c.setAttribute('aria-hidden', 'true');
        view.container().append(c);
        return c;
      };
      base = make('base'); dash = make('dash');
    }
    const {width, height} = view.size();
    for (const c of [base, dash]) { c.width = Math.round(width * dpr()); c.height = Math.round(height * dpr()); }
    const land = landMask(view, width, height, doc);
    paths = flowPaths(screenVector(f, view.unproject, land), width, height, fastSpeed(d.frame));
    const ctx = context(base);
    if (ctx) drawBase(ctx, paths, colours(), d.frame.cells.map(c => view.project(c.lon, c.lat)).filter(p => !land(p.x, p.y)));
    start();
  }

  const visibility = (): void => { hidden.value = !!doc?.hidden; tick.value++; if (hidden.peek()) stop(); else start(); };
  const motionChange = (): void => { reduced.value = !!motion?.matches; stop(); start(); };
  doc?.addEventListener('visibilitychange', visibility);
  motion?.addEventListener('change', motionChange);

  const disposers = [
    // Request the packet only while a source is chosen, for the region's place once it is known.
    effect(() => {
      const choice = current.value, place = o.place?.() ?? null;
      if (choice === 'off' || choice === UNSUPPORTED || !place) return;
      data.setPlace(place);
      void data.load('ocean');
    }),
    effect(() => { currentsState.value = status.value; }),
    // Re-judge the frame at its own deadline and at the next whole hour (the dock's default hour moves on).
    effect(() => {
      const s = status.value, t = now().getTime();
      clearTimeout(timer);
      if (current.value === 'off') return;
      const due = Math.min(s.drawn ? s.drawn.expiresAt : Infinity, (Math.floor(t / HOUR_MS) + 1) * HOUR_MS);
      timer = setTimeout(() => { tick.value++; }, Math.min(Math.max(1000, due - t + 1000), 2 ** 31 - 1));
    }),
    // `off`, another view or presentation, or a lost frame clears at once; a new frame rebuilds.
    effect(() => {
      void drawnKey.value;
      if (shown.value) {
        if (!unlisten.length) unlisten = [
          view.on('movestart', () => { moving = true; clear(); }),
          // `idle`, not `moveend`: the basemap's land in view has loaded by then, so the mask is complete.
          view.on('idle', () => { moving = false; rebuild(); }),
          view.on('resize', rebuild),
        ];
        // Until the map is idle the land in view may be missing: draw then.
        moving = view.busy();
        rebuild();
      } else {
        for (const off of unlisten) off();
        unlisten = [];
        clear();
      }
    }),
  ];

  return {
    reading(at) {
      const d = status.peek().drawn, f = field.peek();
      return d && f && shown.peek() ? currentMark(d, f, at, zone(), now()) : null;
    },
    destroy() {
      for (const dispose of disposers) dispose();
      for (const off of unlisten) off();
      clearTimeout(timer);
      stop();
      base?.remove(); dash?.remove();
      doc?.removeEventListener('visibilitychange', visibility);
      motion?.removeEventListener('change', motionChange);
      currentsState.value = OFF;
    },
  };
}
