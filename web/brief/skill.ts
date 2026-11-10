// SCFEAT-SKILL-1: measured forecast skill beside the brief's model-disagreement line. Reads only the published
// scorecard (dist/data/forecast-skill.json, written by scripts/publish_forecast_skill.py and shown in full at
// /skill): how often the forecast at the shown hour's lead (24, 48 or 72 h ahead, SC1407-11) was within the stated
// tolerance of what the buoy then read. A figure is shown only with its lead, window, sample and buoy; too little
// history at that lead, an unreadable, future-dated or old scorecard is UNKNOWN with no percentage, and a past hour or 72 h or
// more ahead has no published score. Never a navigation or go/no-go statement.
import {signal} from '@preact/signals';
import {t, type Language} from '../i18n.ts';

const VARIABLES = [['wind_speed_10m', 'wind'], ['wave_height', 'seas']] as const;
const WINDOWS = [30, 7] as const, MAX_AGE = 14 * 86_400_000, FUTURE = 10 * 60_000;
const whole = (v: unknown): v is number => Number.isInteger(v) && (v as number) >= 0;

export type SkillLead = 24 | 48 | 72;
export interface SkillPart {readonly variable: 'wind' | 'seas'; readonly pct: number; readonly within: number; readonly n: number; readonly station: string; readonly window: number}
export type SkillSummary = {readonly state: 'known'; readonly lead: SkillLead; readonly parts: SkillPart[]; readonly published: string}
  | {readonly state: 'unknown'; readonly lead: SkillLead; readonly published: string | null}
  | {readonly state: 'unavailable'; readonly reason: 'range' | 'invalid'};

/**
 * SC1407-11: the published lead bucket for the hour `at` seen at `now` (epoch ms), by elapsed time and exactly the
 * publisher's half-open buckets (scripts/publish_forecast_skill.py from pipeline/verification.py lead_bucket):
 * under 24 h → 24, 24 h to under 48 h → 48, 48 h to under 72 h → 72; 72 h or more has no published score (null).
 * 0 ≤ elapsed < 24 h is 24; a past or non-finite instant has no published lead (null), never a 24 h fallback.
 */
export function skillLead(at: number, now: number): SkillLead | null {
  const d = at - now;
  return d >= 0 && d < 259_200_000 ? ((d / 86_400_000 | 0) + 1) * 24 as SkillLead : null;
}

/** Whole percent that never rounds a miss up to 100% or a hit down to 0% (as dist/skill-page.js). */
const percent = (within: number, n: number) => within === n ? 100 : within === 0 ? 0 : Math.min(99, Math.max(1, Math.round(100 * within / n)));

/** The skill for the forecast of the hour `at` (default now), from that lead's rows only; freshness is judged at `now`. */
export function skillSummary(file: unknown, region: string, now: number, at: number = now): SkillSummary {
  const LEAD = skillLead(at, now);
  if (LEAD === null) return {state: 'unavailable', reason: Number.isFinite(at) && at - now >= 259_200_000 ? 'range' : 'invalid'};
  const f = file as {schema_version?: unknown; generated_at?: unknown; minimum?: {valid_times?: unknown}; scores?: unknown} | null;
  const generated = typeof f?.generated_at === 'string' && /(Z|[+-]\d\d:?\d\d)$/.test(f.generated_at) ? Date.parse(f.generated_at) : NaN;
  const minimum = f?.minimum?.valid_times;
  if (!f || f.schema_version !== 1 || !Array.isArray(f.scores) || !whole(minimum) || minimum < 1 || !Number.isFinite(generated)
    || generated - now > FUTURE || now - generated > MAX_AGE) return {state: 'unknown', lead: LEAD, published: null};
  const published = new Date(generated).toISOString().slice(0, 10);
  type Row = {port?: unknown; station?: unknown; variable?: unknown; lead_hours?: unknown; window_days?: unknown; n?: unknown; within?: unknown; enough?: unknown};
  const rows = (f.scores as Row[]).filter(r => r && r.port === region && r.lead_hours === LEAD && r.enough === true && typeof r.station === 'string'
    && whole(r.n) && whole(r.within) && r.within <= r.n && r.n >= minimum);
  for (const window of WINDOWS) {
    const parts: SkillPart[] = [];
    for (const [key, variable] of VARIABLES) {
      const best = rows.filter(r => r.variable === key && r.window_days === window).sort((a, b) => (b.n as number) - (a.n as number))[0];
      if (best) parts.push({variable, pct: percent(best.within as number, best.n as number), within: best.within as number, n: best.n as number, station: best.station as string, window});
    }
    if (parts.length) return {state: 'known', lead: LEAD, parts, published};
  }
  return {state: 'unknown', lead: LEAD, published};
}

export function skillLine(s: SkillSummary, lang: Language | string = 'en'): string {
  const body = s.state === 'known' ? t('brief.skill.known', lang, {lead: s.lead, window: s.parts[0]!.window, date: s.published,
      parts: s.parts.map(p => t('brief.skill.part', lang, {name: t(`brief.skill.${p.variable}`, lang), pct: p.pct, within: p.within, n: p.n, station: p.station})).join('; ')})
    : s.state === 'unknown' && s.published ? t('brief.skill.unknown', lang, {lead: s.lead, date: s.published}) : s.state === 'unknown' ? t('brief.skill.unreadable', lang, {lead: s.lead}) : t(s.reason === 'range' ? 'brief.skill.unavailable.range' : 'brief.skill.unavailable.invalid', lang);
  return `${body} ${t('brief.skill.nav', lang)}`;
}

/** The parsed scorecard once fetched: undefined while loading, null when it could not be read. */
export const skillFile = signal<unknown>(undefined);
let started = false;
export function loadSkill(): void {
  if (started || typeof fetch === 'undefined') return;
  started = true;
  void fetch('/data/forecast-skill.json', {cache: 'no-store'}).then(r => r.ok ? r.json() : null).catch(() => null).then(j => { skillFile.value = j; });
}
