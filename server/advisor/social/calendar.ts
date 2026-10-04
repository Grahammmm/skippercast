// The content calendar (docs/plans/text-advisor/09-social.md § Content calendar,
// SP-6; TA-S4): a weekly cadence in catalog/advisor/calendar.json, slots of
// {weekdays, time_local, kind, region, capacity}.
//
//   calendarTick(env, now)     every 15-minute cron tick, before publishDue: each slot instance in
//                              the next lead_hours (48) takes the oldest approved post of its kind and
//                              region that has no scheduled_for, up to its capacity, by setting
//                              scheduled_for to the slot's time. A dated kind (daily, roundup) takes
//                              only the post made for that date (dailyPostId / roundupPostId), and
//                              one approved after its slot has passed that same day goes out now.
//                              Empty slot instances are reported (logged when the set changes).
//   calendarWeek(db, start)    the admin's week grid: every slot instance of the 7 days with the
//                              posts in it, empty ones marked, and the other scheduled or posted posts.
//   calendarPairs()            the "kind|region" pairs that have slots: publish.ts publishDue holds an
//                              unscheduled approved post of such a pair for the calendar.
//
// A slot instance is filled by a post of its kind and region whose scheduled_for is exactly the
// slot's time and whose status is approved, publishing, posted or partial. Times are local in the
// region's time zone (regions/<id>/region.json), so DST moves nothing.
import calendar from '../../../catalog/advisor/calendar.json' with {type: 'json'};
import {regionConfig} from '../answers/regions.ts';
import {addDays, localDate, PACIFIC} from '../answers/time.ts';
import {advisorLog} from '../log.ts';
import {sha256} from '../ids.ts';
import type {Env} from '../../env.ts';

export type Weekday = 'Mon' | 'Tue' | 'Wed' | 'Thu' | 'Fri' | 'Sat' | 'Sun';
export interface CalendarSlot {id: string; weekdays: Weekday[]; time_local: string; kind: string; region: string; capacity: number; note?: string}
export interface Calendar {lead_hours: number; slots: CalendarSlot[]}
export interface SlotInstance {slot: string; kind: string; region: string; date: string; time: string; at: string; capacity: number}

const WEEKDAYS: readonly Weekday[] = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
const HHMM = /^(?:[01]\d|2[0-3]):[0-5]\d$/;
/** Kinds whose posts are made for one date: a slot takes only that date's post. */
export const DATED_KINDS = ['daily', 'roundup'] as const;
/** Statuses that occupy a slot. */
const OCCUPYING = ['approved', 'publishing', 'posted', 'partial'];
export const EMPTY_KEY = 'advisor.calendar.empty';

/** The catalog's calendar, checked: unknown weekdays, bad times or duplicate ids are dropped. */
export function loadCalendar(raw: unknown = calendar): Calendar {
  const c = (raw ?? {}) as {lead_hours?: unknown; slots?: unknown};
  const seen = new Set<string>();
  const slots = (Array.isArray(c.slots) ? c.slots : []).flatMap((s: Record<string, unknown>) => {
    const weekdays = Array.isArray(s?.weekdays) ? s.weekdays.filter((d): d is Weekday => WEEKDAYS.includes(d as Weekday)) : [];
    if (typeof s?.id !== 'string' || seen.has(s.id) || !weekdays.length || typeof s.time_local !== 'string' || !HHMM.test(s.time_local)
      || typeof s.kind !== 'string' || typeof s.region !== 'string') return [];
    seen.add(s.id);
    const capacity = Number.isInteger(s.capacity) && (s.capacity as number) > 0 ? s.capacity as number : 1;
    return [{id: s.id, weekdays, time_local: s.time_local, kind: s.kind, region: s.region, capacity}];
  });
  const lead = Number(c.lead_hours);
  return {lead_hours: Number.isFinite(lead) && lead > 0 && lead <= 24 * 14 ? lead : 48, slots};
}
export const CALENDAR: Calendar = loadCalendar();

/** "kind|region" for every slot (publishDue holds unscheduled approved posts of these for the calendar). */
export const calendarPairs = (cal: Calendar = CALENDAR): string[] => [...new Set(cal.slots.map(s => `${s.kind}|${s.region}`))];

const tzOf = (region: string): string => regionConfig(region)?.timezone ?? PACIFIC;

const offsets = new Map<string, Intl.DateTimeFormat>();
/** The zone's offset from UTC at `ms`, in ms (local = utc + offset). */
function offsetAt(ms: number, tz: string): number {
  let f = offsets.get(tz);
  if (!f) { f = new Intl.DateTimeFormat('en-US', {timeZone: tz, year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23'}); offsets.set(tz, f); }
  const p: Record<string, number> = {};
  for (const {type, value} of f.formatToParts(new Date(ms))) p[type] = Number(value);
  return Date.UTC(p.year!, p.month! - 1, p.day!, p.hour! % 24, p.minute!, p.second!) - Math.floor(ms / 1000) * 1000;
}

/** The UTC instant (ISO) of a local date and HH:MM in `tz`. A time DST skips lands an hour later; a repeated one the first time. */
export function zonedInstant(date: string, time: string, tz: string): string {
  const [y, mo, d] = date.split('-').map(Number), [h, mi] = time.split(':').map(Number);
  const guess = Date.UTC(y!, mo! - 1, d!, h!, mi!);
  let at = guess - offsetAt(guess, tz);
  const again = guess - offsetAt(at, tz);
  if (again !== at) at = Math.max(at, again);   // across a change, the later reading keeps the local wall time (or the next valid one)
  return new Date(at).toISOString();
}

const weekdayOf = (date: string): Weekday => WEEKDAYS[new Date(`${date}T12:00:00Z`).getUTCDay()]!;

/** Every slot instance whose time is in [fromMs, toMs), oldest first. */
export function slotInstances(fromMs: number, toMs: number, cal: Calendar = CALENDAR): SlotInstance[] {
  const out: SlotInstance[] = [];
  for (const slot of cal.slots) {
    const tz = tzOf(slot.region);
    for (let date = addDays(localDate(fromMs, tz), -1); date <= localDate(toMs, tz); date = addDays(date, 1)) {
      if (!slot.weekdays.includes(weekdayOf(date))) continue;
      const at = zonedInstant(date, slot.time_local, tz), ms = Date.parse(at);
      if (ms >= fromMs && ms < toMs) out.push({slot: slot.id, kind: slot.kind, region: slot.region, date, time: slot.time_local, at, capacity: slot.capacity});
    }
  }
  return out.sort((a, b) => a.at.localeCompare(b.at) || a.slot.localeCompare(b.slot));
}

/** The deterministic id of a region's daily post for a local date (02 § advisor_posts: sha256('daily:' + region + ':' + date)[:32]). */
export const dailyPostId = async (region: string, date: string): Promise<string> => (await sha256(`daily:${region}:${date}`)).slice(0, 32);
/** The deterministic id of a region's roundup for the week ending on `date` (the Sunday it is drafted). */
export const roundupPostId = async (region: string, date: string): Promise<string> => (await sha256(`roundup:${region}:${date}`)).slice(0, 32);
/** The one post a dated slot instance may take, or null for an undated kind. */
export async function datedPostId(kind: string, region: string, date: string): Promise<string | null> {
  if (kind === 'daily') return dailyPostId(region, date);
  if (kind === 'roundup') return roundupPostId(region, date);
  return null;
}

export interface CalendarTickResult {scheduled: {post: string; slot: string; at: string}[]; empty: SlotInstance[]}

/** Posts of this instance's kind and region already holding its time. */
async function occupancy(db: D1Database, i: SlotInstance): Promise<number> {
  const row = await db.prepare(`SELECT COUNT(*) AS n FROM advisor_posts WHERE kind=? AND region=? AND scheduled_for=? AND status IN (${OCCUPYING.map(() => '?').join(',')})`)
    .bind(i.kind, i.region, i.at, ...OCCUPYING).first<{n: number}>();
  return row?.n ?? 0;
}

/** Give one approved post without a time this time. True when it took it (a race with another tick or an admin loses quietly). */
async function place(db: D1Database, id: string, at: string, now: number): Promise<boolean> {
  const r = await db.prepare("UPDATE advisor_posts SET scheduled_for=?,updated_at=? WHERE id=? AND status='approved' AND scheduled_for IS NULL")
    .bind(at, new Date(now).toISOString(), id).run();
  return Boolean(r.meta.changes);
}

/**
 * The calendar's every-tick run (the header). Never throws for one slot's
 * trouble: a D1 failure surfaces to the cron, which logs it.
 */
export async function calendarTick(env: Env, now: number = Date.now(), cal: Calendar = CALENDAR): Promise<CalendarTickResult> {
  const db = env.DB;
  const out: CalendarTickResult = {scheduled: [], empty: []};
  if (!db || !cal.slots.length) return out;
  // A dated post approved after its slot passed, the same local day: out now (it would never fit a later slot).
  for (const slot of cal.slots.filter(s => (DATED_KINDS as readonly string[]).includes(s.kind))) {
    const tz = tzOf(slot.region), today = localDate(now, tz);
    if (!slot.weekdays.includes(weekdayOf(today))) continue;
    const at = zonedInstant(today, slot.time_local, tz);
    if (Date.parse(at) > now) continue;
    const id = await datedPostId(slot.kind, slot.region, today);
    if (id && await place(db, id, new Date(now).toISOString(), now)) out.scheduled.push({post: id, slot: slot.id, at: new Date(now).toISOString()});
  }
  for (const instance of slotInstances(now, now + cal.lead_hours * 3600_000, cal)) {
    let free = instance.capacity - await occupancy(db, instance);
    if (free > 0) {
      const dated = await datedPostId(instance.kind, instance.region, instance.date);
      const candidates = dated
        ? [dated]
        : (await db.prepare("SELECT id FROM advisor_posts WHERE kind=? AND region=? AND status='approved' AND scheduled_for IS NULL ORDER BY approved_at, created_at, id LIMIT ?")
          .bind(instance.kind, instance.region, free).all<{id: string}>()).results.map(r => r.id);
      for (const id of candidates) {
        if (free <= 0) break;
        if (await place(db, id, instance.at, now)) { free--; out.scheduled.push({post: id, slot: instance.slot, at: instance.at}); }
      }
    }
    if (free > 0) out.empty.push(instance);
  }
  if (out.scheduled.length) advisorLog('info', 'advisor_calendar_scheduled', {count: out.scheduled.length});
  // Empty slots: logged when the set changes, not every tick.
  const signature = out.empty.map(e => `${e.slot}@${e.at}`).join(',');
  const previous = (await db.prepare('SELECT value FROM job_state WHERE key=?').bind(EMPTY_KEY).first<{value: string}>())?.value ?? null;
  if (previous !== signature) {
    await db.prepare('INSERT INTO job_state(key,value,updated_at) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at')
      .bind(EMPTY_KEY, signature, new Date(now).toISOString()).run();
    if (out.empty.length) advisorLog('info', 'advisor_calendar_empty', {count: out.empty.length, slots: [...new Set(out.empty.map(e => e.slot))].join(' ')});
  }
  return out;
}

// ---- the admin's week grid ------------------------------------------------------------------------

export interface WeekPost {id: string; kind: string; region: string; status: string; at: string; scheduled_for: string | null; posted_at: string | null; boat: string | null; summary: string}
export interface WeekSlot {slot: string; kind: string; region: string; time: string; at: string; capacity: number; posts: WeekPost[]; empty: boolean; past: boolean}
export interface WeekDay {date: string; weekday: Weekday; slots: WeekSlot[]; others: WeekPost[]}
export interface CalendarWeek {tz: string; start: string; end: string; days: WeekDay[]}

const DATE = /^\d{4}-\d{2}-\d{2}$/;
/** The Monday on or before `date`. */
export const mondayOf = (date: string): string => addDays(date, -((new Date(`${date}T12:00:00Z`).getUTCDay() + 6) % 7));

/**
 * GET /api/admin/posts/calendar?start=YYYY-MM-DD: the 7 days from the Monday of
 * `start` (default this week) in the calendar's time zone (its first slot's
 * region), every slot instance with the posts holding its time (empty when
 * fewer than its capacity), and the other posts scheduled or posted those days.
 */
export async function calendarWeek(db: D1Database, start: string | null, now: number, cal: Calendar = CALENDAR): Promise<CalendarWeek | {error: string}> {
  const tz = cal.slots[0] ? tzOf(cal.slots[0].region) : PACIFIC;
  if (start && (!DATE.test(start) || !Number.isFinite(Date.parse(`${start}T12:00:00Z`)))) return {error: 'start must be YYYY-MM-DD'};
  const first = mondayOf(start ?? localDate(now, tz)), last = addDays(first, 6);
  const fromIso = zonedInstant(first, '00:00', tz), toIso = zonedInstant(addDays(first, 7), '00:00', tz);
  const rows = (await db.prepare(`SELECT p.id,p.kind,p.region,p.status,p.scheduled_for,p.posted_at,p.caption,b.name AS boat FROM advisor_posts p LEFT JOIN advisor_boats b ON b.id=p.boat_id
      WHERE p.status IN ('approved','publishing','posted','partial','failed') AND ((p.scheduled_for>=? AND p.scheduled_for<?) OR (p.posted_at>=? AND p.posted_at<?))
      ORDER BY COALESCE(p.scheduled_for,p.posted_at), p.id LIMIT 500`)
    .bind(fromIso, toIso, fromIso, toIso).all<{id: string; kind: string; region: string; status: string; scheduled_for: string | null; posted_at: string | null; caption: string; boat: string | null}>()).results;
  const posts: WeekPost[] = rows.map(r => ({id: r.id, kind: r.kind, region: r.region, status: r.status, at: r.scheduled_for ?? r.posted_at!, scheduled_for: r.scheduled_for,
    posted_at: r.posted_at, boat: r.boat, summary: Array.from((r.caption ?? '').split('\n')[0] ?? '').slice(0, 80).join('')}));
  const used = new Set<string>();
  const instances = slotInstances(Date.parse(fromIso), Date.parse(toIso), cal);
  const days: WeekDay[] = Array.from({length: 7}, (_, k) => ({date: addDays(first, k), weekday: weekdayOf(addDays(first, k)), slots: [], others: []}));
  for (const i of instances) {
    const inSlot = posts.filter(p => !used.has(p.id) && p.kind === i.kind && p.region === i.region && p.scheduled_for === i.at && OCCUPYING.includes(p.status));
    inSlot.forEach(p => used.add(p.id));
    const day = days.find(d => d.date === localDate(Date.parse(i.at), tz));
    day?.slots.push({slot: i.slot, kind: i.kind, region: i.region, time: i.time, at: i.at, capacity: i.capacity, posts: inSlot, empty: inSlot.length < i.capacity, past: Date.parse(i.at) <= now});
  }
  for (const p of posts) {
    if (used.has(p.id)) continue;
    days.find(d => d.date === localDate(Date.parse(p.at), tz))?.others.push(p);
  }
  return {tz, start: first, end: last, days};
}
