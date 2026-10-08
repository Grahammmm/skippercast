// Time dock (FE-05, FE-12, design § 6): the Dock primitive bound to the day and
// hour signals over the 169-hour horizon of web/hour.ts. Day chips are the
// horizon's local days in the region's zone; the slider runs over the chosen
// day's horizon hours (today from the current hour), so ?hour= stays an exact
// UTC instant and no local-to-UTC offset is guessed. Play steps an hour a
// second across days, stops at the horizon's end and pauses when the page is
// hidden; under prefers-reduced-motion it never auto-plays and the button
// steps one hour per press. A ?hour= outside the horizon is kept, never reset
// (v1's coastal-clock.js rule): the slider is off and the readout says so.
import {useEffect, useRef, useState} from 'preact/hooks';
import {Dock} from '../ui/Dock.tsx';
import {dockTime, horizonDays, localParts, nearestHour, nextHour, play, type DockTime} from '../hour.ts';
import {day, hour, hourParam, setParams} from '../state.ts';
import {zone} from './App.tsx';

export {localParts};
export const REDUCED_MOTION = '(prefers-reduced-motion: reduce)';

/** "2 pm" for an hour of the day. */
export const hourText = (h: number): string => `${h % 12 || 12} ${h < 12 ? 'am' : 'pm'}`;
/** The zone's short name ("PDT") at `date`. */
export const zoneName = (date: Date, tz: string): string =>
  new Intl.DateTimeFormat('en-US', {timeZone: tz, timeZoneName: 'short'}).formatToParts(date).find(p => p.type === 'timeZoneName')?.value ?? tz;

/**
 * Day chips: Today, then weekdays; the eighth day repeats today's weekday, so it carries its
 * date ("Mon 12"). A selected day outside the horizon is kept as a chip.
 */
export function dayOptions(now: Date, tz: string, selected: string | null): {value: string; label: string}[] {
  const options = horizonDays(now, tz).map((d, i) => ({value: d.day, label: i === 0 ? 'Today' : i >= 7 ? `${d.weekday} ${Number(d.day.slice(8))}` : d.weekday}));
  if (selected && !options.some(o => o.value === selected)) options.push({value: selected, label: selected.slice(5)});
  return options;
}

/** The dock's time for the signals: today and the current hour when the URL names neither. */
export const dockState = (now: Date, tz: string): DockTime => dockTime(day.value, hour.value, now, tz);

/** "2 pm" for the selected hour; outside the horizon the slider is off and this says why. */
export function readout(state: DockTime, tz: string): string {
  const text = hourText(localParts(new Date(state.at), tz).hour);
  return state.index < 0 ? `${text} · outside the forecast` : text;
}

/** Write hour `at` (epoch ms): ?hour= ISO UTC, ?day= its local day unless that is today. */
export function selectHour(now: Date, tz: string, at: number): void {
  const d = localParts(new Date(at), tz).day;
  setParams({day: d === localParts(now, tz).day ? null : d, hour: hourParam(at / 1000)});
}

/** A day chip: the same local hour on day `d`, or the nearest hour that day has in the horizon. */
export function selectDay(now: Date, tz: string, d: string, state: DockTime): void {
  const hours = horizonDays(now, tz).find(x => x.day === d)?.hours ?? [];
  const at = nearestHour(hours, localParts(new Date(state.at), tz).hour, tz);
  if (at !== null) selectHour(now, tz, at);
}

const media = (): MediaQueryList | null => typeof matchMedia === 'function' ? matchMedia(REDUCED_MOTION) : null;

/** Whether prefers-reduced-motion asks for no motion, followed while mounted. */
function useReducedMotion(): boolean {
  const [reduced, setReduced] = useState(() => media()?.matches ?? false);
  useEffect(() => {
    const query = media();
    if (!query) return;
    const change = () => setReduced(query.matches);
    query.addEventListener('change', change);
    return () => query.removeEventListener('change', change);
  }, []);
  return reduced;
}

export function TimeDock({now = new Date()}: {now?: Date} = {}) {
  const tz = zone();
  const state = dockState(now, tz);
  const reduced = useReducedMotion();
  const [playing, setPlaying] = useState(false);
  useEffect(() => {
    if (!playing) return;
    const step = (): boolean => {
      const clock = new Date(), next = nextHour(dockState(clock, tz).at, clock);
      if (next === null) return false;
      selectHour(clock, tz, next);
      return true;
    };
    return play({step, onStop: () => setPlaying(false), motion: media()});
  }, [playing, tz]);
  // The day strip scrolls sideways on narrow stages: keep the chosen chip in view.
  const dock = useRef<HTMLDivElement>(null);
  useEffect(() => { dock.current?.querySelector<HTMLElement>('[aria-label="Day"] [aria-pressed="true"]')?.scrollIntoView?.({block: 'nearest', inline: 'nearest'}); }, [state.day]);
  const at = (i: number): number => state.hours[i] ?? state.at;
  return (
    <div class="app-dock" ref={dock}>
      <Dock days={dayOptions(now, tz, state.day)} day={state.day} onDay={d => selectDay(now, tz, d, state)} playing={playing} onPlay={setPlaying}
        stepOnly={reduced} hour={Math.max(0, state.index)} hours={state.index < 0 ? 1 : state.hours.length} disabled={state.index < 0}
        onHour={i => selectHour(now, tz, at(i))} hourText={i => state.index < 0 ? readout(state, tz) : hourText(localParts(new Date(at(i)), tz).hour)} />
      <span class="app-dock-zone ui-mono">{zoneName(now, tz)}</span>
    </div>
  );
}
