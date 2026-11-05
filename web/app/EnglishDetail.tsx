import type {ComponentChildren} from 'preact';
import {t, type Language} from '../i18n.ts';

/**
 * Text a producer wrote in English at run time (a layer's status, age, source note or credit): English shows it as
 * it is; Spanish shows it whole, marked lang="en" and led by one catalogue prefix per block, so it is never
 * mistaken for a Spanish sentence and no caveat in it is dropped or parsed. `prefix` false: a short label inside a
 * block that already carries one.
 */
export function EnglishDetail({lang, children, prefix = true}: {lang: Language; children?: ComponentChildren; prefix?: boolean}) {
  if (lang !== 'es' || children === '' || children === null || children === undefined || children === false) return <>{children}</>;
  return <>{prefix ? t('legend.detailsPrefix', lang) : null}<span lang="en">{children}</span></>;
}
