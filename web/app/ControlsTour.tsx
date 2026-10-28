import {PortDialog} from '../landing/PortInput.tsx';
import {Button} from '../ui/Button.tsx';
import {TOUR_STEPS, type TourAction} from '../tour.ts';

/** Opened only on request, leaving FirstRun and the one-time camera tour alone. */
export function ControlsTour({step, act}: {step: number; act: (action: TourAction) => void}) {
  const current = TOUR_STEPS[step];
  if (!current) return null;
  return (
    <PortDialog open title="Controls tour" onClose={() => act('close')}>
      <div aria-live="polite" aria-atomic="true">
        <p class="ui-eyebrow">Step {step + 1} of {TOUR_STEPS.length}</p>
        <h3>{current.title}</h3>
        <p>{current.text}</p>
      </div>
      <div class="port-input-actions">
        <Button variant="quiet" onClick={() => act('close')}>Skip tour</Button>
        <Button disabled={step === 0} onClick={() => act('back')}>Back</Button>
        <Button variant="primary" onClick={() => act('next')}>{step === TOUR_STEPS.length - 1 ? 'Finish' : 'Next'}</Button>
      </div>
    </PortDialog>
  );
}
