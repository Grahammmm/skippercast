// First run (FE-08, design § 7, D11): the Boat / Shore / Spear choice, shown
// once over the map and never modal. It appears when no profile is stored
// and the address names none; choosing (or keeping Boat) writes ?profile=,
// which the store persists, so it never shows again. v1's boat preset step
// moves to the account menu; "tomorrow's answer" is the brief's headline.
// A home saved on /coast carries its mode, so it is not asked again (FE-83).
import {useEffect, useState} from 'preact/hooks';
import {Button} from '../ui/Button.tsx';
import {DEFAULT_PROFILE, PROFILE_TABLE, PROFILES, isProfile, type Profile} from '../profile.ts';
import {savedHomeMode, type CookieJar} from '../ports.ts';
import {readURL, setParams, STORAGE_KEYS, type StoreStorage} from '../state.ts';

/** What each profile changes, in one line; the semantics are web/profile.ts's. */
export const PROFILE_NOTES: Readonly<Record<Profile, string>> = {
  boat: 'Reef marks and seafloor to 300 ft; seafloor and currents on the map.',
  shore: 'Sandy-shore runs with access and rules; swell and water temp on the map.',
  spear: 'Reef within 60 ft, nearest fresh nearshore site first; seafloor and swell on the map.',
};

function browserStorage(): StoreStorage | null {
  try { return typeof localStorage === 'undefined' ? null : localStorage; } catch { return null; }
}
function browserCookies(): CookieJar | null {
  try { return typeof document === 'undefined' ? null : document; } catch { return null; }
}

/** Whether `href` or storage names a profile already. */
function profileNamed(href: string, storage: StoreStorage | null): boolean {
  if (isProfile(readURL(href).profile)) return true;
  try { return isProfile(storage?.getItem(STORAGE_KEYS.profile)); } catch { return false; }
}

/**
 * The profile a home saved on /coast answers the question with (FE-83, one
 * setup surface): its mode, when neither `href` nor storage names a profile.
 */
export function savedFirstRun(href: string, storage: StoreStorage | null = browserStorage(), cookies: CookieJar | null = browserCookies()): Profile | null {
  return profileNamed(href, storage) ? null : savedHomeMode(storage, cookies);
}

/** Whether the choice is due: no profile in `href`, none stored, and no saved /coast home's mode. */
export function firstRunDue(href: string, storage: StoreStorage | null = browserStorage(), cookies: CookieJar | null = browserCookies()): boolean {
  return !profileNamed(href, storage) && savedHomeMode(storage, cookies) === null;
}

export function FirstRun({href, storage, cookies}: {href?: string; storage?: StoreStorage | null; cookies?: CookieJar | null} = {}) {
  const at = href ?? (typeof location === 'undefined' ? 'https://skippercast.com/map' : location.href);
  const [due, setDue] = useState(() => firstRunDue(at, storage, cookies));
  // A home saved on /coast already chose the mode: apply it (the address names none) rather than ask again.
  useEffect(() => { const saved = savedFirstRun(at, storage, cookies); if (saved) setParams({profile: saved}); }, []);
  if (!due) return null;
  const choose = (p: Profile) => { setDue(false); setParams(p === DEFAULT_PROFILE ? {profile: p} : {profile: p, target: null}); };
  return (
    <section class="app-firstrun" role="dialog" aria-labelledby="first-run-title" data-first-run="">
      <span class="ui-eyebrow">First time here</span>
      <h2 id="first-run-title">How do you fish?</h2>
      <p>The profile sets the depth limit, the species list and the map's default layers. Change it any time in the command bar.</p>
      <div class="app-firstrun-options">
        {PROFILES.map(p => (
          <Button key={p} icon={p} data-profile={p} onClick={() => choose(p)}>
            <span><strong>{PROFILE_TABLE[p].label}</strong><small>{PROFILE_NOTES[p]}</small></span>
          </Button>
        ))}
      </div>
      <Button variant="quiet" size="sm" onClick={() => choose(DEFAULT_PROFILE)}>Keep {PROFILE_TABLE[DEFAULT_PROFILE].label} for now</Button>
    </section>
  );
}
