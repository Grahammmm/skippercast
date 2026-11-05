import {PortDialog} from '../landing/PortInput.tsx';
import {Button} from '../ui/Button.tsx';
import {language, t} from '../i18n.ts';
import {tourSteps, type TourAction} from '../tour.ts';

/** Opened only on request, leaving FirstRun and the one-time camera tour alone. */
export function ControlsTour({step, act}: {step: number; act: (action: TourAction) => void}) {
  const lang = language.value, steps = tourSteps(lang), current = steps[step];
  if (!current) return null;
  return (
    <PortDialog open title={t('tour.title', lang)} onClose={() => act('close')}>
      <div aria-live="polite" aria-atomic="true">
        <p class="ui-eyebrow">{t('tour.step', lang, {n: step + 1, m: steps.length})}</p>
        <h3>{current.title}</h3>
        <p>{current.text}</p>
      </div>
      <div class="port-input-actions">
        <Button variant="quiet" onClick={() => act('close')}>{t('tour.skip', lang)}</Button>
        <Button disabled={step === 0} onClick={() => act('back')}>{t('tour.back', lang)}</Button>
        <Button variant="primary" onClick={() => act('next')}>{step === steps.length - 1 ? t('tour.finish', lang) : t('tour.next', lang)}</Button>
      </div>
    </PortDialog>
  );
}
