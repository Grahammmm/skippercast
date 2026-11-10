// MAPLIVE-1: the private map-style preview layers on the real Chart. Seafloor medium relief, wind particle
// trails, HF-radar currents, sea-surface temperature and chlorophyll were built on research test pages
// (research/scripts/map_style/); this file makes them reachable from the app map without changing what any
// visitor sees.
//   Private: the control, the legend rows and every request exist only for the owner/admin session
//     (/api/session `is_admin`, the same server answer the admin pages use; web/account.ts `sessionAdmin`). Their data
//     files are the private local build output (`var/...`) that scripts/client-build.mjs never publishes, so a
//     deployed site answers 404 for them and these layers then read "unavailable".
//   Off by default: `previewOn` starts empty, lives in memory only (not in the link, the profile or storage).
//   Lazy: this file imports no layer code and fetches nothing. A layer's module and data are requested only
//     when its switch turns on, and its overlay is removed when the switch turns off or the gate closes.
// Not for navigation. No vessel positions. Erasable syntax only: tests/test_preview_layers.mjs imports this file.
import {effect, signal, type ReadonlySignal} from '@preact/signals';
import {session, sessionAdmin} from '../account.ts';
import type {Engine} from './engine.ts';
import {readPalette, type Palette} from './palette.ts';

export const PREVIEW_IDS = ['seafloor', 'wind', 'currents', 'sst', 'chlorophyll'] as const;
export type PreviewId = typeof PREVIEW_IDS[number];

/** The private local files (git-ignored `var/`), relative to the page. Never listed in a manifest or published. */
export const PREVIEW_DATA: Readonly<Record<PreviewId, string>> = {
  seafloor: '/var/seafloor/tiles/morro-bay-seafloor-deep-medium.pmtiles',
  wind: '/var/maplayer-wind-1/wind-preview.json',
  currents: '/var/currents/hfr-central-coast-6km.json',
  sst: '/var/maplayer-sst-1/sst-preview.json',
  chlorophyll: '/var/chlorophyll/central-coast/chlorophyll.json',
};

export interface PreviewMeta {
  readonly id: PreviewId;
  readonly label: string;
  /** What it shows, its source and its limits: one honest sentence (shown in the legend row). */
  readonly basis: string;
  /** The map-style study's pick (G, 2026-11-06). */
  readonly style: string;
}

// TODO(SCFEAT-FRESH-1, PR 1759): when that PR lands, add each layer's "Updates: <cadence>" line from
// web/map/freshness.ts to these rows. Until then each row shows the data's own time and age, which the layer reads from its file.
export const PREVIEW_LAYERS: readonly PreviewMeta[] = [
  {id: 'seafloor', label: 'Seafloor relief (medium)', style: 'medium relief, 2 m shallow bathymetry',
    basis: 'Morro Bay 10 m survey and 2 m shallow bathymetry as shaded relief. Tan or clear = no survey, not a depth. Mixed vertical references.'},
  {id: 'wind', label: 'Wind trails', style: 'wind 3, particle trails',
    basis: 'NOAA model wind at 10 m on a 0.25° grid, drawn as moving trails. It is a forecast, and the trails are tracers rather than forecast paths. Withheld after an 18 h run age.'},
  {id: 'currents', label: 'Surface currents (HF radar)', style: 'current 5, spin tint with streamlines',
    basis: 'HF-radar surface flow, 6 km grid. Drawn only where all four surrounding cells hold a radar vector; no vector = nothing drawn.'},
  {id: 'sst', label: 'Sea-surface temperature', style: 'SST 2, 14 bands with strong-break lines',
    basis: 'NOAA CoastWatch / GHRSST native cells, 52 to 66 °F. A surface analysis, not bottom temperature; clear = no cell.'},
  {id: 'chlorophyll', label: 'Chlorophyll (satellite)', style: 'chlorophyll 4, log scale',
    basis: 'Satellite surface chlorophyll in about 4 km cells on a log scale. Clear means no reading (cloud or land), which differs from zero. It is no sign of bait or fish.'},
];

/** Where a switched-on layer stands. `stale` and `unavailable` draw nothing. */
export interface PreviewStatus {
  readonly state: 'loading' | 'ready' | 'stale' | 'unavailable';
  readonly text: string;
  /** The data's own time (ISO), never the load time. */
  readonly dataTime?: string;
  /** A legend colour ramp, low to high, with its end labels. */
  readonly ramp?: {readonly colours: readonly string[]; readonly low: string; readonly high: string};
}

export interface PreviewContext {
  readonly engine: Engine;
  readonly fetchFn: typeof fetch;
  readonly now: () => Date;
  /** The design tokens, read when a layer draws (never a colour literal). */
  readonly palette: () => Palette;
  /** Resolves a private path against the page. */
  readonly url: (path: string) => string;
  /** Aborts when the layer is switched off or the gate closes; a late answer must draw nothing. */
  readonly signal: AbortSignal;
  readonly report: (status: PreviewStatus) => void;
}
export interface PreviewHandle {destroy(): void}
export type PreviewAttach = (context: PreviewContext) => Promise<PreviewHandle | null>;
/** A layer's loader: the dynamic import is the only place its code is requested. */
export type PreviewLoader = () => Promise<PreviewAttach>;

/**
 * The registry owner name each layer's failures arrive under (web/map/engine.ts routes a failed source to the overlay that
 * contains it, so SST's secondary sources and currents' lines and heads report as the cells / tint owner). Strings only, so
 * this file stays free of layer code. Wind is a canvas layer, not an Engine overlay: its marker is kept for compatibility.
 */
export const PREVIEW_OWNERS: Readonly<Record<PreviewId, string>> = {
  seafloor: 'preview-seafloor',
  wind: 'preview-wind',
  currents: 'preview-currents-tint',
  sst: 'preview-sst-cells',
  chlorophyll: 'preview-chlorophyll',
};

export const PREVIEW_LOADERS: Readonly<Record<PreviewId, PreviewLoader>> = {
  seafloor: async () => (await import('./preview/seafloor.ts')).attach,
  wind: async () => (await import('./preview/wind.ts')).attach,
  currents: async () => (await import('./preview/currents.ts')).attach,
  sst: async () => (await import('./preview/sst.ts')).attach,
  chlorophyll: async () => (await import('./preview/chlorophyll.ts')).attach,
};

const SAFE_COLOUR = /^(?:#[0-9a-f]{3,8}|rgb\(\s*\d{1,3}(?:\s*,\s*\d{1,3}){2}\s*\))$/i;
/** A ramp's CSS gradient from file-supplied colours; any value that is not a plain hex or rgb() colour drops the ramp. */
export function rampGradient(colours: readonly string[]): string | null {
  return colours.length >= 2 && colours.every(c => SAFE_COLOUR.test(c)) ? `linear-gradient(to right, ${colours.join(', ')})` : null;
}

/** The gate: only a signed-in session the server called admin. Anyone else, and the loading state, is closed. */
export const previewAccess = (s = session.value, admin = sessionAdmin.value): boolean => s.state === 'signed-in' && admin;

/** The layers switched on, in `PREVIEW_IDS` order. Empty at start; memory only. */
export const previewOn = signal<readonly PreviewId[]>([]);
export const previewStatus = signal<Readonly<Partial<Record<PreviewId, PreviewStatus>>>>({});

/** Switch a layer on or off. Ignored without the gate, so no caller can turn one on for another viewer. */
export function togglePreview(id: PreviewId, on: boolean, allowed: boolean = previewAccess()): void {
  if (!allowed || !PREVIEW_IDS.includes(id)) return;
  const set = new Set(previewOn.peek());
  if (on) set.add(id); else set.delete(id);
  previewOn.value = PREVIEW_IDS.filter(x => set.has(x));
}

const setStatus = (id: PreviewId, status: PreviewStatus | null): void => {
  const next = {...previewStatus.peek()};
  if (status) next[id] = status; else delete next[id];
  previewStatus.value = next;
};

/**
 * The Chart layer (web/app/MapStage.tsx): follows `previewOn` and the gate. Nothing is imported or requested until
 * a layer is on, a layer that goes off (or a closed gate) is destroyed, and a switch-off while loading aborts the load.
 */
export function createPreviewLayers(o: {
  engine: ReadonlySignal<Engine | null>; fetchFn?: typeof fetch; now?: () => Date; page?: () => string; palette?: () => Palette;
  loaders?: Readonly<Record<PreviewId, PreviewLoader>>; access?: () => boolean;
  /** Registry layers the Chart marked unavailable (web/map/chart.ts `unavailable`), and how to forget one. A source that fails after attach (a missing image, an unreadable archive) arrives here. */
  failures?: {readonly list: ReadonlySignal<readonly string[]>; clear(layer: string): void};
}) {
  const {fetchFn = (...args: Parameters<typeof fetch>) => fetch(...args), now = () => new Date(), page = () => location.href,
    loaders = PREVIEW_LOADERS, access = () => previewAccess(), palette = () => readPalette()} = o;
  const live = new Map<PreviewId, {engine: Engine; abort: AbortController; handle: PreviewHandle | null; failed: boolean}>();
  const stop = (id: PreviewId): void => {
    const item = live.get(id);
    if (!item) return;
    live.delete(id);
    item.abort.abort();
    try { item.handle?.destroy(); } catch { /* the map may already be gone */ }
    setStatus(id, null);
  };
  const FAILED = 'the map could not load this layer\'s image or tiles';
  /** A source failed after the layer reported ready: draw nothing and read unavailable, not ready. */
  function fail(id: PreviewId, item: {handle: PreviewHandle | null; failed: boolean}): void {
    item.failed = true;
    try { item.handle?.destroy(); } catch { /* the map may already be gone */ }
    item.handle = null;
    setStatus(id, {state: 'unavailable', text: `Unavailable: ${FAILED}. Nothing is drawn.`});
  }
  async function start(id: PreviewId, engine: Engine): Promise<void> {
    const abort = new AbortController(), item = {engine, abort, handle: null as PreviewHandle | null, failed: false};
    live.set(id, item);
    o.failures?.clear(PREVIEW_OWNERS[id]);
    const report = (status: PreviewStatus): void => { if (live.get(id) === item) setStatus(id, status); };
    report({state: 'loading', text: 'Loading…'});
    try {
      const attach = await loaders[id]();
      if (abort.signal.aborted) return;
      const handle = await attach({engine, fetchFn, now, palette, url: path => new URL(path, page()).href, signal: abort.signal, report});
      if (abort.signal.aborted) { handle?.destroy(); return; }
      item.handle = handle;
      if (item.failed) fail(id, item);
    } catch (error) {
      if (!abort.signal.aborted) report({state: 'unavailable', text: `Unavailable: ${error instanceof Error ? error.message : 'could not load'}. Nothing is drawn.`});
    }
  }
  const dispose = effect(() => {
    const e = o.engine.value, on = previewOn.value, open = access();
    for (const id of [...live.keys()]) if (!e || !open || !on.includes(id) || live.get(id)!.engine !== e) stop(id);
    if (!e || !open) return;
    for (const id of on) if (!live.has(id)) void start(id, e);
  });
  const watch = o.failures ? effect(() => {
    const bad = o.failures!.list.value;
    for (const [id, item] of live) if (!item.failed && bad.includes(PREVIEW_OWNERS[id])) fail(id, item);
  }) : () => {};
  return {
    destroy() { dispose(); watch(); for (const id of [...live.keys()]) stop(id); },
  };
}
