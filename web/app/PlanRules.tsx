// SC2037-11: the planner says whether each target species is open on the plan's date, from the same reviewed
// rules the rules card and the plan view read (web/regs.ts). Display only: nothing here reaches the GPX, the
// offline notes, a saved trip or the alert plan, and it never blocks saving or exporting.
import {useEffect} from 'preact/hooks';
import {freshnessLabel, loadRegs, regsData, regulationState, ruleSummary, verifiedText, type RulesRegion} from '../regs.ts';
import {currentRegionInfo} from './region-info.ts';

export const CHECK_RULES = 'Check the official rules before this trip.';
export const NOT_LEGAL_ADVICE = 'Not legal advice; check the official page.';
/** A plan's species as the registry's ids: the combined reef plan is one line each for lingcod and rockfish. */
export const ruleSpecies = (species: string): string[] => species === 'reef' ? ['lingcod', 'rockfish'] : [species];

export interface PlanRuleLine {
  id: string; name: string;
  /** closed: said plainly; open: restricted, scheduled and the like keep the card's own label; check: anything not confirmed. */
  kind: 'open' | 'closed' | 'check';
  status: string; label: string; reason: string; limits: string[]; verified: string; fresh: string; link: string; linkLabel: string;
}

/** One species' reading for `date`. Stale, overdue, unknown and not-reviewed rules, a missing registry, and a season that needs a fishing location are `check`, never `open`. */
export function planRuleLine(data: unknown, species: string, date: string, region: RulesRegion, now: number): PlanRuleLine {
  const state = regulationState(data, species, region, now, date, null), s = ruleSummary(data, species, state, region), fresh = freshnessLabel(data, species, state, region, now);
  const confirmed = (fresh.state === 'checked-today' || fresh.state === 'checked-earlier') && !state.overdue;
  const kind = s.status === 'unknown' || !confirmed ? 'check' : s.status === 'closed' ? 'closed' : 'open';
  const name = state.profile?.name ?? species;
  return {id: species, name, kind, status: s.status, label: kind === 'check' && s.status !== 'unknown' ? 'Check rules' : s.label,
    reason: state.reason, limits: [...s.bag, ...s.size, ...(s.depth ? [s.depth] : [])], verified: verifiedText(s), fresh: fresh.text, link: s.link, linkLabel: s.linkLabel};
}

export function PlanRules({date, species, region, now = Date.now()}: {date: string; species: string; region: {id: string; timezone?: string}; now?: number}) {
  const info = currentRegionInfo()?.rules, rules: RulesRegion = info && info.id === region.id ? info : {id: region.id, timezone: region.timezone};
  useEffect(() => { void loadRegs(rules); }, [rules.id]);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) return null;
  const loaded = regsData.value, data = loaded?.region === rules.id ? loaded.data : null;
  return <section class="export-card plan-rules" aria-label="Rules on the plan's date">
    <h2>Rules on {date}</h2>
    {ruleSpecies(species).map(id => {
      const l = planRuleLine(data, id, date, rules, now);
      return <div key={id} class="plan-rule" data-kind={l.kind} data-status={l.kind === 'check' ? 'unknown' : l.status}>
        <p><span class="app-mark-regs-badge" data-status={l.kind === 'check' ? 'unknown' : l.status}>{l.label}</span> <strong>{l.name}</strong>. {l.kind === 'closed' ? `Closed on ${date}. ` : ''}{l.reason}</p>
        {l.kind === 'check' ? <p>{CHECK_RULES}</p> : <>
          {l.limits.map((line, i) => <p key={i}>{line}</p>)}
          <p>{l.verified}</p>
        </>}
        <p class="export-note">{l.fresh}</p>
        <a href={l.link} target="_blank" rel="noopener" aria-label={`${l.linkLabel} for ${l.name} (official page, opens in a new tab)`}>{l.linkLabel}</a>
      </div>;
    })}
    <p class="export-note">{NOT_LEGAL_ADVICE}</p>
  </section>;
}
