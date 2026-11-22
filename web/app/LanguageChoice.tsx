// SC0452-08: the app menu's language choice. Two buttons, each labelled in its own language in both
// languages (so a visitor in the wrong one can still find theirs); the pressed one is the page's
// language. A choice is web/i18n.ts chooseReadyLanguage: it stores the preference and re-renders every covered
// surface through the shared `language` signal, with no reload. SC1407-09: Spanish applies once its table has
// loaded; a failed load keeps English and says so once, here, and Español stays available to try again.
import {useId} from 'preact/hooks';
import {effect} from '@preact/signals';
import {Button} from '../ui/Button.tsx';
import {catalogueFailed, catalogueLoading, chooseReadyLanguage, language, t, type Language} from '../i18n.ts';

/**
 * SC2052-05: the browser tab's title follows the page language, whether or not the menu is open. English is the static
 * <title> of dist/app.html word for word, so it is never rewritten unless a Spanish title is to be taken back.
 * Bound once after the language is ready (web/app/main.tsx); returns the disposer.
 */
export function bindShellTitle(doc: {title: string}): () => void {
  return effect(() => {
    const next = t('shell.title', language.value);
    if (doc.title !== next) doc.title = next;
  });
}

export function LanguageChoice() {
  const id = useId();
  const current = language.value;
  const choose = (lang: Language) => (event: Event) => {
    void chooseReadyLanguage(lang);
    (event.currentTarget as HTMLElement | null)?.focus();   // the activated button keeps focus; Safari does not focus on click
  };
  return (
    <section aria-labelledby={`${id}-language`}>
      <h2 id={`${id}-language`} class="ui-eyebrow">{t('menu.language', current)}</h2>
      <div class="app-account-presets" aria-busy={catalogueLoading.value ? 'true' : undefined}>
        <Button size="sm" lang="en" pressed={current === 'en'} onClick={choose('en')}>{t('menu.language.en', current)}</Button>
        <Button size="sm" lang="es" pressed={current === 'es'} onClick={choose('es')}>{t('menu.language.es', current)}</Button>
      </div>
      <span role="status">{catalogueFailed.value ? t('language.loadFailed', current) : ''}</span>
    </section>
  );
}
