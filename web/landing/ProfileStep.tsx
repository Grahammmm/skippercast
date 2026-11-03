// The guided first run's second step (#622, walkthrough slice 4): after a
// port is chosen, "How do you fish?" with the four profiles and what each
// changes, while the chosen region warms in the background (region-warm.ts).
// The status line says only that the map files are loading or ready; a
// failed or skipped warm-up says nothing, because the map loads as it would
// have. "Change port" goes back to the port step. Focus moves to the heading
// when the step appears, so keyboard and screen-reader users land on it.
import {useEffect, useRef, useState} from 'preact/hooks';
import {ENTRY_COPY, ENTRY_FIELDS, saveFirstUse} from '../boat-entry.ts';
import {Button} from '../ui/Button.tsx';
import {PROFILE_NOTES, PROFILE_TABLE, PROFILES, type Profile} from '../profile.ts';
import type {WarmState} from './region-warm.ts';

export const STEP_COPY = {
  title: 'How do you fish?',
  intro: 'This sets the depth limit, the species list and the map’s layers. Change it any time from the map.',
  back: 'Change port',
  loading: (place: string): string => `Loading the ${place} map…`,
  ready: (place: string): string => `${place} map files ready.`,
} as const;

export type ProfileStepProps = {
  /** The chosen port's name, or the area's ("Central coast"). */
  place: string;
  /** The warm-up's state; null when nothing is warmed (Explore the coast). */
  warm: WarmState | null;
  /** The stored profile, shown pressed. */
  current?: Profile | null;
  /** `notices`: what saving the boat fields reported (MYB-1), for the page the choice opens to show. */
  onChoose: (profile: Profile, notices?: readonly string[]) => void;
  onBack: () => void;
};

export function ProfileStep({place, warm, current = null, onChoose, onBack}: ProfileStepProps) {
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => { heading.current?.focus(); }, []);
  const [boat, setBoat] = useState({lengthFt: '', wind: '', seas: ''});
  const [notices, setNotices] = useState<string[]>([]);
  // MYB-1: save what the boat fields hold, then the choice finishes the step as before.
  // The notices go to onChoose too: the landing navigates at once and carries them to the map (boat-entry.ts carryNotices).
  const pick = (p: Profile) => { const saved = saveFirstUse({...boat, profile: p}); if (saved.notices.length) setNotices(saved.notices); onChoose(p, saved.notices); };
  const status = warm === 'loading' ? STEP_COPY.loading(place) : warm === 'ready' ? STEP_COPY.ready(place) : '';
  return (
    <section class="landing-step" aria-labelledby="landing-step-title" data-step="profile">
      <p class="ui-eyebrow landing-step-place">{place}</p>
      <h2 id="landing-step-title" ref={heading} tabIndex={-1}>{STEP_COPY.title}</h2>
      <p class="landing-step-intro">{STEP_COPY.intro}</p>
      <fieldset class="app-limits" aria-describedby="landing-boat-hint">
        <legend>{ENTRY_COPY.legend}</legend>
        <p class="app-limits-hint">{ENTRY_COPY.line}</p>
        {ENTRY_FIELDS.map(([name, label]) => (
          <div class="app-limits-field" key={name}>
            <label for={`landing-boat-${name}`}>{label}</label>
            <input id={`landing-boat-${name}`} name={name} type="number" inputMode="decimal" value={boat[name]}
              onInput={event => setBoat({...boat, [name]: (event.currentTarget as HTMLInputElement).value})} />
          </div>
        ))}
        <span id="landing-boat-hint" class="app-limits-hint ui-mono">{ENTRY_COPY.lengthHint} · {ENTRY_COPY.limitsHint}</span>
        {notices.length ? <p class="app-limits-hint" role="status">{notices.join(' ')}</p> : null}
      </fieldset>
      <div class="landing-step-options">
        {PROFILES.map(p => (
          <Button key={p} icon={p} data-profile={p} pressed={current === null ? undefined : p === current} onClick={() => pick(p)}>
            <span><strong>{PROFILE_TABLE[p].label}</strong><small>{PROFILE_NOTES[p]}</small></span>
          </Button>
        ))}
      </div>
      <p class="landing-step-status" role="status" data-warm={warm ?? undefined}>{status}</p>
      <Button variant="quiet" size="sm" class="landing-step-back" onClick={onBack}>{STEP_COPY.back}</Button>
    </section>
  );
}
