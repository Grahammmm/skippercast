// First run (FE-08, design § 7, D11): the Boat / Shore / Spear / Kayak choice, shown
// once over the map and never modal. It appears when no profile is stored
// and the address names none; choosing (or keeping Boat) writes ?profile=,
// which the store persists, so it never shows again. v1's boat preset step
// moves to the account menu; "tomorrow's answer" is the brief's headline.
// A home saved on /coast carries its mode, so it is not asked again (FE-83).
// #622: the landing's guided first run asks before the map opens, so this
// card is left for links into the map that name no profile.
// MYB-1 / SC-LANDING-ORDER: the optional boat length and comfort limits are
// asked after the choice, and only for Boat (BoatEntry): here when Boat is
// chosen, or on arrival from the landing's Boat choice (boat-entry.ts carryAsk).
import {signal} from '@preact/signals';
import {useEffect, useRef, useState} from 'preact/hooks';
import {ASK_PARAM, entryCopy, entryFields, saveFirstUse, takeAsk, withoutAsk} from '../boat-entry.ts';
import {language, t} from '../i18n.ts';
import {Button} from '../ui/Button.tsx';
import {DEFAULT_PROFILE, PROFILES, isProfile, type Profile} from '../profile.ts';
import {savedHomeMode, type CookieJar} from '../ports.ts';
import {readURL, setParams, STORAGE_KEYS, type StoreStorage} from '../state.ts';

/** Kept here for existing imports; the notes live in web/profile.ts beside the table, shared with the landing's profile step (#622). */
export {PROFILE_NOTES} from '../profile.ts';

export const BOAT_ENTRY_COPY = {save: t('boatEntry.save', 'en'), skip: t('boatEntry.skip', 'en')} as const;

/** True while BoatEntry is on screen. */
export const boatEntryOpen = signal(false);

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

/**
 * MYB-1's optional boat fields, asked once Boat is chosen. Save writes what they hold
 * (boat-entry.ts saveFirstUse, unchanged); Not now writes nothing. Either closes it.
 * `focus` moves focus here when it replaces the card the visitor was using.
 */
export function BoatEntry({storage, focus = false, onDone}: {storage?: StoreStorage | null; focus?: boolean; onDone: (notices: string[]) => void}) {
  const [boat, setBoat] = useState({lengthFt: '', wind: '', seas: ''});
  const form = useRef<HTMLFormElement>(null);
  // boatEntryOpen tells the phone's sheet to leave peek, whose clipped body hides the fields (Mobile.tsx boatEntryDetent).
  useEffect(() => { boatEntryOpen.value = true; if (focus) form.current?.focus(); return () => { boatEntryOpen.value = false; }; }, []);
  const lang = language.value, copy = entryCopy(lang);
  const save = (event: Event) => { event.preventDefault(); onDone(saveFirstUse({...boat, profile: 'boat'}, storage, lang).notices); };
  return (
    <form ref={form} class="app-boat-entry" aria-labelledby="first-use-boat-legend" tabIndex={-1} onSubmit={save} data-first-use-boat="">
      <fieldset class="app-limits" aria-describedby="first-run-boat-hint">
        <legend id="first-use-boat-legend">{copy.legend}</legend>
        <p class="app-limits-hint">{copy.line}</p>
        {entryFields(lang).map(([name, label]) => (
          <div class="app-limits-field" key={name}>
            <label for={`first-run-boat-${name}`}>{label}</label>
            <input id={`first-run-boat-${name}`} name={name} type="number" step="any" inputMode="decimal" value={boat[name]}
              onInput={event => setBoat({...boat, [name]: (event.currentTarget as HTMLInputElement).value})} />
          </div>
        ))}
        <span id="first-run-boat-hint" class="app-limits-hint ui-mono">{copy.lengthHint} · {copy.limitsHint}</span>
      </fieldset>
      <div class="app-boat-entry-actions">
        <Button type="submit" variant="primary">{t('boatEntry.save', lang)}</Button>
        <Button variant="quiet" onClick={() => onDone([])}>{t('boatEntry.skip', lang)}</Button>
      </div>
    </form>
  );
}

export function FirstRun({href, storage, cookies}: {href?: string; storage?: StoreStorage | null; cookies?: CookieJar | null} = {}) {
  const at = href ?? (typeof location === 'undefined' ? 'https://skippercast.com/map' : location.href);
  const [due, setDue] = useState(() => firstRunDue(at, storage, cookies));
  // A home saved on /coast already chose the mode: apply it (the address names none) rather than ask again.
  useEffect(() => { const saved = savedFirstRun(at, storage, cookies); if (saved) setParams({profile: saved}); }, []);
  // The boat fields: 'chosen' when Boat was chosen here (focus follows), 'carried' when the landing's Boat choice opened this page.
  const [ask, setAsk] = useState<'chosen' | 'carried' | null>(null);
  // MYB-1: what saving the boat reported, shown after the fields close.
  const [notices, setNotices] = useState<string[]>([]);
  useEffect(() => {
    if (takeAsk(at) && readURL(at).profile === 'boat') setAsk('carried');
    try { if (new URL(at).searchParams.has(ASK_PARAM)) history.replaceState(history.state, '', withoutAsk(location.href)); } catch { /* keep the address */ }
  }, []);
  const lang = language.value;
  const notice = notices.length ? (
    <div class="app-firstrun-notice" role="status" data-first-use-notice="">
      <span>{notices.join(' ')}</span>
      <Button variant="quiet" size="sm" onClick={() => setNotices([])}>{t('firstRun.dismiss', lang)}</Button>
    </div>
  ) : null;
  if (!due) {
    if (ask) return <BoatEntry storage={storage} focus={ask === 'chosen'} onDone={held => { setAsk(null); setNotices(held); }} />;
    return notice ? <section class="app-firstrun" aria-label={t('firstRun.boat', lang)}>{notice}</section> : null;
  }
  // The choice finishes the card as before; choosing Boat then asks for the boat (SC-LANDING-ORDER). "Keep Boat for now" asks nothing more.
  const choose = (p: Profile, keep = false) => { setDue(false); setParams(p === DEFAULT_PROFILE ? {profile: p} : {profile: p, target: null}); if (p === 'boat' && !keep) setAsk('chosen'); };
  return (
    <section class="app-firstrun" role="dialog" aria-labelledby="first-run-title" data-first-run="">
      <span class="ui-eyebrow">{t('firstRun.eyebrow', lang)}</span>
      <h2 id="first-run-title">{t('firstRun.title', lang)}</h2>
      <p>{t('firstRun.intro', lang)}</p>
      <div class="app-firstrun-options">
        {PROFILES.map(p => (
          <Button key={p} icon={p} data-profile={p} onClick={() => choose(p)}>
            <span><strong>{t(`where.profile.${p}`, lang)}</strong><small>{t(`landing.profile.note.${p}`, lang)}</small></span>
          </Button>
        ))}
      </div>
      <Button variant="quiet" size="sm" onClick={() => choose(DEFAULT_PROFILE, true)}>{t('firstRun.keep', lang, {profile: t(`where.profile.${DEFAULT_PROFILE}`, lang)})}</Button>
    </section>
  );
}
