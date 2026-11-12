// UXFIX-02: one place that renders web/regs.ts ruleReason(). App-worded reasons are plain text; the registry's own
// English wording and a geography note (region data) are separate lang="en" spans, so a Spanish page never shows
// English as if it were Spanish. `marked` adds the "(in English)" note after each English span.
import {t, type Language} from '../i18n.ts';
import type {ruleReason} from '../regs.ts';

export function RuleReason({reason, lang, marked = true}: {reason: ReturnType<typeof ruleReason>; lang: Language; marked?: boolean}) {
  const tag = marked ? <> {t('rules.english.inline', lang)}</> : null;
  return <>
    {reason.english ? <><span lang="en">{reason.text}</span>{tag}</> : reason.text}
    {reason.note ? <> <span lang="en">{reason.note}</span>{tag}</> : null}
  </>;
}
