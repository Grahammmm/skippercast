// The Boat brief's run line (roadmap P2): fishing time at the chosen place
// and when to turn back, from web/brief/run.ts. The place is the "Where to
// look" pick the user selected, else the top pick, named either way: picks
// have already passed the protected-area screen and the depth limit, so a
// withheld mark never gets a fishing time. Without a cruise speed the line
// asks for one and opens the Boat limits form at that field; without a window
// it names the input that is missing. The method sits in the basis popover.
import {useEffect, useState} from 'preact/hooks';
import {Button} from '../ui/Button.tsx';
import {Popover} from '../ui/Popover.tsx';
import {LimitsDialog, LimitsForm} from '../app/LimitsPanel.tsx';
import {regionInfo} from '../app/region-info.ts';
import {cruiseSpeed, wantedHours} from '../limits.ts';
import type {Ranking} from '../ranking.ts';
import {habitat, profile, selection, species} from '../state.ts';
import {barNote, durationText, planRun, ROUND_MIN, type RunPlace, type RunState} from './run.ts';
import {currentRanking} from './WhereToLook.tsx';
import type {Brief} from './types.ts';
import {PROFILE_TABLE} from '../profile.ts';
import {loadRegs, regsData, regulationState, ruleSummary, openingAt} from '../regs.ts';
import {fishingHours, type FishingHours} from './fishing-hours.ts';
import {DEFAULT_ZONE} from '../zone.ts';

/**
 * The run's place: the selected pick, else the top pick; null without a distance. `unranked` says a
 * selection was made that is not among the picks, so the line says whose times it shows.
 */
export function runPlace(r: Ranking, spot: string | null, hab: string | null): (RunPlace & {chosen: boolean; unranked: boolean}) | null {
  const chosen = r.picks.find(p => p.kind === 'spot' ? p.id === spot : p.id === hab);
  if (chosen) return chosen.nm === null ? null : {name: chosen.name, nm: chosen.nm, chosen: true, unranked: false};
  const top = r.picks[0];
  return top && top.nm !== null ? {name: top.name, nm: top.nm, chosen: false, unranked: !!(spot || hab)} : null;
}

/** "8 am", "8:25 am": the lower-exposure line's clock. */
const clock = (iso: string, tz: string) => new Intl.DateTimeFormat('en-US', {hour: 'numeric', minute: '2-digit', timeZone: tz}).format(new Date(iso)).replace(':00', '').toLowerCase();
const kt = (n: number) => Number(n.toFixed(1)).toString();

/** The basis: what the sum uses and what it leaves to the skipper. */
export const runBasis = (harbor: string) =>
  `Run time is the straight-line distance from ${harbor} at the cruise speed you set, rounded up to ${ROUND_MIN} minutes; the real route is longer. `
  + 'Sea state, the bar crossing and fuel are left out. In by is the end of the lower-exposure window, which already weighs your limits, alerts, daylight and the bar at the window\'s start and end; leaving later than its start, the bar at your departure is yours to check. '
  + 'Counts from the legal opening when the target has one that day; the run is a straight line until a charted route is available. '
  + 'A planning sum for your own decision; it cannot clear the entrance or promise a return.';

/** The line's words for a run state; `tz` is the region's time zone. */
export function runText(state: RunState, tz: string, unranked = false): {lead: string; times?: string; run?: string; note?: string} {
  const top = unranked && (state.kind === 'ok' || state.kind === 'no-time') ? `Your selected place is outside the ranked list, so times are for the top pick. ` : '';
  const text = words(state, tz);
  const note = state.kind === 'ok' || state.kind === 'no-time' ? barNote(state.window) ?? undefined : undefined;
  return {...text, lead: top + text.lead, ...(note ? {note} : {})};
}

function words(state: RunState, tz: string): {lead: string; times?: string; run?: string} {
  switch (state.kind) {
    case 'no-speed': return {lead: 'Set your cruise speed to see run time and when to turn back.'};
    case 'no-place': return {lead: 'Run time shows once a place to look is listed.'};
    case 'no-window': return {lead: state.reason};
    case 'over': return {lead: `Turn-back time for the ${clock(state.window.start, tz)}–${clock(state.window.end, tz)} window has passed.`};
    case 'no-time': return {lead: `The run to ${state.place.name} and back fills the ${clock(state.window.start, tz)}–${clock(state.window.end, tz)} window at ${kt(state.speedKn)} kt.`,
      run: `${state.place.nm.toFixed(1)} nm straight line · at least ${durationText(state.runMin)} each way`};
    case 'ok': return {lead: `Up to ${durationText(state.fishMin)} fishing at ${state.place.name}.`,
      times: `Leave ${clock(state.depart, tz)} · there ${clock(state.arrive, tz)} · turn back ${clock(state.turnBack, tz)} · in by ${clock(state.back, tz)} · window ${clock(state.window.start, tz)}–${clock(state.window.end, tz)}`,
      run: `${state.place.nm.toFixed(1)} nm straight line · at least ${durationText(state.runMin)} each way at ${kt(state.speedKn)} kt`};
  }
}

export function fishingWords(result: FishingHours, tz: string, sunset: string | null, opensAt: number | null): string {
  const duration = durationText;
  if (result.kind === 'closed') return `${result.label} is closed that day: ${result.reason}`;
  if (result.kind === 'no-wanted') return '';
  const edge = 'endedBy' in result ? result.endedBy === 'opening' && opensAt !== null ? `the legal opening at ${clock(new Date(opensAt).toISOString(), tz)}`
    : result.endedBy === 'daylight' && sunset ? `the sunset at ${clock(sunset, tz)}` : 'the conditions window' : '';
  if (result.kind === 'none') return `${result.rulesUnconfirmed ? 'Rules not confirmed · ' : ''}No fishing time remains — ended by ${edge}.`;
  const wanted = `${duration(result.wantedMin)} wanted · `;
  if (result.kind === 'beyond-daylight') return `${wanted}the day has ${duration(result.daylightMin)} of daylight.`;
  const available = `${wanted}${duration(result.availableMin)} available`;
  if (result.kind === 'enough') return `${available} (${duration(result.spareMin)} to spare).`;
  return result.rulesUnconfirmed ? `Rules not confirmed · ${available}; check the official rules.` : `${available}, ${duration(result.shortMin)} short — ended by ${edge}.`;
}

/** Fishing time and the return for the Boat brief; nothing for the other profiles or before the brief loads. */
export function RunLine({brief, ranking, now}: {brief: Brief | null; ranking?: Ranking; now: Date}) {
  const [open, setOpen] = useState(false);
  const rules = regionInfo.value?.rules;
  useEffect(() => { if (rules) void loadRegs(rules); }, [rules?.id]);
  if (!brief || profile.value !== 'boat' || brief.profile !== 'boat') return null;
  const r = ranking ?? currentRanking(now.getTime());
  const place = runPlace(r, selection.value, habitat.value);
  const state = planRun(brief, place, cruiseSpeed.value, now), tz = regionInfo.value?.timezone ?? DEFAULT_ZONE;
  const text = runText(state, tz, place?.unranked), harbor = r.harbor ?? 'the harbor';
  const target = species.value ?? PROFILE_TABLE.boat.defaultTarget;
  const loaded = regsData.value, data = loaded?.region === rules?.id ? loaded?.data : null;
  const active = state.kind === 'ok' || state.kind === 'no-time';
  const date = active ? new Intl.DateTimeFormat('en-CA', {timeZone: tz, year: 'numeric', month: '2-digit', day: '2-digit'}).format(new Date(state.window.start)) : '';
  const opensAt = rules ? openingAt(data, target, rules, date) : null;
  // Read at the opening (not before it) so a timed opener clips rather than closing the whole day.
  const rule = rules ? regulationState(data, target, rules, now.getTime(), date, opensAt) : {status: 'unknown', label: 'Check rules', reason: 'Rules unavailable.', today: date, issues: []};
  const summary = rules ? ruleSummary(data, target, rule, rules) : null;
  const result = active ? fishingHours(state, {wantedMin: wantedHours.value === null ? null : wantedHours.value * 60, sunrise: brief.sunrise, sunset: brief.sunset, rule: {...rule, opensAt, label: target === 'reef' ? 'Lingcod & rockfish' : rule.profile?.name ?? target}}) : null;
  const verdict = result ? fishingWords(result, tz, brief.sunset, opensAt) : '';
  if (state.kind === 'ok' && result && result.kind !== 'no-wanted') text.lead = `Run to ${state.place.name}.`;
  // Places listed with no distance: the region gives no harbor position to measure from.
  if (state.kind === 'no-place' && r.picks.length) text.lead = 'No harbor position to measure from, so no run time.';
  return (
    <section class="app-run" aria-label="Fishing time and return" data-state={state.kind}>
      <p class="app-run-lead"><span class="ui-eyebrow">Fishing time</span> {text.lead}</p>
      {text.times ? <p class="app-run-times ui-mono">{text.times}{brief.sunrise && brief.sunset ? ` · Daylight ${clock(brief.sunrise, tz)}–${clock(brief.sunset, tz)}` : ''}</p> : null}
      {verdict ? <p class="app-run-hours" data-kind={result!.kind}>{text.note ? `${text.note} — check the bar. ` : ''}{verdict}{' '}
        {['scheduled', 'restricted'].includes(rule.status) ? `${summary?.label ?? rule.label}: ${rule.reason} ` : ''}
        {summary ? <a href={summary.link}>{summary.linkLabel}</a> : null}</p> : null}
      {text.note ? <p class="app-run-note">{text.note}.</p> : null}
      {text.run ? (
        <p class="app-run-detail ui-mono">
          {text.run}{place && !place.chosen ? ' · top pick' : ''}{' '}
          <Popover summary="basis" align="start">{runBasis(harbor)}</Popover>
        </p>
      ) : null}
      {state.kind === 'no-speed' || result?.kind === 'no-wanted' ? <>
        <Button variant="ghost" size="sm" icon="settings" aria-haspopup="dialog" onClick={() => setOpen(true)}>{state.kind === 'no-speed' ? 'Set cruise speed' : 'Set hours I want'}</Button>
        <LimitsDialog open={open} onClose={() => setOpen(false)} title="Your limits · Boat">
          <LimitsForm profile="boat" focusCruise={state.kind === 'no-speed'} focusWanted={result?.kind === 'no-wanted'} onDone={() => setOpen(false)} />
        </LimitsDialog>
      </> : null}
    </section>
  );
}
