// One opt-in controls tour, shared by desktop and mobile. No onboarding,
// profile or flyover storage is read or reset when the tour is replayed.
import {t, type Language} from './i18n.ts';

/** The four tour steps in `lang` (English by default). */
export const tourSteps = (lang: Language = 'en') => [
  {title: t('tour.s1.title', lang), text: t('tour.s1.text', lang)},
  {title: t('tour.s2.title', lang), text: t('tour.s2.text', lang)},
  {title: t('tour.s3.title', lang), text: t('tour.s3.text', lang)},
  {title: t('tour.s4.title', lang), text: t('tour.s4.text', lang)},
] as const;
export const TOUR_STEPS = tourSteps('en');

export type TourState = number | null;
export type TourAction = 'replay' | 'next' | 'back' | 'close';
/** Replay always starts at the beginning, including after skip or completion; an impossible step closes the tour. */
export function tourTransition(step: TourState, action: TourAction): TourState {
  if (action === 'replay') return 0;
  if (action === 'close' || step === null || !Number.isInteger(step) || step < 0 || step >= TOUR_STEPS.length) return null;
  if (action !== 'back' && action !== 'next') return null;
  if (action === 'back') return Math.max(0, step - 1);
  return step + 1 < TOUR_STEPS.length ? step + 1 : null;
}
