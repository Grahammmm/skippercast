// SC2252-06: each day chip says its day's verdict, so the week reads without tapping through.
// The word is the brief's own: currentBrief and currentVerdict at the hour the dock picks on that
// day (web/hour.ts dockTime), from the feeds already loaded, so a day beyond the forecast, under a
// marine alert or with its alert check missing reads exactly as the brief reads it once chosen.
// Each consumer keeps one memoized projection for its clock and zone; it never reads the selected
// day or hour, so scrubbing, playing or choosing a day reuses it, while the profile, boat, limits,
// region, feeds, tide choice and language invalidate it through the signals the brief reads.
import {computed, type ReadonlySignal} from '@preact/signals';
import {useMemo} from 'preact/hooks';
import {currentBrief, currentVerdict} from '../brief/Brief.tsx';
import type {DayVerdict} from '../brief/verdict.ts';
import {dockTime, horizonDays} from '../hour.ts';
import {hourParam} from '../state.ts';
import {language, t, type Language, type StringId} from '../i18n.ts';

/** One day's answer: the explicit hour it was read at and the engine's capped verdict with its held and limit sentences. */
export interface DayAnswer {
  readonly at: string | null;
  readonly verdict: DayVerdict;
  readonly held: string | null;
  readonly limit: string | null;
}

const UNKNOWN = (at: string | null): DayAnswer => ({at, verdict: 'unknown', held: null, limit: null});

/** Every horizon day's answer keyed by local day, at `now` in `tz`. `onEvaluate` (tests) is told of each day computed. */
export function dayVerdicts(now: Date, tz: string, {onEvaluate}: {onEvaluate?: (day: string) => void} = {}): ReadonlySignal<ReadonlyMap<string, DayAnswer>> {
  return computed(() => {
    const days = horizonDays(now, tz), lang = language.value, out = new Map<string, DayAnswer>();
    for (const d of days) {
      const at = hourParam(dockTime(d.day, null, now, tz, days).at / 1000);
      onEvaluate?.(d.day);
      try {
        const v = currentVerdict(currentBrief(now, at), now, lang);
        out.set(d.day, v ? {at, verdict: v.verdict, held: v.held, limit: v.limit} : UNKNOWN(at));
      } catch { out.set(d.day, UNKNOWN(at)); }
    }
    return out;
  });
}

/** The mounted consumer's answers: one projection per clock value and zone, re-read only when its sources change. */
export function useDayVerdicts(now: Date, tz: string): ReadonlyMap<string, DayAnswer> {
  const ms = now.getTime();
  return useMemo(() => dayVerdicts(new Date(ms), tz), [ms, tz]).value;
}

/** Day options with their verdict word after the day ("Sat · Rough"); a day without an answer (outside the horizon) says Unknown. Values are unchanged. */
export const withVerdicts = (options: readonly {value: string; label: string}[], answers: ReadonlyMap<string, DayAnswer>, lang: Language): {value: string; label: string}[] =>
  options.map(o => ({value: o.value, label: `${o.label} · ${t(`brief.verdict.${answers.get(o.value)?.verdict ?? 'unknown'}` as StringId, lang)}`}));
