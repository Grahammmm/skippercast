// Account, boat and alerts for the v2 masthead (FE-50, design § 6 and § 7).
// A wrapper, not a rewrite: the passkey dialog (dist/account.js), the exact
// boat sheet (dist/boat-profile.js) and the boat presets (dist/first-run.js)
// keep one implementation, so the session cookie and the reload after sign in
// are v1's. Saved-trip alerts are v2's own (web/alerts.ts, #602).
// Each module loads on first use: the app entry carries none of them.
//
// Erasable syntax only: Node tests import this file by type stripping.
import {signal} from '@preact/signals';

/** dist/account.js's key: after sign in or close it restores this hash. */
export const RETURN_KEY = 'skippercast-account-return';
/** v2 has no hash routes; account.js needs a non-empty value, so it restores a bare "#" (dropped by `dropEmptyHash`). */
const BARE = '#';

export type Session =
  | {readonly state: 'loading'}
  | {readonly state: 'offline'}
  | {readonly state: 'disabled'}
  | {readonly state: 'signed-out'}
  | {readonly state: 'signed-in'; readonly name: string | null};

export const session = signal<Session>({state: 'loading'});
let sessionRequest: Promise<Session> | null = null;
let sessionGeneration = 0;

/** The /api/session answer as the menu reads it: offline on any failure, disabled when the site offers no sign in. */
export function readSession(data: unknown, ok = true): Session {
  if (!ok || !data || typeof data !== 'object') return {state: 'offline'};
  const d = data as {signIn?: unknown; signedIn?: unknown; user?: {display_name?: unknown}};
  if (!d.signIn) return {state: 'disabled'};
  if (!d.signedIn) return {state: 'signed-out'};
  const name = typeof d.user?.display_name === 'string' && d.user.display_name.trim() ? d.user.display_name.trim() : null;
  return {state: 'signed-in', name};
}

/** Mount initialization: share pending reads and reuse settled sessions across layout remounts. */
export function ensureSession(fetchFn: typeof fetch = fetch): Promise<Session> {
  if (sessionRequest) return sessionRequest;
  const current = session.peek();
  if (current.state !== 'loading' && current.state !== 'offline') return Promise.resolve(current);
  return refreshSession(fetchFn);
}

/** Always fetch; only the latest requested read may update shared state. Offline reads remain retryable. */
export function refreshSession(fetchFn: typeof fetch = fetch): Promise<Session> {
  const generation = ++sessionGeneration;
  sessionRequest = (async (): Promise<Session> => {
    try {
      const response = await fetchFn('/api/session', {signal: AbortSignal.timeout(20000)});
      return readSession(await response.json().catch(() => null), response.ok);
    } catch { return {state: 'offline'}; }
  })().then(next => {
    if (generation === sessionGeneration) session.value = next;
    return next;
  }).finally(() => {
    if (generation === sessionGeneration) sessionRequest = null;
  });
  return sessionRequest;
}

/** The trigger's text: the account name, "Account", or "Sign in". */
export function accountLabel(s: Session): string {
  if (s.state === 'signed-in') return s.name ?? 'Account';
  return s.state === 'signed-out' || s.state === 'loading' ? 'Sign in' : 'Account';
}

/** Where account.js returns after it closes or reloads: the hash before #account, else a bare "#". */
export function remember(back: string, storage: Pick<Storage, 'setItem'> | undefined = globalThis.sessionStorage): void {
  try { storage?.setItem(RETURN_KEY, back && back !== '#account' ? back : BARE); } catch { /* storage blocked: account.js falls back */ }
}

/** "/map?region=…#" → "/map?region=…" after account.js restored the bare hash. */
export function dropEmptyHash(loc: Pick<Location, 'href' | 'hash' | 'pathname' | 'search'> = location, h: Pick<History, 'replaceState' | 'state'> = history): void {
  if (!loc.hash && loc.href.endsWith('#')) h.replaceState(h.state, '', loc.pathname + loc.search);
}

/** Open v1's passkey dialog (sign in, create, passkeys, sign out, delete). */
export async function openAccountDialog(): Promise<void> {
  remember(location.hash);
  const {openAccount} = await import('../dist/account.js');
  await openAccount();
}

/**
 * Follow #account links as v1's initAccount does: the boat sheet's and the
 * alerts' sign-in links are "#account". `before` closes v2's own dialogs first.
 */
export function followAccountHash(before: () => void): () => void {
  const fromHash = (event?: HashChangeEvent) => {
    if (location.hash !== '#account') { dropEmptyHash(); return; }
    before();
    remember(event?.oldURL ? new URL(event.oldURL).hash : '');
    void import('../dist/account.js').then(m => m.openAccount());
  };
  addEventListener('hashchange', fromHash);
  fromHash();
  return () => removeEventListener('hashchange', fromHash);
}

/**
 * A trip-alert notification tap lands on "#alerts" (dist/sw.js): open the alerts
 * dialog (`open(true)`) or, with no port in view, the account panel (`open(false)`).
 * The hash is dropped at once so closing the dialog or reloading never reopens it.
 */
export function followAlertsHash(open: (hasRegion: boolean) => void, hasRegion: () => boolean): () => void {
  const fromHash = () => {
    if (location.hash !== '#alerts') return;
    open(hasRegion());
    history.replaceState(history.state, '', location.pathname + location.search);
  };
  addEventListener('hashchange', fromHash);
  fromHash();
  return () => removeEventListener('hashchange', fromHash);
}

export type BoatPreset = {readonly id: string; readonly label: string; readonly detail: string};
export type BoatState = {readonly presets: readonly BoatPreset[]; /** The saved boat's name, or null for the reference boat. */ readonly name: string | null; readonly preset: string | null};
export const boat = signal<BoatState | null>(null);

export async function loadBoat(): Promise<BoatState> {
  const [{PRESETS}, {savedBoat}] = await Promise.all([import('../dist/first-run.js'), import('../dist/boat-handling.js')]);
  const saved = savedBoat() as {boat?: {name?: string; loa_ft?: number}; preset?: string} | null;
  const name = saved?.boat ? saved.boat.name || (saved.boat.loa_ft ? `${Math.round(saved.boat.loa_ft)} ft boat` : 'Saved boat') : null;
  const state: BoatState = {presets: PRESETS.map(p => ({id: p.id, label: p.label, detail: p.detail})), name, preset: saved?.preset ?? null};
  boat.value = state;
  return state;
}

/** Save a preset the way first-run.js does, then reload as v1 does: ratings and alert limits read the boat on load. */
export async function choosePreset(id: string): Promise<boolean> {
  const {savePreset} = await import('../dist/first-run.js');
  if (!savePreset(id)) return false;
  location.reload();
  return true;
}

export async function openBoatSheet(): Promise<void> {
  const {openBoatProfile} = await import('../dist/boat-profile.js');
  openBoatProfile();
}
