import {useId} from 'preact/hooks';
import {language, t} from '../i18n.ts';
import {setThemeChoice, themeChoice} from '../theme-choice.ts';
import {Button} from '../ui/Button.tsx';

/** `inMenu`: the layer menu's own row, a labelled group rather than a second "Map theme" region beside the account menu's. */
export function ThemeChoice({inMenu = false}: {inMenu?: boolean} = {}) {
  const id = useId(), current = themeChoice.value, lang = language.value;
  const Box = inMenu ? 'div' : 'section';
  return (
    <Box aria-labelledby={`${id}-theme`} aria-describedby={`${id}-theme-note`} role={inMenu ? 'group' : undefined} class={inMenu ? 'app-rail-theme' : undefined}>
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
    </Box>
  );
}
