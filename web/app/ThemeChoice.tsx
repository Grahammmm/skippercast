import {useId} from 'preact/hooks';
import {language, t} from '../i18n.ts';
import {setThemeChoice, themeChoice} from '../theme-choice.ts';
import {Button} from '../ui/Button.tsx';

export function ThemeChoice() {
  const id = useId(), current = themeChoice.value, lang = language.value;
  return (
    <section aria-labelledby={`${id}-theme`} aria-describedby={`${id}-theme-note`}>
      <h2 id={`${id}-theme`} class="ui-eyebrow">{t('theme.title', lang)}</h2>
      <p id={`${id}-theme-note`}>{t('theme.autoNote', lang)}</p>
      <div class="app-account-presets app-account-presets--wind">
        {(['auto', 'light', 'dark'] as const).map(choice =>
          <Button key={choice} size="sm" pressed={current === choice} onClick={event => {
            setThemeChoice(choice);
            event.currentTarget.focus();
          }}>{t(`theme.${choice}`, lang)}</Button>
        )}
      </div>
    </section>
  );
}
