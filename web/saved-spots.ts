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
import {t, type StringId} from './i18n.ts';
import type {ChartMark} from './map/coastline.ts';
import {SAVED_SPOTS_CHANGED} from './map/saved-spots.ts';

export type SpotCandidate = {readonly name: string; readonly lat: number; readonly lon: number; readonly note: null};
export type SpotResult = {readonly state: 'saved' | 'refused' | 'failed'; readonly message: string};

/** The card's wording in English, one place, so the tests and the page read the same words (the catalogue holds the Spanish). */
const SAVE_IDS = {helper: 'mark.save.helper', context: 'mark.save.context', noPosition: 'mark.save.noPosition', notChecked: 'mark.save.notChecked',
  inside: 'mark.save.inside', margin: 'mark.save.margin', signIn: 'mark.save.signIn', cap: 'mark.save.cap', invalid: 'mark.save.invalid',
  uncertain: 'mark.save.uncertain', changed: 'mark.save.changed', saved: 'mark.save.saved'} as const satisfies Record<string, StringId>;
export const SAVE_WORDS = Object.fromEntries(Object.entries(SAVE_IDS).map(([k, id]) => [k, t(id, 'en')])) as {readonly [K in keyof typeof SAVE_IDS]: string};

/** The catalogue identity of a result's message, kept beside the result so `.message` stays the exact English the callers expect. */
export type MessageIdentity = {readonly id: StringId; readonly vars?: Readonly<Record<string, string | number>>};
const identities = new WeakMap<SpotResult, MessageIdentity>();
/** The result's message in `lang`: its catalogue identity when it has one, else the message verbatim (never parsed). */
export function resultMessage(result: SpotResult, lang: string): string {
  const known = identities.get(result);
  return known ? t(known.id, lang, known.vars) : result.message;
}
const worded = (state: SpotResult['state'], key: keyof typeof SAVE_IDS): SpotResult => {
  const result: SpotResult = {state, message: SAVE_WORDS[key]};
  identities.set(result, {id: SAVE_IDS[key]});
  return result;
};

const NAME_UNITS = 80;
/** The exact answer of the spots route when the account is full. */
const CAP_ERROR = 'you can keep at most 100 saved spots; remove one first';
const CONTEXT = /^(?:geology|charter|fleet):/;

const refused = (key: keyof typeof SAVE_IDS): SpotResult => worded('refused', key);
const failed = (key: keyof typeof SAVE_IDS): SpotResult => worded('failed', key);

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
  const found = classify(mark);
  if (!('reason' in found)) return found;
  if (found.reason !== 'withheld') return refused(found.reason);
  const reading = typeof mark.reading === 'string' ? mark.reading.trim() : '', identity: MessageIdentity = reading ? {id: 'mark.save.withheld', vars: {reading}} : {id: 'mark.save.notSaved'};
  const result: SpotResult = {state: 'refused', message: t(identity.id, 'en', identity.vars)};
  identities.set(result, identity);
  return result;
}

/** Why a mark's position may not be kept or handed on. Neutral codes: the save path words them its way, the card's copy action its own. */
export type PositionRefusal = 'context' | 'withheld' | 'noPosition' | 'notChecked' | 'inside' | 'margin';
export type MarkPositionScreen = {readonly allowed: true; readonly region: string; readonly candidate: SpotCandidate} | {readonly allowed: false; readonly reason: PositionRefusal};

/** The one candidate rule: map context, a withheld card and a mark without its own valid position are not candidates. */
function classify(mark: ChartMark): SpotCandidate | {readonly reason: 'context' | 'withheld' | 'noPosition'} {
  if (CONTEXT.test(String(mark?.id ?? ''))) return {reason: 'context'};
  if (mark?.withheld) return {reason: 'withheld'};
  const at = mark?.position, lat = at?.latitude, lon = at?.longitude;
  if (typeof lat !== 'number' || typeof lon !== 'number' || !Number.isFinite(lat) || !Number.isFinite(lon) || lat < -90 || lat > 90 || lon < -180 || lon >= 180) return {reason: 'noPosition'};
  return {name: boundName(typeof mark.name === 'string' ? mark.name : ''), lat, lon, note: null};
}

/**
 * SC2252-09: may this mark's position be kept or handed on, by the region's shared protected-area screen as already loaded?
 * The save path and the card's copy action both ask this, so neither can allow a point the other refuses. Account-free and
 * synchronous: it loads nothing, reads no session and sends or stores nothing. Only a covered, screened point that is neither
 * inside a protected area nor within its 70 m margin (dist/geo-screen.js `placeRefused`) is allowed.
 */
export function screenMarkPosition(mark: ChartMark, region: string | null, loaded: ProtectedScreen): MarkPositionScreen {
  const found = classify(mark);
  if ('reason' in found) return {allowed: false, reason: found.reason};
  const screen = region && loaded?.state === 'loaded' && loaded.region === region ? loaded.screen : null;
  if (!region || !screen || typeof (screen as {coversGeometry?: unknown}).coversGeometry !== 'function') return {allowed: false, reason: 'notChecked'};
  let verdict;
  try { verdict = screenPlace(screen, {latitude: found.lat, longitude: found.lon}); } catch { return {allowed: false, reason: 'notChecked'}; }
  if (!verdict || !verdict.screened) return {allowed: false, reason: 'notChecked'};
  if (verdict.inside) return {allowed: false, reason: 'inside'};
  if (placeRefused(verdict)) return {allowed: false, reason: 'margin'};
  return {allowed: true, region, candidate: found};
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
  if (who.state !== 'signed-in') return failed('signIn');
  if (!where) return refused('notChecked');
  let loaded: ProtectedScreen;
  try { loaded = await loadScreen(where); } catch { return refused('notChecked'); }
  const answer = screenMarkPosition(mark, where, loaded);
  if (!answer.allowed) return answer.reason === 'withheld' ? spotCandidate(mark) as SpotResult : refused(answer.reason);
  // Re-read just before the write: a different account, a sign out or another region means this answer is not for them.
  const now = readSession();
  if (now.state !== 'signed-in') return failed('signIn');
  if (now !== who) return failed('changed');
  if (readRegion() !== where) return refused('notChecked');
  let response: Response;
  try {
    response = await fetchFn('/api/spots', {
      method: 'POST', credentials: 'same-origin', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({name: candidate.name, lat: candidate.lat, lon: candidate.lon, note: null}), signal: AbortSignal.timeout(20000),
    });
  } catch { return failed('uncertain'); }
  if (response.status === 201) {
    const row = await response.json().catch(() => null);
    if (!confirmed(row, candidate)) return failed('uncertain');
    // SC0922-04: tell the owner's Chart layer, if it is listening, that the list changed: no row, id, name, position or note travels with it, and a session that changed since says nothing.
    if (readSession() === who) {
      const target = deps.events ?? globalThis;
      try { if (typeof target.dispatchEvent === 'function') target.dispatchEvent(new Event(SAVED_SPOTS_CHANGED)); } catch { /* the layer reads again on its next turn-on */ }
    }
    return worded('saved', 'saved');
  }
  if (response.status === 401) { try { void (deps.refresh ?? (() => refreshSession()))(); } catch { /* the session reads again on its own */ } return failed('signIn'); }
  if (response.status === 400) {
    const body = await response.json().catch(() => null) as {error?: unknown} | null;
    return failed(body?.error === CAP_ERROR ? 'cap' : 'invalid');
  }
  return failed('uncertain');
}

/** The answer when the save call itself threw: unconfirmed, with the same identity as any other unconfirmed save. */
export const uncertainResult = (): SpotResult => worded('failed', 'uncertain');
