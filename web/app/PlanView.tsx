import {useEffect, useRef} from 'preact/hooks';
import {planView, PLAN_COPY} from '../plan.ts';
import {PROFILE_TABLE} from '../profile.ts';
import {regionCoverage, regionPlans, targetLabel, targetState, TARGET_STATE_TEXT} from '../species.ts';
import {profile, region, setParams, species, withParams} from '../state.ts';
import {loadRegs, regsData, regulationState, ruleSummary, verifiedText} from '../regs.ts';
import {currentRegionInfo, zone} from './App.tsx';
import {dockState} from './TimeDock.tsx';
import './plan.css';

export function PlanLink() {
  const href = withParams(typeof location === 'undefined' ? 'https://skippercast.test/map' : location.href, {view: 'plan'});
  return <a href={href} onClick={e => { if (!e.button && !e.metaKey && !e.ctrlKey && !e.shiftKey && !e.altKey) { e.preventDefault(); setParams({view: 'plan'}); } }}>Plan for {targetLabel(profile.value, region.value, species.value)}</a>;
}

/** The selected target's existing registry logic, evaluated for the dock's date and instant. */
export function targetRules(now: Date) {
  const rules = currentRegionInfo()?.rules ?? {id: region.value ?? '', timezone: zone()};
  const loaded = regsData.value, data = loaded?.region === rules.id ? loaded.data : null;
  const target = species.value ?? PROFILE_TABLE[profile.value].defaultTarget, at = dockState(now, zone()).at;
  const date = new Intl.DateTimeFormat('en-CA', {timeZone: zone(), year: 'numeric', month: '2-digit', day: '2-digit'}).format(new Date(at));
  const state = regulationState(data, target, rules, now.getTime(), date, at);
  return {state, summary: ruleSummary(data, target, state, rules), available: !!data};
}
export function TargetRules({now = new Date()}: {now?: Date}) {
  const rules = currentRegionInfo()?.rules;
  useEffect(() => { if (rules) void loadRegs(rules); }, [rules?.id]);
  const {state, summary: s} = targetRules(now);
  const name = targetLabel(profile.value, region.value, species.value);
  return <div class="app-plan-rules" data-status={s.status}>
    <p><span class="app-mark-regs-badge" data-status={s.status}>{s.label}</span> {name}. {state.reason}</p>
    {[...s.bag, ...s.size, ...(s.depth ? [s.depth] : [])].map((line, i) => <p key={i}>{line}</p>)}
    <p>{verifiedText(s)}</p>
    <a href={s.link} target="_blank" rel="noopener" aria-label={`${s.linkLabel} for ${name} (opens in a new tab)`}>{s.linkLabel}</a>
  </div>;
}

export function PlanView({now = new Date()}: {now?: Date} = {}) {
  const heading = useRef<HTMLHeadingElement>(null), id = species.value ?? PROFILE_TABLE[profile.value].defaultTarget;
  useEffect(() => { heading.current?.focus(); }, []);
  const loaded = regionPlans.value, plans = loaded?.region === region.value ? loaded.plans : null;
  const coverage = regionCoverage(region.value), state = plans ? targetState(id, profile.value, plans, coverage) : null;
  const result = planView(plans, id, state, coverage.unavailable, loaded?.reviewedAt ?? null);
  const name = targetLabel(profile.value, region.value, species.value);
  return <section class="app-plan" aria-labelledby="app-plan-title">
    <h2 id="app-plan-title" ref={heading} tabIndex={-1}>{name}</h2>
    {state ? <p class="ui-eyebrow">{TARGET_STATE_TEXT[state]}</p> : null}
    {result.kind === 'plan' ? <>
      {result.lifeStage ? <p>{result.lifeStage}</p> : null}
      {result.sections.map((s, i) => <div key={i}><h3>{s.title}</h3><p>{s.text}</p></div>)}
      {result.confirm.length ? <><h3>Confirm on the day</h3><ul>{result.confirm.map((s, i) => <li key={i}>{s}</li>)}</ul></> : null}
      <h3>Evidence</h3><p>{result.evidence.basis}</p>
      {result.evidence.links.length ? <ul>{result.evidence.links.map((l, i) => <li key={i}><a href={l.href} target="_blank" rel="noopener" aria-label={`${l.title} (opens in a new tab)`}>{l.title}</a></li>)}</ul> : null}
      {result.reviewedAt ? <p>Plan reviewed {result.reviewedAt}</p> : null}
    </> : <p>{result.kind === 'loading' ? PLAN_COPY.loading : result.kind === 'unknown' ? <>{PLAN_COPY.unknown} {result.id}</> : result.reason}</p>}
    <h3>Rules</h3><TargetRules now={now} />
    <p><a href="/sources">How it's built</a></p>
  </section>;
}
