// BF-one-answer: the one line the app leads with, rendered from web/first-answer.ts. Split out of App.tsx so it
// is one covered surface of the string catalogue (BF-spanish-app): its words come from catalog/app/strings.json
// in the page's language; the reason is the brief's own verdict sentence (web/brief/verdict.ts), which
// currentVerdict phrases in the page's language from the same catalogue (web/brief/verdict-copy.ts).
// SC1722-01: a forecast that could not be read says so with a Try again (Brief.tsx ForecastFailure) in place of the verdict line.
import {useEffect} from 'preact/hooks';
import {Button} from '../ui/Button.tsx';
import {currentVerdict, DockVerdictGuard, ForecastFailure, forecastGate, leadBrief, leadDate, leadDayText} from '../brief/Brief.tsx';
import {firstAnswer} from '../first-answer.ts';
import {language, t} from '../i18n.ts';
import {isProfile, PROFILE_TABLE} from '../profile.ts';
import {loadRegs, regsData} from '../regs.ts';
import {profile, readStored, species, STORAGE_KEYS} from '../state.ts';
import {DEFAULT_ZONE} from '../zone.ts';
import {regionInfo} from './region-info.ts';

/** BF-one-answer: whether the address or storage names a profile; if neither, the line says which it assumed. */
const profileChosen = (): boolean => {
  try { return isProfile(new URLSearchParams(location.search).get('profile')) || isProfile(readStored(STORAGE_KEYS.profile)); } catch { return false; }
};

/** BF-one-answer: the app leads with one answer (web/first-answer.ts) above the desktop map; the detail stays below it. The mobile layout fills the viewport with the map and leads with the same verdict at the sheet's peek. SC1407-05: guarded like the brief's verdict while the dock's hour settles. */
export const FirstAnswerLine = ({now = new Date()}: {now?: Date} = {}) => <DockVerdictGuard><SettledFirstAnswer now={now} /></DockVerdictGuard>;

/** The first answer for the settled day and hour. */
function SettledFirstAnswer({now}: {now: Date}) {
  const info = regionInfo.value, rules = info?.rules ?? null, brief = leadBrief(now), date = leadDate(now, brief), lang = language.value;
  useEffect(() => { if (rules) void loadRegs(rules); }, [rules?.id]);
  const loaded = regsData.value, p = profile.value, gate = forecastGate(brief);
  // No weather answer while the forecast is unread: the verdict is left out, the legality note stays.
  const unread = gate === 'failed' || gate === 'waiting';
  const a = firstAnswer({verdict: unread ? null : currentVerdict(brief, now), rules, regs: rules && loaded?.region === rules.id ? loaded.data : null, lang,
    target: species.value ?? PROFILE_TABLE[p].defaultTarget, date, day: leadDayText(date, now, info?.timezone ?? DEFAULT_ZONE, lang), now, profile: p, chosen: profileChosen()});
  return (
    <section class="app-first-answer" aria-label={t('fa.aria', lang)} data-fishable={unread ? undefined : a.fishable} data-forecast={unread ? gate : undefined} data-as-of={a.asOf}>
      {gate === 'failed' ? <ForecastFailure as="h2" /> : <>
        <h2 class="app-first-answer-line">{gate === 'waiting' ? t('common.waiting', lang) : a.line}</h2>
        {gate === 'waiting' ? null : <p class="app-first-answer-reason">{a.reason}</p>}
        {gate === 'saved-failed' ? <ForecastFailure as="p" /> : null}
      </>}
      <p class="app-first-answer-rules">{a.legalityNote} <a href={a.rulesHref} target="_blank" rel="noopener">{t('rules.link.official', lang)}</a></p>
      <Button class="app-first-answer-more" onClick={() => document.querySelector('.app-main, .app-mobile')?.scrollIntoView?.()}>{t('fa.more', lang)}</Button>
    </section>
  );
}
