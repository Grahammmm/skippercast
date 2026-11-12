// SC2037-11: the planner says whether each target species is open on the plan's date, from the same reviewed
// rules the rules card and the plan view read (web/regs.ts). Display only: nothing here reaches the GPX, the
// offline notes, a saved trip or the alert plan, and it never blocks saving or exporting.
// SC1407-13: the card's own words follow the page's language (catalog/app/strings.json planRules.*); the
// registry's reason and its bag and size clauses stay in the registry's English, marked lang="en", and say so.
import {useEffect} from 'preact/hooks';
import {freshnessLabel, loadRegs, regsData, regulationState, ruleReason, ruleSummary, verifiedText, type RulesRegion} from '../regs.ts';
import {language, t, type Language} from '../i18n.ts';
import {currentRegionInfo} from './region-info.ts';

export const CHECK_RULES = t('planRules.check', 'en');
export const NOT_LEGAL_ADVICE = t('planRules.notLegalAdvice', 'en');
/** A plan's species as the registry's ids: the combined reef plan is one line each for lingcod and rockfish. */
export const ruleSpecies = (species: string): string[] => species === 'reef' ? ['lingcod', 'rockfish'] : [species];

export interface PlanRuleLine {
  id: string; name: string;
  /** closed: said plainly; open: restricted, scheduled and the like keep the card's own label; check: anything not confirmed. */
  kind: 'open' | 'closed' | 'check';
  status: string; label: string; reason: string; /** The reason is the registry's own English wording on a Spanish page. */ english: boolean; limits: string[]; verified: string; fresh: string; link: string; linkLabel: string;
}

/** The line, with its limits split into the registry's own (English) bag and size clauses and the app-written depth line. */
function readLine(data: unknown, species: string, date: string, region: RulesRegion, now: number, lang: Language) {
  const state = regulationState(data, species, region, now, date, null), s = ruleSummary(data, species, state, region, lang), fresh = freshnessLabel(data, species, state, region, now, lang);
  const confirmed = (fresh.state === 'checked-today' || fresh.state === 'checked-earlier') && !state.overdue;
  const kind = s.status === 'unknown' || !confirmed ? 'check' : s.status === 'closed' ? 'closed' : 'open';
  const name = state.profile?.name ?? species, official = [...s.bag, ...s.size];
  const line: PlanRuleLine = {id: species, name, kind, status: s.status, label: kind === 'check' && s.status !== 'unknown' ? t('rules.status.unknown', lang) : s.label,
    reason: ruleReason(state, lang).text, english: ruleReason(state, lang).english, limits: [...official, ...(s.depth ? [s.depth] : [])], verified: verifiedText(s, lang), fresh: fresh.text, link: s.link, linkLabel: s.linkLabel};
  return {line, official, depth: s.depth};
}

/** One species' reading for `date` (labels in `lang`). Stale, overdue, unknown and not-reviewed rules, a missing registry, and a season that needs a fishing location are `check`, never `open`. */
export function planRuleLine(data: unknown, species: string, date: string, region: RulesRegion, now: number, lang: Language = 'en'): PlanRuleLine {
  return readLine(data, species, date, region, now, lang).line;
}

export function PlanRules({date, species, region, now = Date.now()}: {date: string; species: string; region: {id: string; timezone?: string}; now?: number}) {
  const info = currentRegionInfo()?.rules, rules: RulesRegion = info && info.id === region.id ? info : {id: region.id, timezone: region.timezone};
  const lang = language.value, english = lang === 'es' ? 'en' : undefined;
  useEffect(() => { void loadRegs(rules); }, [rules.id]);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) return null;
  const loaded = regsData.value, data = loaded?.region === rules.id ? loaded.data : null;
  return <section class="export-card plan-rules" aria-label={t('planRules.aria', lang)}>
    <h2>{t('planRules.heading', lang, {date})}</h2>
    {(() => {
      const reads = ruleSpecies(species).map(id => readLine(data, id, date, rules, now, lang));
      const first = reads[0]!.line;
      // RF1925-3: only readings that are all unconfirmed and identical in badge, reason and freshness share one notice; every species keeps its name and official link.
      const same = reads.length > 1 && reads.every(({line: l}) => l.kind === 'check' && l.status === first.status && l.label === first.label && l.reason === first.reason && l.fresh === first.fresh);
      const note = (l: PlanRuleLine) => l.english ? <><span lang="en">{l.reason}</span> {t('rules.english.inline', lang)}</> : l.reason;
      const link = (l: PlanRuleLine) => <a href={l.link} target="_blank" rel="noopener" hrefLang={english} aria-label={t('rules.link.for', lang, {label: l.linkLabel, name: l.name})}>{l.linkLabel}</a>;
      return <>
        {same ? <div class="plan-rule" data-kind="check" data-status="unknown">
          <p><span class="app-mark-regs-badge" data-status="unknown">{first.label}</span> <strong>{reads.map(r => r.line.name).join(', ')}</strong>. {note(first)}</p>
          <p class="export-note">{first.fresh}</p>
          <p>{reads.map((r, i) => <>{i ? ' ' : null}{link(r.line)}</>)}</p>
        </div> : reads.map(({line: l, official, depth}) => <div key={l.id} class="plan-rule" data-kind={l.kind} data-status={l.kind === 'check' ? 'unknown' : l.status}>
          <p><span class="app-mark-regs-badge" data-status={l.kind === 'check' ? 'unknown' : l.status}>{l.label}</span> <strong>{l.name}</strong>. {l.kind === 'closed' ? `${t('planRules.closedOn', lang, {date})} ` : ''}{note(l)}</p>
          {l.kind === 'check' ? null : <>
            {official.map((line, i) => <p key={i} lang={english}>{line}</p>)}
            {depth ? <p>{depth}</p> : null}
            {english && official.length ? <p class="export-note">{t('rules.english', lang)}</p> : null}
            <p>{l.verified}</p>
          </>}
          <p class="export-note">{l.fresh}</p>
          {link(l)}
        </div>)}
        {reads.some(r => r.line.kind === 'check') ? <p>{t('planRules.check', lang)}</p> : null}
      </>;
    })()}
    <p class="export-note">{t('planRules.notLegalAdvice', lang)}</p>
  </section>;
}
