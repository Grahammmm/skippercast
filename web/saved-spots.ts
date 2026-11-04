// SC0022-05: keep a selected map mark as a private spot in the signed-in person's account.
// The mark card calls only this module. A mark is a candidate (name and position, never a note);
// the shared protected-area screen (web/trip.ts `loadProtectedScreen`, dist/geo-screen.js
// `screenPlace` and `placeRefused`) must have checked the exact point before anything is sent;
// then one POST to the private spots store. Nothing here touches the address, history, a share
// link, storage, a feed, error reporting or usage measurement.
//
// The server's spots route does not run the browser's protected-area screen, so this module is
// where the screen applies to a save from the map. Erasable syntax only (Node tests import this).
import {refreshSession, session, type Session} from './account.ts';
import {region as currentRegion} from './state.ts';
import {loadProtectedScreen, type ProtectedScreen} from './trip.ts';
import {placeRefused, screenPlace} from '../dist/geo-screen.js';
import type {ChartMark} from './map/coastline.ts';
import {SAVED_SPOTS_CHANGED} from './map/saved-spots.ts';

export type SpotCandidate = {readonly name: string; readonly lat: number; readonly lon: number; readonly note: null};
export type SpotResult = {readonly state: 'saved' | 'refused' | 'failed'; readonly message: string};

/** The card's wording, one place, so the tests and the page read the same words. */
export const SAVE_WORDS = {
  helper: 'Private to your account. You can keep up to 100 saved spots.',
  context: 'This is map context, not a spot to save.',
  noPosition: 'This mark has no position to save.',
  notChecked: 'Protected areas not checked for this spot: outside coverage or check unavailable; not saved.',
  inside: 'Inside a protected area. Not saved.',
  margin: 'Within 70 m of a protected area. Not saved.',
  signIn: 'Sign in again to save this spot.',
  cap: 'You can keep up to 100 saved spots. Remove one in Account before saving another.',
  invalid: 'This spot could not be saved. Check its name and position.',
  uncertain: 'Could not confirm this spot was saved. Check Saved spots in Account before trying again.',
  changed: 'Your session changed. Not saved. Try again.',
  saved: 'Saved to your spots',
} as const;

const NAME_UNITS = 80;
/** The exact answer of the spots route when the account is full. */
const CAP_ERROR = 'you can keep at most 100 saved spots; remove one first';
const CONTEXT = /^(?:geology|charter|fleet):/;

const refused = (message: string): SpotResult => ({state: 'refused', message});
const failed = (message: string): SpotResult => ({state: 'failed', message});

/** The displayed name cut to 80 UTF-16 units, never inside a surrogate pair. */
export function boundName(name: string): string {
  let out = name.slice(0, NAME_UNITS);
  const last = out.charCodeAt(out.length - 1);
  if (out.length < name.length && last >= 0xd800 && last <= 0xdbff) out = out.slice(0, -1);
  return out;
}

/**
 * The mark's own name and position as a spot, or why it is not one. Only a position the mark itself supplies counts:
 * no camera centre, geometry centroid, id parsing or hidden position. A withheld card keeps its position to itself.
 */
export function spotCandidate(mark: ChartMark): SpotCandidate | SpotResult {
  if (CONTEXT.test(String(mark?.id ?? ''))) return refused(SAVE_WORDS.context);
  if (mark?.withheld) return refused(`${typeof mark.reading === 'string' && mark.reading.trim() ? mark.reading.trim() + ' ' : ''}Not saved.`);
  const at = mark?.position, lat = at?.latitude, lon = at?.longitude;
  if (typeof lat !== 'number' || typeof lon !== 'number' || !Number.isFinite(lat) || !Number.isFinite(lon) || lat < -90 || lat > 90 || lon < -180 || lon >= 180) return refused(SAVE_WORDS.noPosition);
  return {name: boundName(typeof mark.name === 'string' ? mark.name : ''), lat, lon, note: null};
}

export type SaveDeps = {
  fetchFn?: typeof fetch;
  /** The session now. */
  session?: () => Session;
  /** The region now. */
  region?: () => string | null;
  loadScreen?: (region: string) => Promise<ProtectedScreen>;
  /** Asked once after a 401. */
  refresh?: () => unknown;
  /** Where the zero-detail change event goes; the page by default. */
  events?: Pick<EventTarget, 'dispatchEvent'>;
};

const isResult = (value: SpotCandidate | SpotResult): value is SpotResult => 'state' in value;

/** The 201 answer is the stored row: an id, and this candidate's own position and name. Anything else is unconfirmed. */
function confirmed(row: unknown, spot: SpotCandidate): boolean {
  if (!row || typeof row !== 'object') return false;
  const r = row as Record<string, unknown>;
  return typeof r.id === 'string' && r.id !== '' && r.lat === spot.lat && r.lon === spot.lon && r.name === spot.name;
}

/**
 * Save the mark. Order: the candidate, the shared screen for this region (it must cover the point), the verdict,
 * a last look at the session and region, then the one POST. A refusal never posts; a POST is never retried.
 */
export async function saveMarkSpot(mark: ChartMark, deps: SaveDeps = {}): Promise<SpotResult> {
  const readSession = deps.session ?? (() => session.peek()), readRegion = deps.region ?? (() => currentRegion.peek());
  const fetchFn = deps.fetchFn ?? ((input, init) => fetch(input, init)), loadScreen = deps.loadScreen ?? ((id: string) => loadProtectedScreen(id));
  const candidate = spotCandidate(mark);
  if (isResult(candidate)) return candidate;
  const who = readSession(), where = readRegion();
  if (who.state !== 'signed-in') return failed(SAVE_WORDS.signIn);
  if (!where) return refused(SAVE_WORDS.notChecked);
  let loaded: ProtectedScreen;
  try { loaded = await loadScreen(where); } catch { return refused(SAVE_WORDS.notChecked); }
  const screen = loaded.state === 'loaded' && loaded.region === where ? loaded.screen : null;
  if (!screen || typeof (screen as {coversGeometry?: unknown}).coversGeometry !== 'function') return refused(SAVE_WORDS.notChecked);
  let verdict;
  try { verdict = screenPlace(screen, {latitude: candidate.lat, longitude: candidate.lon}); } catch { return refused(SAVE_WORDS.notChecked); }
  if (!verdict || !verdict.screened) return refused(SAVE_WORDS.notChecked);
  if (verdict.inside) return refused(SAVE_WORDS.inside);
  if (placeRefused(verdict)) return refused(SAVE_WORDS.margin);
  // Re-read just before the write: a different account, a sign out or another region means this answer is not for them.
  const now = readSession();
  if (now.state !== 'signed-in') return failed(SAVE_WORDS.signIn);
  if (now !== who) return failed(SAVE_WORDS.changed);
  if (readRegion() !== where) return refused(SAVE_WORDS.notChecked);
  let response: Response;
  try {
    response = await fetchFn('/api/spots', {
      method: 'POST', credentials: 'same-origin', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({name: candidate.name, lat: candidate.lat, lon: candidate.lon, note: null}), signal: AbortSignal.timeout(20000),
    });
  } catch { return failed(SAVE_WORDS.uncertain); }
  if (response.status === 201) {
    const row = await response.json().catch(() => null);
    if (!confirmed(row, candidate)) return failed(SAVE_WORDS.uncertain);
    // SC0922-04: tell the owner's Chart layer, if it is listening, that the list changed: no row, id, name, position or note travels with it, and a session that changed since says nothing.
    if (readSession() === who) {
      const target = deps.events ?? globalThis;
      try { if (typeof target.dispatchEvent === 'function') target.dispatchEvent(new Event(SAVED_SPOTS_CHANGED)); } catch { /* the layer reads again on its next turn-on */ }
    }
    return {state: 'saved', message: SAVE_WORDS.saved};
  }
  if (response.status === 401) { try { void (deps.refresh ?? (() => refreshSession()))(); } catch { /* the session reads again on its own */ } return failed(SAVE_WORDS.signIn); }
  if (response.status === 400) {
    const body = await response.json().catch(() => null) as {error?: unknown} | null;
    return failed(body?.error === CAP_ERROR ? SAVE_WORDS.cap : SAVE_WORDS.invalid);
  }
  return failed(SAVE_WORDS.uncertain);
}
