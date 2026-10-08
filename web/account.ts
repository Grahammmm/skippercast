// Account, boat and alerts for the v2 masthead (FE-50, design § 6 and § 7).
// A wrapper, not a rewrite: the passkey dialog (dist/account.js), the exact
// boat sheet (dist/boat-profile.js), the boat presets (dist/first-run.js) and
// the saved-trip alerts (dist/trip-alerts.js) keep one implementation, so the
// session cookie, the reload after sign in and every /api/ call are v1's.
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

/** The /api/session answer as the menu reads it: offline on any failure, disabled when the site offers no sign in. */
export function readSession(data: unknown, ok = true): Session {
  if (!ok || !data || typeof data !== 'object') return {state: 'offline'};
  const d = data as {signIn?: unknown; signedIn?: unknown; user?: {display_name?: unknown}};
  if (!d.signIn) return {state: 'disabled'};
  if (!d.signedIn) return {state: 'signed-out'};
  const name = typeof d.user?.display_name === 'string' && d.user.display_name.trim() ? d.user.display_name.trim() : null;
  return {state: 'signed-in', name};
}

export async function refreshSession(fetchFn: typeof fetch = fetch): Promise<Session> {
  let next: Session;
  try {
    const response = await fetchFn('/api/session', {signal: AbortSignal.timeout(20000)});
    next = readSession(await response.json().catch(() => null), response.ok);
  } catch { next = {state: 'offline'}; }
  session.value = next;
  return next;
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

/**
 * Render v1's saved-trip alerts into the hosts trip-alerts.js expects
 * (#trip-alerts, #comfort-feedback, #species-select, #comfort-heading) for
 * `regionId`, the alert species defaulting to the app's target when the
 * region lists it. Comfort feedback carries no forecast context in v2.
 */
export async function mountTripAlerts(regionId: string, target: string | null): Promise<void> {
  const [regions, {initTripAlerts}] = await Promise.all([import('../dist/region.js'), import('../dist/trip-alerts.js')]);
  const response = await fetch(`regions/${encodeURIComponent(regionId)}/region.json`);
  if (!response.ok) throw Error('The region could not be loaded. Try again when you are online.');
  const json = await response.json() as {species: string[]};
  regions.setRegion(json);
  const r = regions.getRegion();
  const select = document.getElementById('species-select') as HTMLSelectElement | null;
  if (select) {
    const initial = regions.initialTargetSelection(r, target && json.species.includes(target) ? target : null);
    regions.renderTargetOptions(select, initial.options.filter((o: {id: string}) => json.species.includes(o.id)), initial.value);
  }
  await initTripAlerts({getState: () => null});
  document.querySelector('#trip-alerts > details')?.setAttribute('open', '');
}

/** v1's guide holds the GPX day plan and the offline pack until FE-51 brings them into v2. */
export const classicURL = (regionId: string | null, hash: '#export' | '#guide'): string =>
  `/?ui=v1${regionId ? `&region=${encodeURIComponent(regionId)}` : ''}${hash}`;
