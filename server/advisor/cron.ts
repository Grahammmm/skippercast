// Text Advisor cron hooks (docs/plans/text-advisor/01-architecture.md § Cron
// slots and § Idempotency and failure rules), run from the Worker's existing
// */15 trigger in server/index.ts.
//
// Slots: the only trigger is UTC every 15 minutes, so local-time jobs ("07:00
// in Morro Bay") are slots. On each tick runSlot computes the local date and
// time in the slot's zone; once the local time is at or past the slot's time
// and job_state key advisor.slot.<name> is not today's local date, it claims
// the key (UPSERT with WHERE, as scheduleTripChecks does) and runs the job. A
// slot therefore runs once per local day, within 15 minutes of its time, and
// never twice; DST changes move nothing because the comparison is local. A job
// that throws releases its claim, so the next tick tries again.
//
// The relay watchdog is not a slot: it runs on every tick (01 says every 15
// minutes) and pings the Mac relay. Three consecutive failures mark it down.
// While it is down the consumer writes new BlueBubbles sends as 'held'
// (consumer.ts); releaseHeld runs after the watchdog on every tick, sends the
// held rows once the relay is up again (or through Twilio once the owner has
// set ADVISOR_CHANNEL=twilio, never automatically) and fails rows older than
// 6 hours.
import {advisorSettings} from './settings.ts';
import {advisorLog} from './log.ts';
import {RELAY_KEY, relayState} from './relay.ts';
import type {RelayState} from './relay.ts';
import {releaseHeld} from './consumer.ts';
import {channelFor} from './channels/index.ts';
import type {ConsumerDeps} from './types.ts';
import type {Env} from '../env.ts';

export const SLOT_PREFIX = 'advisor.slot.';
export {RELAY_KEY, relayState} from './relay.ts';
export type {RelayState} from './relay.ts';
export const RELAY_DOWN_AFTER = 3;          // consecutive failed pings
export const RELAY_TIMEOUT_MS = 10000;
export const DEFAULT_TZ = 'America/Los_Angeles';

export type Weekday = 'Mon' | 'Tue' | 'Wed' | 'Thu' | 'Fri' | 'Sat' | 'Sun';
export interface SlotTime {local: string; tz?: string; weekday?: Weekday}
export type SlotOutcome = 'ran' | 'not-yet' | 'done-today' | 'not-today' | 'claimed-elsewhere' | 'failed' | 'no-db';
export type SlotJob = (env: Env, now: number) => Promise<unknown>;
export interface Slot {name: string; time: SlotTime; run: SlotJob}

/**
 * Every local-time job of the advisor, one table (01 § Cron slots). Empty
 * until the tasks that own them add theirs (the daily answers, the social
 * calendar, insights, the weekly retention prune in 02). Each name is the
 * job_state key suffix and must stay stable once deployed.
 */
export const SLOTS: readonly Slot[] = [];

const parts = new Map<string, Intl.DateTimeFormat>();
/** The local calendar date (YYYY-MM-DD), time (HH:MM, 00-23) and weekday of `now` in `tz`. */
export function localClock(now: number, tz = DEFAULT_TZ): {date: string; time: string; weekday: Weekday} {
  let format = parts.get(tz);
  if (!format) {
    format = new Intl.DateTimeFormat('en-US', {timeZone: tz, year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', weekday: 'short', hourCycle: 'h23'});
    parts.set(tz, format);
  }
  const p: Record<string, string> = {};
  for (const {type, value} of format.formatToParts(new Date(now))) p[type] = value;
  return {date: `${p.year}-${p.month}-${p.day}`, time: `${p.hour === '24' ? '00' : p.hour}:${p.minute}`, weekday: p.weekday as Weekday};
}

const HHMM = /^(?:[01]\d|2[0-3]):[0-5]\d$/;
const NAME = /^[a-z0-9][a-z0-9-]{0,47}$/;

/**
 * Run `fn` once per local day at or after `time.local` (and only on
 * `time.weekday`, when given). Returns what happened, for logs and tests.
 */
export async function runSlot(env: Env, name: string, time: SlotTime, fn: SlotJob, now: number = Date.now()): Promise<SlotOutcome> {
  if (!NAME.test(name) || !HHMM.test(time.local)) throw Error(`invalid slot ${name}`);
  if (!env.DB) return 'no-db';
  const local = localClock(now, time.tz ?? DEFAULT_TZ);
  if (time.weekday && local.weekday !== time.weekday) return 'not-today';
  if (local.time < time.local) return 'not-yet';
  const key = SLOT_PREFIX + name;
  const previous = (await env.DB.prepare('SELECT value FROM job_state WHERE key=?').bind(key).first<{value: string}>())?.value ?? null;
  if (previous === local.date) return 'done-today';
  const claim = await env.DB.prepare('INSERT INTO job_state(key,value,updated_at) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at WHERE job_state.value IS NOT excluded.value')
    .bind(key, local.date, new Date(now).toISOString()).run();
  if (!claim.meta.changes) return 'claimed-elsewhere';
  try {
    await fn(env, now);
    return 'ran';
  } catch (error) {
    const release = previous === null
      ? env.DB.prepare('DELETE FROM job_state WHERE key=? AND value=?').bind(key, local.date)
      : env.DB.prepare('UPDATE job_state SET value=? WHERE key=? AND value=?').bind(previous, key, local.date);
    await release.run().catch(() => {});
    advisorLog('error', 'advisor_slot_failed', {slot: name, reason: String((error as Error)?.message).slice(0, 200)});
    return 'failed';
  }
}

export interface CronDeps {fetcher?: typeof fetch; slots?: readonly Slot[]; consumer?: ConsumerDeps}
export type RelayOutcome = 'not-configured' | 'up' | 'failing' | 'down' | 'no-db';

/**
 * Relay watchdog: when outbound goes through BlueBubbles and BLUEBUBBLES_URL is
 * set, GET {url}/api/v1/ping?password=... with the Cloudflare Access service
 * token, 10 s timeout. A 2xx is up and resets the count; anything else adds a
 * failure, and the third in a row marks the relay down and logs an error line
 * (Cloudflare alerting picks it up, like the trip watchdog). State lives in
 * job_state advisor.relay as JSON {state, failures, checked_at, last_ok_at}.
 */
export async function relayWatchdog(env: Env, deps: CronDeps = {}, now: number = Date.now()): Promise<RelayOutcome> {
  const base = (env.BLUEBUBBLES_URL ?? '').trim().replace(/\/+$/, '');
  if (advisorSettings(env).channel !== 'bluebubbles' || !base) return 'not-configured';
  if (!env.DB) return 'no-db';
  let ok = false, detail = '';
  try {
    const url = new URL(base + '/api/v1/ping');
    url.searchParams.set('password', env.BLUEBUBBLES_PASSWORD ?? '');
    const headers: Record<string, string> = {Accept: 'application/json'};
    if (env.CF_ACCESS_CLIENT_ID && env.CF_ACCESS_CLIENT_SECRET) {
      headers['CF-Access-Client-Id'] = env.CF_ACCESS_CLIENT_ID;
      headers['CF-Access-Client-Secret'] = env.CF_ACCESS_CLIENT_SECRET;
    }
    const response = await (deps.fetcher ?? fetch)(url.toString(), {headers, signal: AbortSignal.timeout(RELAY_TIMEOUT_MS)});
    ok = response.ok; detail = `http-${response.status}`;
    await response.body?.cancel().catch(() => {});
  } catch (error) { detail = (error as Error)?.name === 'TimeoutError' ? 'timeout' : 'fetch-error'; }
  const previous = await relayState(env), at = new Date(now).toISOString();
  const failures = ok ? 0 : (previous?.failures ?? 0) + 1;
  const state: RelayState['state'] = ok ? 'up' : failures >= RELAY_DOWN_AFTER ? 'down' : previous?.state ?? 'up';
  const next: RelayState = {state, failures, checked_at: at, last_ok_at: ok ? at : previous?.last_ok_at ?? null};
  await env.DB.prepare('INSERT INTO job_state(key,value,updated_at) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at')
    .bind(RELAY_KEY, JSON.stringify(next), at).run();
  if (state === 'down' && previous?.state !== 'down') advisorLog('error', 'advisor_relay_down', {failures, detail});
  else if (ok && previous?.state === 'down') advisorLog('info', 'advisor_relay_up', {});
  return ok ? 'up' : state === 'down' ? 'down' : 'failing';
}

/**
 * The advisor's part of each cron tick: the relay watchdog, then every slot
 * that is due. One word for recordCron's `advisor` field:
 *   disabled  TEXT_ADVISOR_ENABLED is off (nothing ran)
 *   no-db     no D1 binding
 *   ok        everything that ran succeeded (or nothing was due)
 *   partial   a slot failed or the relay is failing/down; the others ran
 *   error     the cron hook itself threw
 */
export async function advisorCron(env: Env, now: number = Date.now(), deps: CronDeps = {}): Promise<'ok' | 'disabled' | 'no-db' | 'partial' | 'error'> {
  if (!advisorSettings(env).enabled) return 'disabled';
  if (!env.DB) return 'no-db';
  try {
    let partial = false;
    const relay = await relayWatchdog(env, deps, now).catch(error => { advisorLog('error', 'advisor_relay_check_failed', {reason: String((error as Error)?.message).slice(0, 200)}); return 'error'; });
    if (relay === 'failing' || relay === 'down' || relay === 'error') partial = true;
    const held = await releaseHeld(env, deps.consumer ?? {channelFor}, now).catch(error => { advisorLog('error', 'advisor_release_failed', {reason: String((error as Error)?.message).slice(0, 200)}); return null; });
    if (!held) partial = true;
    for (const slot of deps.slots ?? SLOTS) {
      const outcome = await runSlot(env, slot.name, slot.time, slot.run, now);
      if (outcome === 'failed') partial = true;
      if (outcome === 'ran') advisorLog('info', 'advisor_slot_ran', {slot: slot.name});
    }
    return partial ? 'partial' : 'ok';
  } catch (error) {
    advisorLog('error', 'advisor_cron_failed', {reason: String((error as Error)?.message).slice(0, 200)});
    return 'error';
  }
}
