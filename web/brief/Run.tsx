// The Boat brief's run line (roadmap P2): fishing time at the chosen place
// and when to turn back, from web/brief/run.ts. The place is the "Where to
// look" pick the user selected, else the top pick, named either way: picks
// have already passed the protected-area screen and the depth limit, so a
// withheld mark never gets a fishing time. Without a cruise speed the line
// asks for one and opens the Boat limits form at that field; without a window
// it names the input that is missing. The method sits in the basis popover.
import {useState} from 'preact/hooks';
import {Button} from '../ui/Button.tsx';
import {Popover} from '../ui/Popover.tsx';
import {LimitsDialog, LimitsForm} from '../app/LimitsPanel.tsx';
import {regionInfo} from '../app/App.tsx';
import {cruiseSpeed} from '../limits.ts';
import type {Ranking} from '../ranking.ts';
import {habitat, profile, selection} from '../state.ts';
import {durationText, planRun, ROUND_MIN, type RunPlace, type RunState} from './run.ts';
import {currentRanking} from './WhereToLook.tsx';
import type {Brief} from './types.ts';

/** The run's place: the selected pick, else the top pick; null without a distance. */
export function runPlace(r: Ranking, spot: string | null, hab: string | null): (RunPlace & {chosen: boolean}) | null {
  const chosen = r.picks.find(p => p.kind === 'spot' ? p.id === spot : p.id === hab);
  if (chosen) return chosen.nm === null ? null : {name: chosen.name, nm: chosen.nm, chosen: true};
  const top = r.picks[0];
  return top && top.nm !== null ? {name: top.name, nm: top.nm, chosen: false} : null;
}

/** "8 am", "8:25 am": the lower-exposure line's clock. */
const clock = (iso: string, tz: string) => new Intl.DateTimeFormat('en-US', {hour: 'numeric', minute: '2-digit', timeZone: tz}).format(new Date(iso)).replace(':00', '').toLowerCase();
const kt = (n: number) => Number(n.toFixed(1)).toString();

/** The basis: what the sum uses and what it leaves to the skipper. */
export const runBasis = (harbor: string) =>
  `Run time is the straight-line distance from ${harbor} at the cruise speed you set, rounded up to ${ROUND_MIN} minutes; the real route is longer. `
  + 'Sea state, the bar crossing and fuel are left out. In by is the end of the lower-exposure window, which already weighs your limits, alerts, daylight and the bar at departure and return. '
  + 'A planning sum for your own decision; it cannot clear the entrance or promise a return.';

/** The line's words for a run state; `tz` is the region's time zone. */
export function runText(state: RunState, tz: string): {lead: string; times?: string; run?: string} {
  switch (state.kind) {
    case 'no-speed': return {lead: 'Set your cruise speed to see run time and when to turn back.'};
    case 'no-place': return {lead: 'Run time shows once a place to look is listed.'};
    case 'no-window': return {lead: state.reason};
    case 'over': return {lead: `Turn-back time for the ${clock(state.window.start, tz)}–${clock(state.window.end, tz)} window has passed.`};
    case 'no-time': return {lead: `The run to ${state.place.name} and back fills the ${clock(state.window.start, tz)}–${clock(state.window.end, tz)} window at ${kt(state.speedKn)} kt.`,
      run: `${state.place.nm.toFixed(1)} nm straight line · at least ${durationText(state.runMin)} each way`};
    case 'ok': return {lead: `Up to ${durationText(state.fishMin)} fishing at ${state.place.name}.`,
      times: `Leave ${clock(state.depart, tz)} · there ${clock(state.arrive, tz)} · turn back ${clock(state.turnBack, tz)} · in by ${clock(state.back, tz)}`,
      run: `${state.place.nm.toFixed(1)} nm straight line · at least ${durationText(state.runMin)} each way at ${kt(state.speedKn)} kt`};
  }
}

/** Fishing time and the return for the Boat brief; nothing for the other profiles or before the brief loads. */
export function RunLine({brief, ranking, now}: {brief: Brief | null; ranking?: Ranking; now: Date}) {
  const [open, setOpen] = useState(false);
  if (!brief || profile.value !== 'boat' || brief.profile !== 'boat') return null;
  const r = ranking ?? currentRanking(now.getTime());
  const place = runPlace(r, selection.value, habitat.value);
  const state = planRun(brief, place, cruiseSpeed.value, now), tz = regionInfo.value?.timezone ?? 'America/Los_Angeles';
  const text = runText(state, tz), harbor = r.harbor ?? 'the harbor';
  return (
    <section class="app-run" aria-label="Fishing time and return" data-state={state.kind}>
      <p class="app-run-lead"><span class="ui-eyebrow">Fishing time</span> {text.lead}</p>
      {text.times ? <p class="app-run-times ui-mono">{text.times}</p> : null}
      {text.run ? (
        <p class="app-run-detail ui-mono">
          {text.run}{place && !place.chosen ? ' · top pick' : ''}{' '}
          <Popover summary="basis" align="start">{runBasis(harbor)}</Popover>
        </p>
      ) : null}
      {state.kind === 'no-speed' ? <>
        <Button variant="ghost" size="sm" icon="settings" aria-haspopup="dialog" onClick={() => setOpen(true)}>Set cruise speed</Button>
        <LimitsDialog open={open} onClose={() => setOpen(false)} title="Your limits · Boat">
          <LimitsForm profile="boat" focusCruise onDone={() => setOpen(false)} />
        </LimitsDialog>
      </> : null}
    </section>
  );
}
