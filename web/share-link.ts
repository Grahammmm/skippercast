// Shareable links (BF-deep-links): the one canonical address Share copies. It names the region, the port the control
// shows, the dock's absolute day (today included, so Wednesday's link still means Wednesday) and the profile, then the
// hour, target, listed view keys and the grade filter the address has. A whitelist: nothing else (ui, utm, a token, the hash) is carried,
// values are re-encoded, and the title names place, day and profile only, never a condition.
// Pure and DOM-free; erasable syntax only: Node tests import this file by type stripping.
import {canonicalHour, fishLink} from './fish-links.ts';
import {gradeParam, parseGrade} from './grade.ts';
import {dockTime, horizonDays, localParts} from './hour.ts';
import {currentPort, type Port} from './ports.ts';
import {isProfile, PROFILE_TABLE, type Profile} from './profile.ts';
import {parsePort} from './state.ts';

/** View keys a link keeps when the address already has them, in this order, after region, port, profile, day, hour and target. */
export const SHARED_VIEW_KEYS = ['view', 'layers', 'base', 'presentation', 'current', 'habitat', 'spot'] as const;

export interface ShareInput {
  /** The current address; only whitelisted keys are read from it. */
  readonly href: string;
  /** The site origin the link opens on, e.g. https://skippercast.com. */
  readonly origin: string;
  /** The port directory, or null/empty when it failed to load (the link then names no port). */
  readonly ports: readonly Port[] | null;
  readonly region: string | null;
  /** The device's saved home port id (savedPortId()). */
  readonly savedId: string | null;
  readonly profile: Profile;
  readonly now: Date;
  /** The region's time zone. */
  readonly tz: string;
  /** The dock's ?day= value; defaults to the address's own. */
  readonly dockDay?: string | null;
}

export interface ShareLink {readonly url: string; readonly title: string}

/** "Sat Nov 7" for a "YYYY-MM-DD" day (the brief's lead uses the same shape). */
export const shareDayText = (date: string): string =>
  new Date(`${date}T12:00:00Z`).toLocaleDateString('en-US', {timeZone: 'UTC', weekday: 'short', month: 'short', day: 'numeric'}).replace(',', '');

/** The coast a region-less link names: the address's own single, well-formed ?coast=, else `central` (exploreURL's). */
export function shareCoast(values: readonly string[]): string {
  const [only] = values;
  return values.length === 1 && only !== undefined && /^[a-z0-9-]{1,40}$/.test(only) ? only : 'central';
}

/** The canonical link to what the page shows now, and its share-sheet title. */
export function shareLink({href, origin, ports, region, savedId, profile, now, tz, dockDay}: ShareInput): ShareLink {
  const from = fishLink(href).searchParams;
  const out = new URL('/map', origin), p = out.searchParams;
  const linked = parsePort(from.getAll('port').length === 1 ? from.get('port') : null);
  const port = ports && ports.length ? currentPort(ports, region, savedId, linked) : null;
  const hour = canonicalHour(from.get('hour'));
  const days = horizonDays(now, tz);
  // The dock's own rule: an hour wins; a later horizon day keeps its date; a past or far day reads as today.
  const shown = dockTime(dockDay === undefined ? from.get('day') : dockDay, hour, now, tz, days);
  const day = days.some(d => d.day === shown.day) ? shown.day : null;
  // Geography is always named, so the recipient never falls through to their own saved home (web/app/main.tsx):
  // the region, else the coast view the address shows ("Explore the coast", exploreURL), else that same coast view.
  if (region) p.set('region', region);
  else p.set('coast', shareCoast(from.getAll('coast')));
  if (port) p.set('port', port.id);
  if (isProfile(profile)) p.set('profile', profile);
  if (day) p.set('day', day);
  if (hour) p.set('hour', hour);
  const target = from.get('target');
  if (target) p.set('target', target);
  for (const key of SHARED_VIEW_KEYS) {
    const value = from.get(key);
    if (value) p.set(key, value);
  }
  const grade = gradeParam(parseGrade(from.get('grade')));
  if (grade) p.set('grade', grade);
  const title = [port?.name, shareDayText(day ?? localParts(new Date(shown.at), tz).day), isProfile(profile) ? PROFILE_TABLE[profile].label : null]
    .filter(Boolean).join(' · ');
  return {url: out.href, title};
}

/** What one press of Share did: handed to the share sheet, cancelled there, copied, or shown to copy by hand. */
export type ShareOutcome = 'shared' | 'cancelled' | 'copied' | 'manual';

/** The press: the share sheet when there is one (a dismissed sheet does nothing), else the clipboard, else the caller shows the link. */
export async function shareOrCopy(link: ShareLink, nav: Partial<Pick<Navigator, 'share' | 'clipboard'>> | undefined = globalThis.navigator): Promise<ShareOutcome> {
  if (typeof nav?.share === 'function') {
    try { await nav.share({title: link.title, url: link.url}); return 'shared'; } catch (error) {
      if ((error as {name?: unknown})?.name === 'AbortError') return 'cancelled';
    }
  }
  try {
    if (typeof nav?.clipboard?.writeText !== 'function') return 'manual';
    await nav.clipboard.writeText(link.url);
    return 'copied';
  } catch { return 'manual'; }
}
