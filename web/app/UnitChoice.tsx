import {useId} from 'preact/hooks';
import {Button} from '../ui/Button.tsx';
import {language, t} from '../i18n.ts';
import {units, setUnits, type Units} from '../unit-choice.ts';

export function UnitChoice() {
  const id = useId(), current = units.value, lang = language.value;
  const choose = (next: Partial<Units>) => (event: Event) => {
    setUnits(next);
    (event.currentTarget as HTMLElement | null)?.focus();
  };
  return <><section aria-labelledby={`${id}-units`}>
    <h2 id={`${id}-units`} class="ui-eyebrow">{t('units.temperature', lang)}</h2>
    <div class="app-account-presets">
      <Button size="sm" pressed={current.temp === 'F'} onClick={choose({temp: 'F'})}>{t('units.fahrenheit', lang)}</Button>
      <Button size="sm" pressed={current.temp === 'C'} onClick={choose({temp: 'C'})}>{t('units.celsius', lang)}</Button>
    </div>
  </section><section aria-labelledby={`${id}-wind`}>
    <h2 id={`${id}-wind`} class="ui-eyebrow">{t('units.wind.speed', lang)}</h2>
    <div class="app-account-presets">{(['kt', 'mph', 'kmh'] as const).map(wind =>
      <Button key={wind} size="sm" pressed={current.wind === wind} onClick={choose({wind})}>{t(`units.wind.${wind}`, lang)}</Button>)}
    </div>
  </section></>;
}
