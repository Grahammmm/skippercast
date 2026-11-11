// SC1407-14: the optional float plan in the trip dialog (boat, people aboard, departure, be back by, if overdue). Pure helpers only:
// the values live in the open dialog (web/planner.ts holds them in memory), never in the draft, the account, GPX, a share link, an
// alert snapshot or telemetry. They reach exactly one place: the English offline-notes file the person downloads (dist/trip-export.js).
// Erasable syntax only: Node tests import this file by type stripping.
import {entranceWindow} from '../packages/coast/src/entrance-window.ts';
import type {BarHour, Entrance} from '../packages/coast/src/bar-conditions.ts';

export type FloatPlanFields = {boat: string; people: string; departure: string; backBy: string; overdue: string};
export const BOAT_MAX = 160, OVERDUE_MAX = 1000, PEOPLE_MAX = 999;
export const emptyFloatPlan = (): FloatPlanFields => ({boat: '', people: '', departure: '', backBy: '', overdue: ''});

/** A time on the plan's date, pinned to the region zone. */
export type FloatTime = {date: string; time: string; zone: string; offset: string};
/** What the notes file receives: only supplied fields, already checked. */
export type FloatPlanRecord = {boat?: string; people?: number; departure?: FloatTime; backBy?: FloatTime; overdue?: string};
export type FloatField = keyof FloatPlanFields;
/** Reason codes only (the view translates them); never any of the typed text. */
export type FloatReason = 'boat-long' | 'overdue-long' | 'people' | 'time' | 'gap' | 'ambiguous' | 'order' | 'date' | 'zone';
export type FloatCheck = {ok: true; record: FloatPlanRecord | null} | {ok: false; errors: Partial<Record<FloatField, FloatReason>>};

const blank = (v: string): boolean => v.trim() === '';

function offsetMin(zone: string, at: number): number {
  const parts = new Intl.DateTimeFormat('en-US', {timeZone: zone, hourCycle: 'h23', year: 'numeric', month: 'numeric', day: 'numeric', hour: 'numeric', minute: 'numeric', second: 'numeric'}).formatToParts(new Date(at));
  const n = (type: string): number => Number(parts.find(p => p.type === type)!.value);
  return Math.round((Date.UTC(n('year'), n('month') - 1, n('day'), n('hour'), n('minute'), n('second')) - Math.floor(at / 1000) * 1000) / 60000);
}
const offsetText = (m: number): string => `${m < 0 ? '-' : '+'}${String(Math.floor(Math.abs(m) / 60)).padStart(2, '0')}:${String(Math.abs(m) % 60).padStart(2, '0')}`;

/** HH:mm on `date` in `zone`: the one matching instant, else why not. Never the host zone, never a guessed offset or next day. */
export function zonedTime(date: string, time: string, zone: string): {ok: true; at: number; value: FloatTime} | {ok: false; reason: FloatReason} {
  const d = /^(\d{4})-(\d{2})-(\d{2})$/.exec(date), t = /^([01]\d|2[0-3]):([0-5]\d)$/.exec(time);
  if (!d) return {ok: false, reason: 'date'};
  const [y, mo, da] = [Number(d[1]), Number(d[2]), Number(d[3])], probe = new Date(Date.UTC(y, mo - 1, da));
  if (probe.getUTCFullYear() !== y || probe.getUTCMonth() !== mo - 1 || probe.getUTCDate() !== da) return {ok: false, reason: 'date'};
  if (!t) return {ok: false, reason: 'time'};
  const guess = Date.UTC(y, mo - 1, da, Number(t[1]), Number(t[2]));
  try {
    const found = new Set<number>(), offsets = new Set([offsetMin(zone, guess - 86400000), offsetMin(zone, guess + 86400000)]);
    for (const o of offsets) { const at = guess - o * 60000; if (offsetMin(zone, at) === o) found.add(at); }
    if (found.size === 0) return {ok: false, reason: 'gap'};
    if (found.size > 1) return {ok: false, reason: 'ambiguous'};
    const at = [...found][0]!;
    return {ok: true, at, value: {date, time, zone, offset: offsetText(offsetMin(zone, at))}};
  } catch { return {ok: false, reason: 'zone'}; }
}

/** The fields as the notes record, or the reasons they cannot be. Blank fields are absent. */
export function validateFloatPlan(f: FloatPlanFields, date: string, zone: string): FloatCheck {
  const errors: Partial<Record<FloatField, FloatReason>> = {}, record: FloatPlanRecord = {};
  if (!blank(f.boat)) { if (f.boat.length > BOAT_MAX) errors.boat = 'boat-long'; else record.boat = f.boat.trim(); }
  if (!blank(f.people)) { const s = f.people.trim(); if (/^\d{1,3}$/.test(s) && Number(s) >= 1 && Number(s) <= PEOPLE_MAX) record.people = Number(s); else errors.people = 'people'; }
  const at: Partial<Record<'departure' | 'backBy', number>> = {};
  for (const k of ['departure', 'backBy'] as const) {
    if (blank(f[k])) continue;
    const r = zonedTime(date, f[k].trim(), zone);
    if (r.ok) { record[k] = r.value; at[k] = r.at; } else errors[k] = r.reason;
  }
  if (at.departure !== undefined && at.backBy !== undefined && at.backBy <= at.departure) errors.backBy = 'order';
  if (!blank(f.overdue)) { if (f.overdue.length > OVERDUE_MAX) errors.overdue = 'overdue-long'; else record.overdue = f.overdue.trim(); }
  if (Object.keys(errors).length) return {ok: false, errors};
  return {ok: true, record: Object.keys(record).length ? record : null};
}

type SeedBrief = {date: string; profile: string; bar: {hours: readonly BarHour[]; entrance: Entrance} | null; sunrise: string | null; sunset: string | null};

/** The saved boat as one line: its literal name and a finite length, `name · N ft`; blank when none (never the reference boat). */
export function boatLine(boat: {name?: unknown; loa_ft?: unknown} | null | undefined): string {
  const name = typeof boat?.name === 'string' ? boat.name.trim() : '', loa = typeof boat?.loa_ft === 'number' && Number.isFinite(boat.loa_ft) ? boat.loa_ft : null;
  return [name, loa === null ? '' : `${loa} ft`].filter(Boolean).join(' · ').slice(0, BOAT_MAX);
}

/**
 * The fields to open with. Be back by is the Boat brief's entrance window end (Run.tsx's gate, `returnBy`, the exclusive end) only
 * when the brief is for the plan's date, this region and zone and the window is judged, and it falls on that date at a whole minute
 * with one instant; otherwise empty. Nothing is searched for, fetched or guessed.
 */
export function seedFloatPlan(input: {boat: {name?: unknown; loa_ft?: unknown} | null | undefined; brief: SeedBrief | null; shown: {id: string; timezone: string} | null; region: {id: string; timezone: string}; date: string}): {fields: FloatPlanFields; backAuto: boolean} {
  const fields = emptyFloatPlan();
  fields.boat = boatLine(input.boat);
  const {brief, shown, region, date} = input;
  if (!brief || !shown || shown.id !== region.id || shown.timezone !== region.timezone || brief.profile !== 'boat' || !date || brief.date !== date || !brief.bar) return {fields, backAuto: true};
  try {
    const r = entranceWindow(brief.bar.hours, {entrance: brief.bar.entrance, sunrise: brief.sunrise ? Date.parse(brief.sunrise) : null, sunset: brief.sunset ? Date.parse(brief.sunset) : null});
    if (!r.judged || r.departBy === null || r.returnBy === null || !Number.isFinite(r.returnBy) || r.returnBy % 60000 !== 0) return {fields, backAuto: true};
    const p = new Intl.DateTimeFormat('en-CA', {timeZone: region.timezone, hourCycle: 'h23', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit'}).formatToParts(new Date(r.returnBy));
    const g = (type: string): string => p.find(x => x.type === type)!.value, time = `${g('hour')}:${g('minute')}`;
    if (`${g('year')}-${g('month')}-${g('day')}` !== date) return {fields, backAuto: true};
    const z = zonedTime(date, time, region.timezone);
    if (z.ok && z.at === r.returnBy) fields.backBy = time;
  } catch { /* an unusable brief gives no estimate */ }
  return {fields, backAuto: true};
}
