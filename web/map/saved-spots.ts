// SC0922-04: a signed-in person's private saved spots on the Chart, off by default. The list is read once per
// session from GET /api/spots (the same route the planner's picker and the account panel read) and kept only in
// this page's memory, projected to an opaque pick key, a name and a point; the note, owner and date are dropped
// as the answer is parsed. The layer is a Chart-only choice that is not in the address, a share link, the
// profile defaults, a feed, an export or usage measurement. A pin is the person's own record, never a ranked or
// recommended fishing place: its card shows the shared protected-area reading (dist/geo-screen.js `screenPlace`,
// worded by web/waypoint-placement.ts `verdictLine`) and says so. Nothing runs, and nothing is asked, before the
// first explicit turn-on.
//
// Erasable syntax only: Node tests import this file.
import {computed, effect, signal, untracked, type ReadonlySignal} from '@preact/signals';
import {session as accountSession, type Session} from '../account.ts';
import {screenPlace, type PlaceVerdict} from '../../dist/geo-screen.js';
import {appView, region} from '../state.ts';
import {verdictLine, verdictParts} from '../waypoint-placement.ts';
import {language, t, type StringId} from '../i18n.ts';
import type {MarkCopyFields, MarkCopyPart} from '../mark-copy.ts';
import {sp, type StatusPart} from './status-copy.ts';
import type {ProtectedScreen} from '../trip.ts';
import type {ChartMark} from './coastline.ts';
import {EMPTY, regulationsLink, type Collection} from './habitat.ts';
import {SAVED_SPOTS_SOURCE, layerEntry} from './layers.ts';
import {markData, picked} from './marks.ts';
import type {Engine} from './engine.ts';
import type {Palette} from './palette.ts';
import {shownPresentation} from './stage.ts';
import {LABEL_FONT} from './style.ts';

export const SAVED_SPOT_PICK = 'saved-spot-pick';
export const SAVED_SPOT_PIN = 'saved-spot-pin';
const SAVED_SPOT_NAME = 'saved-spot-name';
/** The card id's prefix: ephemeral, and never a database id. */
export const SAVED_CARD_PREFIX = 'private-saved:';
/** A zero-detail event: something changed in the account's spots. It carries no row, id, name, point or note. */
export const SAVED_SPOTS_CHANGED = 'skippercast:saved-spots-changed';

export const STATUS_WORDS = {
  signedOut: 'Sign in to show your saved spots.',
  loadingAccount: 'Checking your account…',
  offline: 'Accounts need a connection.',
  disabled: 'Accounts are not available on this site.',
  off: 'Off. Turn it on to show your saved spots on the Chart.',
  loading: 'Loading your saved spots…',
  empty: 'No saved spots yet.',
  failed: 'Your saved spots could not be loaded. Try again.',
  ready: 'Your saved spots are shown only to you.',
} as const;
export const CARD_WORDS = {
  kind: 'Your saved spot · private',
  source: 'Your account',
  caveat: 'A saved position, not a recommendation. Check current rules before you fish.',
  clear: 'No protected-area overlap found in this check.',
  near: 'Within 70 m of a protected area.',
  unnamed: 'Unnamed spot',
} as const;

const MAX_SPOTS = 100, MAX_ID = 64, MAX_NAME = 80, READ_MS = 20000, REFRESH_MS = 60000;
const ID = /^[\w.-]{1,64}$/;
// eslint-disable-next-line no-control-regex
const CONTROLS = /[\u0000-\u001f\u007f-\u009f\u2028\u2029\ufffe\uffff]/g;

/** One saved spot as the layer keeps it: an opaque pick key, a display name and a point. Nothing else. */
/** `unnamed` is set only when the name was blank, so the fallback can be shown in the page's language; a person's own 'Unnamed spot' never has it. */
export interface SavedSpotRow {readonly key: string; readonly name: string; readonly latitude: number; readonly longitude: number; readonly unnamed?: true}

/** The list answer as rows, or null when anything about it is wrong: one malformed row, a repeat or a 101st fails the whole read. */
export function projectSavedSpots(data: unknown): SavedSpotRow[] | null {
  const list = data && typeof data === 'object' ? (data as {spots?: unknown}).spots : null;
  if (!Array.isArray(list) || list.length > MAX_SPOTS) return null;
  const seen = new Set<string>(), rows: SavedSpotRow[] = [];
  for (const raw of list) {
    const r = raw as {id?: unknown; name?: unknown; lat?: unknown; lon?: unknown} | null;
    if (!r || typeof r !== 'object' || typeof r.id !== 'string' || !ID.test(r.id) || seen.has(r.id) || typeof r.name !== 'string' || r.name.length > MAX_NAME
      || typeof r.lat !== 'number' || !(r.lat > -90 && r.lat < 90) || typeof r.lon !== 'number' || !(r.lon > -180 && r.lon < 180)) return null;
    seen.add(r.id);
    const name = r.name.replace(CONTROLS, '').trim();
    rows.push({key: `s${rows.length}`, name: name || CARD_WORDS.unnamed, latitude: r.lat, longitude: r.lon, ...(name ? {} : {unnamed: true as const})});
  }
  return rows;
}

type Read = {readonly who: Session | null; readonly state: 'idle' | 'loading' | 'ready' | 'failed'; readonly rows: readonly SavedSpotRow[]};
const NONE: Read = Object.freeze({who: null, state: 'idle', rows: []});

/** The choice: session-only, off at the start, and never written anywhere. */
export const savedSpotsOn = signal(false);
/** The page's one private list for the session it was read for, and the signal source the layer follows (the real session unless a test injects one). */
const store = signal<Read>(NONE);
const followed = signal<ReadonlySignal<Session>>(accountSession);
/** Bumped to ask the layer to evaluate the cards again (the shared screen changed, a minute passed, the tab came back). */
const tick = signal(0);
const screenState = signal<{region: string; loaded: ProtectedScreen} | null>(null);

const onChart = (): boolean => shownPresentation.value === 'chart' && appView.value === 'coast';
const signedIn = (s: Session): boolean => s.state === 'signed-in';
/** Whether pins may draw now: signed in as the session the list was read for, turned on, on the Chart, list ready. */
const drawable = computed(() => {
  const who = followed.value.value, read = store.value;
  return signedIn(who) && read.who === who && read.state === 'ready' && savedSpotsOn.value && onChart();
});

export interface SavedSpotsStatus {
  readonly text: string; /** Whether the checkbox may be changed. */ readonly canToggle: boolean; readonly retry: boolean;
  /** SC1352-06: the same words as catalogue parts, which the legend shows in the page's language. `text` stays the English. */
  readonly copy?: readonly StatusPart[];
}
const statusOf = (key: keyof typeof STATUS_WORDS, canToggle: boolean, retry: boolean): SavedSpotsStatus =>
  ({text: STATUS_WORDS[key], canToggle, retry, copy: [sp(`savedSpots.status.${key}` as StringId)]});
/** What the legend row says and allows. Never a count or a private value. */
export const savedSpotsStatus = computed<SavedSpotsStatus>(() => {
  const who = followed.value.value, read = store.value;
  if (who.state === 'signed-out') return statusOf('signedOut', false, false);
  if (who.state === 'loading') return statusOf('loadingAccount', false, false);
  if (who.state === 'offline') return statusOf('offline', false, false);
  if (who.state === 'disabled') return statusOf('disabled', false, false);
  if (!onChart()) return {text: 'Chart only', canToggle: false, retry: false, copy: [sp('rail.chartOnly')]};
  if (!savedSpotsOn.value) return statusOf('off', true, false);
  const mine = read.who === who;
  if (mine && read.state === 'failed') return statusOf('failed', true, true);
  if (mine && read.state === 'ready') return statusOf(read.rows.length ? 'ready' : 'empty', true, false);
  return statusOf('loading', true, false);
});

export function setSavedSpotsOn(on: boolean): void {
  if (on && !signedIn(followed.peek().peek())) return;
  savedSpotsOn.value = on;
}

/** The legend's Try again: a failed read is read again, only on this explicit ask. */
export function retrySavedSpots(): void {
  const read = store.peek();
  if (read.state === 'failed') store.value = {who: read.who, state: 'idle', rows: []};
}

// ---- Pins, style and card -------------------------------------------------------------------------------------------

const rowByKey = (key: unknown): SavedSpotRow | undefined => {
  const read = store.peek();
  return typeof key === 'string' && read.state === 'ready' ? read.rows.find(r => r.key === key) : undefined;
};

/** The pins as GeoJSON: the pick key and the name, at the point; empty unless the layer may draw. */
export function savedSpotFeatures(): Collection {
  if (!drawable.value) return EMPTY;
  const lang = language.value;
  return {type: 'FeatureCollection', features: store.value.rows.map(r => ({
    type: 'Feature', geometry: {type: 'Point', coordinates: [r.longitude, r.latitude]}, properties: {key: r.key, name: r.unnamed ? t('savedSpots.card.unnamed', lang) : r.name}}))} as unknown as Collection;
}

/** The Chart's source and layers: a 44 px target, the pin and its name, from the palette. */
export function savedSpotStyle(p: Palette) {
  return {
    source: {type: 'geojson', data: {type: 'FeatureCollection', features: []}},
    layers: [
      {id: SAVED_SPOT_PICK, type: 'circle', source: SAVED_SPOTS_SOURCE, paint: {'circle-radius': 22, 'circle-color': p.bg, 'circle-opacity': 0}},
      {id: SAVED_SPOT_PIN, type: 'circle', source: SAVED_SPOTS_SOURCE, paint: {'circle-radius': 8, 'circle-color': p.blue, 'circle-stroke-color': p.bg, 'circle-stroke-width': 2.5}},
      {id: SAVED_SPOT_NAME, type: 'symbol', source: SAVED_SPOTS_SOURCE,
        layout: {'text-field': ['get', 'name'], 'text-font': [LABEL_FONT], 'text-size': 12, 'text-anchor': 'top', 'text-offset': [0, 1.1], 'text-allow-overlap': false},
        paint: {'text-color': p.text, 'text-halo-color': p.bg, 'text-halo-width': 2}},
    ],
  };
}

const NOT_CHECKED: PlaceVerdict = Object.freeze({inside: false, name: null, distanceM: null, screened: false});

/** The shared verdict for the point now: only a loaded screen of this region that knows its coverage can speak; anything else is not checked. */
function verdictFor(row: SavedSpotRow, at: string | null): PlaceVerdict {
  const held = screenState.value;
  if (!at || !held || held.region !== at || held.loaded.state !== 'loaded' || held.loaded.region !== at) return NOT_CHECKED;
  const screen = held.loaded.screen;
  if (typeof (screen as {coversGeometry?: unknown}).coversGeometry !== 'function') return NOT_CHECKED;
  try { return screenPlace(screen, {latitude: row.latitude, longitude: row.longitude}); } catch { return NOT_CHECKED; }
}

/** The card's reading: the shared line verbatim for inside and not checked, the shared near line with the margin beside it, else the clear words. */
export function readingFor(v: PlaceVerdict): string {
  const line = verdictLine(v);
  if (!line) return CARD_WORDS.clear;
  return v.screened && !v.inside ? `${line} · ${CARD_WORDS.near}` : line;
}
/** The same reading as catalogue parts, for the card to say in the page's language. */
function readingParts(v: PlaceVerdict): MarkCopyPart[] {
  const line = verdictParts(v);
  if (!line) return [{id: 'savedSpots.card.clear'}];
  return v.screened && !v.inside ? [...line, ' · ', {id: 'savedSpots.card.near'}] : line;
}

let wantScreen: (() => void) | null = null;

/** The card for a clicked pin: the private reading, with no position, trip, note or database id. Null when the pin is no longer drawn. */
export function savedSpotMark(properties: Record<string, unknown> | null): ChartMark | null {
  const row = drawable.peek() ? rowByKey(properties?.key) : undefined;
  if (!row) return null;
  wantScreen?.();
  return cardFor(row);
}

/** SC1822-09: each private card is bound to the row it was made from, so the card needs no position of its own. */
const CARD_ROW = new WeakMap<ChartMark, SavedSpotRow>();

/**
 * The point behind a real private card, for the card's distance line only: a fresh coordinate pair, never the row, note or database id.
 * Null for a forged or copied card, a row no longer in the current session's ready list, a layer that does not draw, or a signed-out session.
 * Reads the layer's signals, so a caller re-renders the moment access is lost.
 */
export function savedSpotDistancePosition(mark: ChartMark): {latitude: number; longitude: number} | null {
  const row = CARD_ROW.get(mark), read = store.value;
  if (!row || !drawable.value || read.state !== 'ready' || !read.rows.includes(row)) return null;
  return {latitude: row.latitude, longitude: row.longitude};
}

function cardFor(row: SavedSpotRow): ChartMark {
  const at = region.peek(), data = markData.peek()?.region;
  const card: ChartMark = {
    id: `${SAVED_CARD_PREFIX}${row.key}`, name: row.name, kind: CARD_WORDS.kind, reading: readingFor(verdictFor(row, at)), source: CARD_WORDS.source,
    rules: CARD_WORDS.caveat, regulations: regulationsLink(data && data.id === at ? data : {id: at ?? ''}), basis: layerEntry('saved-spots').basis,
    // Display wording only: no note, owner, id or date goes into it. A real name is never in it; only the generated fallback is.
    copy: {
      kind: [{id: 'savedSpots.card.kind'}], reading: readingParts(verdictFor(row, at)), source: [{id: 'savedSpots.card.source'}], rules: [{id: 'savedSpots.card.caveat'}],
      ...(row.unnamed ? {name: [{id: 'savedSpots.card.unnamed'}]} : {}),
    } satisfies MarkCopyFields,
  };
  CARD_ROW.set(card, row);
  return card;
}

/** A pick of a pin: the private card replaces the Chart's selection. It never touches the address, history or camera. */
export function pickSavedSpot(properties: Record<string, unknown> | null, set: (mark: ChartMark | null) => void): boolean {
  const mark = savedSpotMark(properties);
  if (!mark) return false;
  set(mark);
  picked.value++;
  return true;
}

// ---- The layer ------------------------------------------------------------------------------------------------------

export interface SavedSpotLayerOptions {
  engine: ReadonlySignal<Engine | null>;
  /** The Chart's selection, which a private card is cleared from. */
  chartMark?: {value: ChartMark | null; peek(): ChartMark | null};
  session?: ReadonlySignal<Session>;
  fetchFn?: typeof fetch;
  events?: Pick<EventTarget, 'addEventListener' | 'removeEventListener'>;
  loadScreen?: (region: string) => Promise<ProtectedScreen>;
}

const defaultScreen = async (id: string): Promise<ProtectedScreen> => (await import('../trip.ts')).loadProtectedScreen(id);

export function createSavedSpotLayer(o: SavedSpotLayerOptions): {destroy(): void} {
  const sessionSignal = o.session ?? accountSession, fetchFn = o.fetchFn ?? ((input: RequestInfo | URL, init?: RequestInit) => fetch(input, init));
  const loadScreen = o.loadScreen ?? defaultScreen;
  const events = o.events ?? (typeof globalThis.addEventListener === 'function' ? globalThis : null);
  let alive = true, gen = 0, abort: AbortController | null = null, timer: ReturnType<typeof setTimeout> | undefined, scheduled = false;
  followed.value = sessionSignal;
  screenState.value = null;

  const clearCard = (): void => { if (o.chartMark?.peek()?.id.startsWith(SAVED_CARD_PREFIX)) o.chartMark.value = null; };
  const stopRead = (): void => { gen++; abort?.abort(); abort = null; clearTimeout(timer); };

  async function read(who: Session): Promise<void> {
    const mine = ++gen, ctl = new AbortController();
    abort?.abort(); abort = ctl;
    store.value = {who, state: 'loading', rows: []};
    const readTimer = setTimeout(() => ctl.abort(), READ_MS);
    timer = readTimer;
    const stopped = new Promise<never>((_, reject) => ctl.signal.addEventListener('abort', () => reject(new Error('stopped'))));
    let rows: SavedSpotRow[] | null = null;
    try {
      rows = await Promise.race([(async () => {
        const response = await fetchFn('/api/spots', {credentials: 'same-origin', cache: 'no-store', signal: ctl.signal});
        if (!response.ok) return null;
        return projectSavedSpots(await response.json());
      })(), stopped]);
    } catch { rows = null; }
    // Each read owns its deadline: stale cleanup must not cancel a replacement's timer.
    clearTimeout(readTimer);
    // A late answer for an older read, an old session or a destroyed layer is dropped.
    if (!alive || mine !== gen || sessionSignal.peek() !== who) return;
    store.value = rows ? {who, state: 'ready', rows} : {who, state: 'failed', rows: []};
  }

  /** The list is asked for in the next microtask, so a burst of changes is one request. */
  const schedule = (): void => {
    if (scheduled) return;
    scheduled = true;
    void Promise.resolve().then(() => {
      scheduled = false;
      const who = sessionSignal.peek(), now = store.peek();
      if (!alive || !signedIn(who) || !savedSpotsOn.peek() || !onChart() || now.who !== who || now.state !== 'idle') return;
      void read(who);
    });
  };

  const invalidate = (): void => {
    const now = store.peek();
    if (now.state === 'idle') return;
    stopRead();
    store.value = {who: now.who, state: 'idle', rows: []};
    clearCard();
  };

  const requestScreen = (): void => {
    const at = region.peek(), held = screenState.peek();
    if (!at || (held?.region === at && held.loaded.state === 'loaded')) return;
    const who = sessionSignal.peek();
    void loadScreen(at).then(loaded => {
      if (!alive || region.peek() !== at || sessionSignal.peek() !== who) return;
      screenState.value = {region: at, loaded};
      tick.value++;
    }, () => { if (alive && region.peek() === at) { screenState.value = {region: at, loaded: {state: 'failed'}}; tick.value++; } });
  };
  wantScreen = requestScreen;

  const onChange = (): void => invalidate();
  events?.addEventListener(SAVED_SPOTS_CHANGED, onChange);
  let minute: ReturnType<typeof setInterval> | undefined;
  const refresh = (): void => { if (drawable.peek()) { requestScreen(); tick.value++; } };
  const onVisible = (): void => { if (typeof document !== 'undefined' && !document.hidden) refresh(); };
  const stopTimers = (): void => {
    clearInterval(minute); minute = undefined;
    if (typeof document !== 'undefined') document.removeEventListener?.('visibilitychange', onVisible);
  };

  const disposers = [
    // A different session (sign-out, a new sign-in, a refreshed read) drops the list, the choice and any private card at once.
    effect(() => {
      const who = sessionSignal.value;
      untracked(() => {
        const now = store.peek();
        if (now.who !== who) { stopRead(); store.value = {who, state: 'idle', rows: []}; clearCard(); if (now.who !== null) savedSpotsOn.value = false; }
        if (!signedIn(who)) savedSpotsOn.value = false;
      });
    }),
    // The first turn-on (and a retry or an invalidation) asks for the list; a toggle, camera, region or remount does not.
    effect(() => {
      const who = sessionSignal.value, read1 = store.value, on = savedSpotsOn.value, chart = onChart();
      if (signedIn(who) && on && chart && read1.who === who && read1.state === 'idle') schedule();
    }),
    // The shared screen for the region, asked for once the layer is on; a region change reads the verdict again, not the list.
    // The minute and the tab's return read the open card's verdict again, only while the layer draws.
    effect(() => {
      const on = drawable.value, at = region.value;
      untracked(() => {
        if (on && at) requestScreen();
        if (on && minute === undefined) {
          minute = setInterval(refresh, REFRESH_MS);
          if (typeof document !== 'undefined') document.addEventListener?.('visibilitychange', onVisible);
        } else if (!on && minute !== undefined) stopTimers();
      });
    }),
    effect(() => { o.engine.value?.setData(SAVED_SPOTS_SOURCE, savedSpotFeatures()); }),
    // A private card goes with its pin: turned off, another presentation, a changed or invalidated list, a signed-out session.
    effect(() => {
      const shown = drawable.value; void store.value;
      untracked(() => {
        const id = o.chartMark?.peek()?.id;
        if (!id?.startsWith(SAVED_CARD_PREFIX)) return;
        if (!shown || !rowByKey(id.slice(SAVED_CARD_PREFIX.length))) clearCard();
      });
    }),
    // The shared screen changing, a minute passing or the tab returning reads the open card's verdict again.
    effect(() => {
      void tick.value; void screenState.value; void region.value;
      untracked(() => {
        const id = o.chartMark?.peek()?.id;
        if (!id?.startsWith(SAVED_CARD_PREFIX)) return;
        const row = rowByKey(id.slice(SAVED_CARD_PREFIX.length));
        if (row && o.chartMark) o.chartMark.value = cardFor(row);
      });
    }),
  ];
  return {
    destroy() {
      if (!alive) return;
      alive = false;
      stopRead();
      stopTimers();
      events?.removeEventListener(SAVED_SPOTS_CHANGED, onChange);
      for (const dispose of disposers) dispose();
      clearCard();
      if (wantScreen === requestScreen) wantScreen = null;
      if (followed.peek() === sessionSignal) followed.value = accountSession;
      // The list stays for this session, so a remount of the Chart does not ask for it again; a read in flight is dropped and asked again.
      const now = store.peek();
      if (now.state === 'loading') store.value = {who: now.who, state: 'idle', rows: []};
    },
  };
}
