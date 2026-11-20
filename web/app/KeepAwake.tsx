import {language, t} from '../i18n.ts';
import {keepAwake} from '../wake-lock.ts';
import {Button} from '../ui/Button.tsx';

export function KeepAwake({control = keepAwake()}: {control?: ReturnType<typeof keepAwake>} = {}) {
  const lang = language.value;
  if (!control.supported()) return null;
  return <span>
    <Button size="sm" pressed={control.enabled.value} onClick={() => control.set(!control.enabled.value)}>{t('keepAwake.label', lang)}</Button>
    <span role="status">{control.status.value ? t('keepAwake.failed', lang) : ''}</span>
  </span>;
}
