// The guided first run's second step (#622, walkthrough slice 4): after a
// port is chosen, "How do you fish?" with the four profiles and what each
// changes, while the chosen region warms in the background (region-warm.ts).
// The status line says only that the map files are loading or loaded; a
// failed or skipped warm-up says nothing, because the map loads as it would
// have. "Change port" goes back to the port step. Focus moves to the heading
// when the step appears, so keyboard and screen-reader users land on it.
import {useEffect, useRef} from 'preact/hooks';
import {Button} from '../ui/Button.tsx';
import {PROFILE_NOTES, PROFILE_TABLE, PROFILES, type Profile} from '../profile.ts';
import type {WarmState} from './region-warm.ts';

export const STEP_COPY = {
  title: 'How do you fish?',
  intro: 'This sets the depth limit, the species list and the map’s layers. Change it any time from the map.',
  back: 'Change port',
  loading: (place: string): string => `Loading the ${place} map…`,
  ready: (place: string): string => `${place} map loaded.`,
} as const;

export type ProfileStepProps = {
  /** The chosen port's name, or the area's ("Central coast"). */
  place: string;
  /** The warm-up's state; null when nothing is warmed (Explore the coast). */
  warm: WarmState | null;
  /** The stored profile, shown pressed. */
  current?: Profile | null;
  onChoose: (profile: Profile) => void;
  onBack: () => void;
};

export function ProfileStep({place, warm, current = null, onChoose, onBack}: ProfileStepProps) {
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => { heading.current?.focus(); }, []);
  const status = warm === 'loading' ? STEP_COPY.loading(place) : warm === 'ready' ? STEP_COPY.ready(place) : '';
  return (
    <section class="landing-step" aria-labelledby="landing-step-title" data-step="profile">
      <p class="ui-eyebrow landing-step-place">{place}</p>
      <h2 id="landing-step-title" ref={heading} tabIndex={-1}>{STEP_COPY.title}</h2>
      <p class="landing-step-intro">{STEP_COPY.intro}</p>
      <div class="landing-step-options">
        {PROFILES.map(p => (
          <Button key={p} icon={p} data-profile={p} pressed={current === null ? undefined : p === current} onClick={() => onChoose(p)}>
            <span><strong>{PROFILE_TABLE[p].label}</strong><small>{PROFILE_NOTES[p]}</small></span>
          </Button>
        ))}
      </div>
      <p class="landing-step-status" role="status" data-warm={warm ?? undefined}>{status}</p>
      <Button variant="quiet" size="sm" class="landing-step-back" onClick={onBack}>{STEP_COPY.back}</Button>
    </section>
  );
}
