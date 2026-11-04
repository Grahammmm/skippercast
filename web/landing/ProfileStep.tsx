// The guided first run's second step (#622, walkthrough slice 4): after a
// port is chosen, "How do you fish?" with the four profiles and what each
// changes, while the chosen region warms in the background (region-warm.ts).
// The status line says only that the map files are loading or ready; a
// failed or skipped warm-up says nothing, because the map loads as it would
// have. "Change port" goes back to the port step. Focus moves to the heading
// when the step appears, so keyboard and screen-reader users land on it.
// MYB-1's boat fields come after this choice, not in it (SC-LANDING-ORDER):
// choosing Boat opens the map asking for the boat (Landing.tsx, boat-entry.ts carryAsk).
import {useEffect, useRef} from 'preact/hooks';
import {Button} from '../ui/Button.tsx';
import {PROFILES, type Profile} from '../profile.ts';
import {language, t} from './i18n.ts';
import type {WarmState} from './region-warm.ts';

/** The English step copy (the catalogue's en values, equal to the strings this file carried before SC0707-05); the rendered text follows the page language. */
export const STEP_COPY = {
  title: t('landing.step.title', 'en'),
  intro: t('landing.step.intro', 'en'),
  back: t('landing.step.back', 'en'),
  loading: (place: string): string => t('landing.step.loading', 'en', {place}),
  ready: (place: string): string => t('landing.step.ready', 'en', {place}),
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
  const lang = language.value;
  const status = warm === 'loading' ? t('landing.step.loading', lang, {place}) : warm === 'ready' ? t('landing.step.ready', lang, {place}) : '';
  return (
    <section class="landing-step" aria-labelledby="landing-step-title" data-step="profile">
      <p class="ui-eyebrow landing-step-place">{place}</p>
      <h2 id="landing-step-title" ref={heading} tabIndex={-1}>{t('landing.step.title', lang)}</h2>
      <p class="landing-step-intro">{t('landing.step.intro', lang)}</p>
      <div class="landing-step-options">
        {PROFILES.map(p => (
          <Button key={p} icon={p} data-profile={p} pressed={current === null ? undefined : p === current} onClick={() => onChoose(p)}>
            <span><strong>{t(`where.profile.${p}`, lang)}</strong><small>{t(`landing.profile.note.${p}`, lang)}</small></span>
          </Button>
        ))}
      </div>
      <p class="landing-step-status" role="status" data-warm={warm ?? undefined}>{status}</p>
      <Button variant="quiet" size="sm" class="landing-step-back" onClick={onBack}>{t('landing.step.back', lang)}</Button>
    </section>
  );
}
