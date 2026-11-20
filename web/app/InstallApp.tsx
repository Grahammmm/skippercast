import {installable, isIosSafari, isStandalone, requestInstall} from '../install-app.ts';
import {language, t} from '../i18n.ts';
import {Button} from '../ui/Button.tsx';

export function InstallApp({win = typeof window === 'undefined' ? undefined : window}: {win?: Window} = {}) {
  const event = installable.value, lang = language.value;
  if (!win || isStandalone(win)) return null;
  if (event) return <li><Button size="sm" variant="quiet" onClick={requestInstall}>{t('install.action', lang)}</Button></li>;
  return isIosSafari(win.navigator.userAgent) ? <li>{t('install.iosHint', lang)}</li> : null;
}
