// The selected-mark card's rules at a glance (FE-54, design § 6 and § 9), split out of MarkCard.tsx so the
// rules card is one covered surface of the string catalogue (BF-spanish-app, catalog/app/strings.json).
// Labels follow the page's language; the registry's own bag and size clauses stay in the registry's
// English, are marked lang="en", and the card says so (rules.english). Never paraphrased into Spanish.
import {useEffect} from 'preact/hooks';
import {PROFILE_TABLE} from '../profile.ts';
import {markData} from '../map/marks.ts';
import {areaPageOnly, freshnessLabel, loadRegs, regsData, regulationState, ruleSummary, speciesPage, verifiedText, type RulesRegion} from '../regs.ts';
import {language, t} from '../i18n.ts';
import {profile, species} from '../state.ts';
import {zone} from './region-info.ts';
import {dockState} from './TimeDock.tsx';
import type {Mark} from './MarkCard.tsx';

/** The cards that speak for a place to fish, so carry the target's rules. */
const RULED = /^(?:spot|survey|geology|habitat|charter):/;

/** The target's rules at a glance for the dock's hour, or nothing while the region loads. */
export function RulesLine({mark}: {mark: Mark}) {
  const region = markData.value?.region as RulesRegion | undefined, loaded = regsData.value, lang = language.value;
  // Each selected card asks again (loadRegs reads once unless the last read failed), so the retained line retries on A→B.
  useEffect(() => { if (region) void loadRegs(region); }, [region?.id, mark.id]);
  if (!region || !RULED.test(mark.id) || mark.withheld) return null;
  const target = species.value ?? PROFILE_TABLE[profile.value].defaultTarget, data = loaded?.region === region.id ? loaded.data : null;
  const at = dockState(new Date(), zone()).at, day = new Intl.DateTimeFormat('en-CA', {timeZone: zone(), year: 'numeric', month: '2-digit', day: '2-digit'}).format(new Date(at));
  const state = regulationState(data, target, region, Date.now(), day, at), s = ruleSummary(data, target, state, region, lang), page = speciesPage(data, target, region, lang), fresh = freshnessLabel(data, target, state, region, Date.now(), lang);
  const name = target === 'reef' ? 'Lingcod & rockfish' : state.profile?.name ?? target, wording = lang === 'es' ? 'en' : undefined;
  const cell = (label: string, values: readonly string[]) => values.length ? <div><dt>{label}</dt>{values.map(v => <dd key={v} class="ui-mono" lang={wording}>{v}</dd>)}</div> : null;
  return (
    <div class="app-mark-regs" role="group" aria-label={t('rules.glance', lang, {name})}>
      <p><span class="app-mark-regs-badge" data-status={s.status}>{s.label}</span> <span class="ui-mono">{verifiedText(s, lang)}</span></p>
      <p class="app-mark-regs-fresh ui-mono" data-state={fresh.state}>{fresh.text}</p>
      <dl>{cell(t('rules.bag', lang), s.bag)}{cell(t('rules.size', lang), s.size)}{cell(t('rules.depth', lang), s.depth ? [s.depth] : [])}</dl>
      {page && <a href={page.href} target="_blank" rel="noopener" aria-label={t('rules.link.page', lang, {label: page.label})}>{page.label}</a>}
      <a href={s.link} target="_blank" rel="noopener" aria-label={t('rules.link.for', lang, {label: s.linkLabel, name})}>{s.linkLabel}</a>
      {areaPageOnly(s, page) && <p class="app-mark-regs-note">{t('rules.areaonly', lang, {name})}</p>}
      {wording && (s.bag.length || s.size.length) ? <p class="app-mark-regs-note">{t('rules.english', lang)}</p> : null}
    </div>
  );
}
