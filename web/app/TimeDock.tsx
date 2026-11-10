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
import {Dock, type DockLabels} from '../ui/Dock.tsx';
import {dockTime, horizonDays, localParts, nearestHour, nextHour, play, type DockTime} from '../hour.ts';
import {day, hour} from '../state.ts';
import {commitDockHour, previewDockState, requestDockDay, requestDockHour, useDockSelection} from '../dock-selection.ts';
import {zone} from './App.tsx';
import {language, localeOf, t, type Language} from '../i18n.ts';
import {useDayVerdicts, withVerdicts} from './day-verdicts.ts';

export {localParts};
export const REDUCED_MOTION = '(prefers-reduced-motion: reduce)';

/**
 * "2 pm" for an hour of the day; Spanish reads the 24-hour clock ("14"). Display only: nothing
 * here feeds the dock's parsing or selection, which stay on web/hour.ts's en-US parts.
 */
export const hourText = (h: number, lang: Language = 'en'): string =>
  lang === 'en' ? `${h % 12 || 12} ${h < 12 ? 'am' : 'pm'}`
    : new Intl.DateTimeFormat(localeOf(lang), {hour: 'numeric', hourCycle: 'h23', timeZone: 'UTC'}).format(Date.UTC(2000, 0, 1, h));
/** The zone's short name ("PDT") at `date`. */
export const zoneName = (date: Date, tz: string): string =>
  new Intl.DateTimeFormat('en-US', {timeZone: tz, timeZoneName: 'short'}).formatToParts(date).find(p => p.type === 'timeZoneName')?.value ?? tz;

/**
 * Day chips: Today, then weekdays; the eighth day repeats today's weekday, so it carries its
 * date ("Mon 12"). A selected day outside the horizon is kept as a chip.
 */
export function dayOptions(now: Date, tz: string, selected: string | null, lang: Language = 'en'): {value: string; label: string}[] {
  // The weekday text is display only: English keeps hour.ts's own, other languages format the day's first real hour in the region zone.
  const weekday = (d: {weekday: string; hours: readonly number[]}): string =>
    lang === 'en' ? d.weekday : new Intl.DateTimeFormat(localeOf(lang), {timeZone: tz, weekday: 'short'}).format(d.hours[0]!);
  const options = horizonDays(now, tz).map((d, i) => ({value: d.day, label: i === 0 ? t('dock.today', lang) : i >= 7 ? `${weekday(d)} ${Number(d.day.slice(8))}` : weekday(d)}));
  if (selected && !options.some(o => o.value === selected)) options.push({value: selected, label: selected.slice(5)});
  return options;
}

/** The dock's time for the signals: today and the current hour when the URL names neither. */
export const dockState = (now: Date, tz: string): DockTime => dockTime(day.value, hour.value, now, tz);

/** "2 pm" for the selected hour; outside the horizon the slider is off and this says why. */
export function readout(state: DockTime, tz: string, lang: Language = 'en'): string {
  const text = hourText(localParts(new Date(state.at), tz).hour, lang);
  return state.index < 0 ? `${text}${t('dock.outside', lang)}` : text;
}

/** Day and hour for the controls, using the same explicit preview context as the thumb. */
export function dockValueText(now: Date, tz: string, state: DockTime, lang: Language = 'en', at = state.at): string {
  const parts = localParts(new Date(at), tz);
  const label = parts.day === state.today ? t('dock.today', lang)
    : parts.day === horizonDays(now, tz)[1]?.day ? t('dock.tomorrow', lang)
    : dayOptions(now, tz, parts.day, lang).find(d => d.value === parts.day)!.label;
  const text = `${label} · ${hourText(parts.hour, lang)}`;
  return state.index < 0 ? `${text}${t('dock.outside', lang)}` : text;
}

/**
 * Write hour `at` (epoch ms) at once: ?hour= ISO UTC, ?day= its local day unless that is today. The dock's own
 * inputs go through web/dock-selection.ts instead, which shows the hour at once and settles it after a pause.
 */
export const selectHour = (now: Date, tz: string, at: number): void => commitDockHour(now, tz, at);

/** A day chip at once: the same local hour on day `d`, or the nearest hour that day has in the horizon. */
export function selectDay(now: Date, tz: string, d: string, state: DockTime): void {
  const hours = horizonDays(now, tz).find(x => x.day === d)?.hours ?? [];
  const at = nearestHour(hours, localParts(new Date(state.at), tz).hour, tz);
  if (at !== null) selectHour(now, tz, at);
}

/** The dock's own words in `lang`. */
export const dockLabels = (lang: Language): DockLabels => ({time: t('shell.time', lang), day: t('shell.day', lang), hour: t('shell.hour', lang), play: t('dock.play', lang), pause: t('dock.pause', lang), nextHour: t('dock.nextHour', lang)});

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
  const tz = zone(), lang = language.value;
  // SC1407-05: the controls show the pending preview at once; the evidence follows the settled hour.
  useDockSelection(now, tz);
  const state = previewDockState(now, tz), answers = useDayVerdicts(now, tz);
  const reduced = useReducedMotion();
  const [playing, setPlaying] = useState(false);
  useEffect(() => {
    if (!playing) return;
    const step = (): boolean => {
      const clock = new Date(), next = nextHour(previewDockState(clock, tz).at, clock);
      if (next === null) return false;
      requestDockHour(clock, tz, next);
      return true;
    };
    return play({step, onStop: () => setPlaying(false), motion: media()});
  }, [playing, tz]);
  // The day strip scrolls sideways on narrow stages: keep the chosen chip in view.
  const dock = useRef<HTMLDivElement>(null);
  useEffect(() => { dock.current?.querySelector<HTMLElement>('.ui-segmented [aria-pressed="true"]')?.scrollIntoView?.({block: 'nearest', inline: 'nearest'}); }, [state.day, lang]);
  const at = (i: number): number => state.hours[i] ?? state.at;
  return (
    <div class="app-dock" ref={dock}>
      <Dock days={withVerdicts(dayOptions(now, tz, state.day, lang), answers, lang)} labels={dockLabels(lang)} day={state.day} onDay={d => requestDockDay(now, tz, d, state)} playing={playing} onPlay={setPlaying}
        stepOnly={reduced} advanceDisabled={nextHour(state.at, now) === null} hour={Math.max(0, state.index)} hours={state.index < 0 ? 1 : state.hours.length} disabled={state.index < 0}
        onHour={i => requestDockHour(now, tz, at(i))} hourText={i => dockValueText(now, tz, state, lang, at(i))} />
      <span class="app-dock-zone ui-mono">{zoneName(new Date(state.at), tz)}</span>
    </div>
  );
}
