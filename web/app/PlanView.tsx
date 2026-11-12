import {useEffect, useRef} from 'preact/hooks';
import {planCopy, planView} from '../plan.ts';
import {PROFILE_TABLE} from '../profile.ts';
import {regionCoverage, regionPlans, targetLabel, targetState, TARGET_STATE_TEXT} from '../species.ts';
import {appView, navigate, profile, region, species, withParams} from '../state.ts';
import {freshnessLabel, loadRegs, regsData, regulationState, ruleReason, ruleSummary, verifiedText} from '../regs.ts';
import {currentRegionInfo, zone} from './App.tsx';
import {language, t} from '../i18n.ts';
import {dockState} from './TimeDock.tsx';
import {RuleReason} from './RuleReason.tsx';
import {dateTimeFormat} from '../../packages/coast/src/date-format.ts';
import {Button} from '../ui/Button.tsx';
import {openTrip} from '../trip.ts';
import './plan.css';

export function PlanLink() {
  const href = withParams(typeof location === 'undefined' ? 'https://skippercast.test/map' : location.href, {view: 'plan'});
  return <a href={href} onClick={e => { if (!e.button && !e.metaKey && !e.ctrlKey && !e.shiftKey && !e.altKey) { e.preventDefault(); if (appView.value !== 'plan') navigate(withParams(location.href, {view: 'plan'})); } }}>{t('plan.for', language.value, {name: targetLabel(profile.value, region.value, species.value)})}</a>;
}

/** The selected target's existing registry logic, evaluated for the dock's date and instant. */
export function targetRules(now: Date) {
  const rules = currentRegionInfo()?.rules ?? {id: region.value ?? '', timezone: zone()};
  const loaded = regsData.value, data = loaded?.region === rules.id ? loaded.data : null;
  const target = species.value ?? PROFILE_TABLE[profile.value].defaultTarget, at = dockState(now, zone()).at;
  const date = dateTimeFormat('en-CA', zone(), {year: 'numeric', month: '2-digit', day: '2-digit'}).format(new Date(at));
  const lang = language.value, state = regulationState(data, target, rules, now.getTime(), date, at);
  return {state, summary: ruleSummary(data, target, state, rules, lang), freshness: freshnessLabel(data, target, state, rules, now.getTime(), lang), available: !!data};
}
export function TargetRules({now = new Date()}: {now?: Date}) {
  const rules = currentRegionInfo()?.rules;
  useEffect(() => { if (rules) void loadRegs(rules); }, [rules?.id]);
  const {state, summary: s, freshness} = targetRules(now);
  const name = targetLabel(profile.value, region.value, species.value), lang = language.value;
  return <div class="app-plan-rules" data-status={s.status}>
    <p><span class="app-mark-regs-badge" data-status={s.status}>{s.label}</span> {name}. <RuleReason reason={ruleReason(state, lang)} lang={lang} marked={false} /></p>
    {[...s.bag, ...s.size, ...(s.depth ? [s.depth] : [])].map((line, i) => <p key={i}>{line}</p>)}
    <p>{verifiedText(s, lang)}</p>
    <p class="app-plan-rules-fresh" data-state={freshness.state}>{freshness.text}</p>
    <a href={s.link} target="_blank" rel="noopener" aria-label={t('plan.rulesNewTab', lang, {link: s.linkLabel, name})}>{s.linkLabel}</a>
  </div>;
}

export function PlanView({now = new Date()}: {now?: Date} = {}) {
  const heading = useRef<HTMLHeadingElement>(null), id = species.value ?? PROFILE_TABLE[profile.value].defaultTarget;
  useEffect(() => { heading.current?.focus(); }, []);
  const loaded = regionPlans.value, plans = loaded?.region === region.value ? loaded.plans : null;
  const coverage = regionCoverage(region.value), state = plans ? targetState(id, profile.value, plans, coverage) : null;
  const lang = language.value, copy = planCopy(lang);
  const result = planView(plans, id, state, coverage.unavailable, loaded?.reviewedAt ?? null, lang);
  const name = targetLabel(profile.value, region.value, species.value);
  return <section class="app-plan" aria-labelledby="app-plan-title">
    <h2 id="app-plan-title" ref={heading} tabIndex={-1}>{name}</h2>
    {state ? <p class="ui-eyebrow">{TARGET_STATE_TEXT[state]}</p> : null}
    {result.kind === 'plan' ? <>
      {result.lifeStage ? <p>{result.lifeStage}</p> : null}
      {result.sections.map((s, i) => <div key={i}><h3>{s.title}</h3><p>{s.text}</p></div>)}
      {result.confirm.length ? <><h3>{t('plan.confirm', lang)}</h3><ul>{result.confirm.map((s, i) => <li key={i}>{s}</li>)}</ul></> : null}
      <h3>{t('plan.evidence', lang)}</h3><p>{result.evidence.basis}</p>
      {result.evidence.links.length ? <ul>{result.evidence.links.map((l, i) => <li key={i}><a href={l.href} target="_blank" rel="noopener" aria-label={t('plan.newTab', lang, {title: l.title})}>{l.title}</a></li>)}</ul> : null}
      {result.reviewedAt ? <p>{t('plan.reviewed', lang, {date: result.reviewedAt})}</p> : null}
    </> : result.kind === 'unknown' ? <>
      <p>{copy.unknown}</p>
      <p><Button size="sm" variant="quiet" icon="pin" disabled={!region.value} onClick={() => openTrip()} data-plan-open-trip="">{t('accountMenu.trip', lang)}</Button></p>
    </> : <p>{result.kind === 'loading' ? copy.loading : result.reason}</p>}
    <h3>{t('plan.rules', lang)}</h3><TargetRules now={now} />
    <p><a href="/sources">{t('plan.built', lang)}</a></p>
  </section>;
}
