// One opt-in controls tour, shared by desktop and mobile. No onboarding,
// profile or flyover storage is read or reset when the tour is replayed.
export const TOUR_STEPS = [
  {title: 'Time dock', text: 'Use the day buttons and hour slider below the map to choose a forecast time. Check the displayed time before reading a layer.'},
  {title: 'Layer list', text: 'Use the layer list beside the map, or open Layers on a phone. Each layer explains its source and limits; unavailable layers are not evidence of clear conditions.'},
  {title: 'Save for offline', text: 'Open the account menu and choose Save for offline after choosing a port. Review what is saved and its date before leaving your connection.'},
  {title: 'Evidence-limit line', text: 'Read the limit below the brief: habitat describes a place to look, while fish presence is unverified. A map layer is not a safety clearance.'},
] as const;

export type TourState = number | null;
export type TourAction = 'replay' | 'next' | 'back' | 'close';
/** Replay always starts at the beginning, including after skip or completion. */
export function tourTransition(step: TourState, action: TourAction): TourState {
  if (action === 'replay') return 0;
  if (action === 'close' || step === null) return null;
  if (action === 'back') return Math.max(0, step - 1);
  return step + 1 < TOUR_STEPS.length ? step + 1 : null;
}
