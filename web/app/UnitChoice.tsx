import {useId} from 'preact/hooks';
import {Button} from '../ui/Button.tsx';
import {language, t} from '../i18n.ts';
import {units, setUnits, type Units} from '../unit-choice.ts';

export function UnitChoice() {
  const id = useId(), current = units.value.temp, lang = language.value;
  const choose = (temp: Units['temp']) => (event: Event) => {
    setUnits({temp});
    (event.currentTarget as HTMLElement | null)?.focus();
  };
  return <section aria-labelledby={`${id}-units`}>
    <h2 id={`${id}-units`} class="ui-eyebrow">{t('units.temperature', lang)}</h2>
    <div class="app-account-presets">
      <Button size="sm" pressed={current === 'F'} onClick={choose('F')}>{t('units.fahrenheit', lang)}</Button>
      <Button size="sm" pressed={current === 'C'} onClick={choose('C')}>{t('units.celsius', lang)}</Button>
    </div>
  </section>;
}
