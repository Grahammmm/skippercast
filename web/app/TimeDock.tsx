// Time dock (FE-05, design § 6): the Dock primitive bound to the day and hour
// signals. Day chips are today and the next two days in the region's zone;
// the slider is the hour of that day; ?hour= stays ISO UTC and ?day= local.
// Play steps an hour a second and stops at the day's end; under
// prefers-reduced-motion it steps one hour per press. FE-12 replaces the
// fixed horizon with the forecast's frames and their age gates.
import {useEffect, useState} from 'preact/hooks';
import {Dock} from '../ui/Dock.tsx';
import {day, hour, hourParam, parseHour, setParams} from '../state.ts';
import {zone} from './App.tsx';

export const DAY_COUNT = 3;
const pad = (n: number): string => String(n).padStart(2, '0');

/** The local calendar day and hour of `date` in `tz`. */
export function localParts(date: Date, tz: string): {day: string; hour: number; weekday: string} {
  const f = new Intl.DateTimeFormat('en-US', {timeZone: tz, hourCycle: 'h23', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', weekday: 'short'});
  const p = Object.fromEntries(f.formatToParts(date).map(part => [part.type, part.value]));
  return {day: `${p.year}-${p.month}-${p.day}`, hour: Number(p.hour) % 24, weekday: p.weekday ?? ''};
}

/**
 * The ?hour= value for local `hourOfDay` on calendar `dayValue` in `tz`. The
 * offset is read once at the guessed instant, so on a DST change day the hours
 * around the switch can land one hour off; FE-12 replaces this with the
 * forecast's own frame times and drops the conversion.
 */
export function utcHour(dayValue: string, hourOfDay: number, tz: string): string | null {
  const guess = Date.parse(`${dayValue}T${pad(hourOfDay)}:00:00Z`);
  if (!Number.isFinite(guess)) return null;
  const local = localParts(new Date(guess), tz);
  const offset = Date.parse(`${local.day}T${pad(local.hour)}:00:00Z`) - guess;
  return hourParam((guess - offset) / 1000);
}

/** "2 pm" for an hour of the day. */
export const hourText = (h: number): string => `${h % 12 || 12} ${h < 12 ? 'am' : 'pm'}`;
/** The zone's short name ("PDT") at `date`. */
export const zoneName = (date: Date, tz: string): string =>
  new Intl.DateTimeFormat('en-US', {timeZone: tz, timeZoneName: 'short'}).formatToParts(date).find(p => p.type === 'timeZoneName')?.value ?? tz;

/** Day chips from `now`: today, then the next days by weekday; a selected day outside the horizon is kept as a chip. */
export function dayOptions(now: Date, tz: string, selected: string | null): {value: string; label: string}[] {
  const options = Array.from({length: DAY_COUNT}, (_, i) => {
    const p = localParts(new Date(now.getTime() + i * 86_400_000), tz);
    return {value: p.day, label: i === 0 ? 'Today' : p.weekday};
  });
  if (selected && !options.some(o => o.value === selected)) options.push({value: selected, label: selected.slice(5)});
  return options;
}

/** The dock's day and hour index for the signals: today and the current hour when the URL names none. */
export function dockState(now: Date, tz: string): {day: string; today: string; hour: number} {
  const current = localParts(now, tz);
  const at = parseHour(hour.value);
  return {day: day.value ?? current.day, today: current.day, hour: at === null ? current.hour : localParts(new Date(at * 1000), tz).hour};
}

export function TimeDock({now = new Date()}: {now?: Date} = {}) {
  const tz = zone();
  const state = dockState(now, tz);
  const [playing, setPlaying] = useState(false);
  const select = (d: string, h: number) => setParams({day: d === state.today ? null : d, hour: utcHour(d, h, tz)});
  useEffect(() => {
    if (!playing) return;
    const still = typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches;
    const step = () => {
      const next = dockState(new Date(), tz);
      if (next.hour >= 23) { setPlaying(false); return; }
      select(next.day, next.hour + 1);
    };
    if (still) { step(); setPlaying(false); return; }
    const timer = setInterval(step, 1000);
    return () => clearInterval(timer);
  }, [playing, tz]);
  return (
    <div class="app-dock">
      <Dock days={dayOptions(now, tz, day.value)} day={state.day} onDay={d => select(d, state.hour)} playing={playing} onPlay={setPlaying}
        hour={state.hour} hours={24} onHour={h => select(state.day, h)} hourText={hourText} />
      <span class="app-dock-zone ui-mono">{zoneName(now, tz)}</span>
    </div>
  );
}
