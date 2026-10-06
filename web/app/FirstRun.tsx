// First run (FE-08, design § 7, D11): the Boat / Shore / Spear choice, shown
// once over the map and never modal. It appears when no profile is stored
// and the address names none; choosing (or keeping Boat) writes ?profile=,
// which the store persists, so it never shows again. v1's boat preset step
// moves to the account menu; "tomorrow's answer" is the brief's headline.
import {useState} from 'preact/hooks';
import {Button} from '../ui/Button.tsx';
import {DEFAULT_PROFILE, PROFILE_TABLE, PROFILES, isProfile, type Profile} from '../profile.ts';
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

/** Whether the choice is due: no stored profile and none in `href`. */
export function firstRunDue(href: string, storage: StoreStorage | null = browserStorage()): boolean {
  if (isProfile(readURL(href).profile)) return false;
  try { return !isProfile(storage?.getItem(STORAGE_KEYS.profile)); } catch { return true; }
}

export function FirstRun({href, storage}: {href?: string; storage?: StoreStorage | null} = {}) {
  const [due, setDue] = useState(() => firstRunDue(href ?? (typeof location === 'undefined' ? 'https://skippercast.com/map' : location.href), storage));
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
