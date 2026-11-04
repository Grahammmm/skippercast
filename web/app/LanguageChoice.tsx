// SC0452-08: the app menu's language choice. Two buttons, each labelled in its own language in both
// languages (so a visitor in the wrong one can still find theirs); the pressed one is the page's
// language. A choice is web/i18n.ts setLanguage: it stores the preference and re-renders every covered
// surface through the shared `language` signal, with no reload.
import {useId} from 'preact/hooks';
import {Button} from '../ui/Button.tsx';
import {language, setLanguage, t, type Language} from '../i18n.ts';

export function LanguageChoice() {
  const id = useId();
  const current = language.value;
  const choose = (lang: Language) => (event: Event) => {
    setLanguage(lang);
    (event.currentTarget as HTMLElement | null)?.focus();   // the activated button keeps focus; Safari does not focus on click
  };
  return (
    <section aria-labelledby={`${id}-language`}>
      <h2 id={`${id}-language`} class="ui-eyebrow">{t('menu.language', current)}</h2>
      <div class="app-account-presets">
        <Button size="sm" lang="en" pressed={current === 'en'} onClick={choose('en')}>{t('menu.language.en', current)}</Button>
        <Button size="sm" lang="es" pressed={current === 'es'} onClick={choose('es')}>{t('menu.language.es', current)}</Button>
      </div>
    </section>
  );
}
