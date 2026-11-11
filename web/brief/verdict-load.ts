// SC1722-02: one bounded publication epoch for the weather answer, independent of transport retries and source clocks.
// Each participating source is asked under its own ticket; only the ticket that asked may settle that source, so an
// earlier request (another region, an older context, a superseded retry) can never settle a newer one. The epoch seals
// once every source is terminal or at VERDICT_SETTLE_MS from its start, and only a sealed epoch is published as an answer.
import type {RegionInfo} from '../app/region-info.ts';
import type {ConditionsForecast, ForecastFailureReason} from '../conditions.ts';
import type {CoastSnapshot} from '../coast-data.ts';
import type {RegionalDailyFeed} from './types.ts';

export const VERDICT_SETTLE_MS = 20_000;
export type SourceState = 'pending' | 'loaded' | 'failed' | 'timedout' | 'absent';
export interface VerdictInputs {
  metadata: RegionInfo;
  daily: {feed: RegionalDailyFeed; savedAt: number | null};
  conditions: {feed: RegionalDailyFeed; savedAt: number | null};
  forecast: {forecast: ConditionsForecast; savedAt: number | null};
  coast: {snapshot: CoastSnapshot<'report'>; areaId: string};
}
export type Source = keyof VerdictInputs;
export type Slot<T> = {state: SourceState; data?: T; reason?: ForecastFailureReason; status?: number};
export type ForecastSlot = Slot<VerdictInputs['forecast']>;
export type InputSet = {[K in Source]: Slot<VerdictInputs[K]>};
/** The context parts beside the region: the forecast point and the coast binding (null until known). */
export type VerdictContext = {forecast: string | null; coast: string | null};
export interface VerdictEpoch {generation: number; region: string; context: string; parts: VerdictContext; sealed: boolean; inputs: InputSet; tickets: {[K in Source]: number}}
export const SOURCES: readonly Source[] = ['metadata', 'daily', 'conditions', 'forecast', 'coast'];
const pendingSlots = (): InputSet => ({metadata: {state: 'pending'}, daily: {state: 'pending'}, conditions: {state: 'pending'}, forecast: {state: 'pending'}, coast: {state: 'pending'}});
const contextKey = (region: string, parts: VerdictContext): string => `${region}|${parts.forecast ?? ''}|${parts.coast ?? ''}`;

export interface Scheduler {set: (fn: () => void, ms: number) => unknown; clear: (timer: unknown) => void}
const realScheduler: Scheduler = {
  set: (fn, ms) => { const timer = setTimeout(fn, ms); (timer as unknown as {unref?: () => void}).unref?.(); return timer; },
  clear: timer => clearTimeout(timer as ReturnType<typeof setTimeout>),
};

/**
 * `publish` receives the current epoch on every change (null once reset). `published()` is the last sealed epoch of this region: the
 * answer that stands while a refresh of the same context runs. Tickets and generations come from one counter, so every ticket is unique.
 */
export function createVerdictLoad(publish: (epoch: VerdictEpoch | null) => void, scheduler: Scheduler = realScheduler) {
  let serial = 0, current: VerdictEpoch | null = null, sealed: VerdictEpoch | null = null, timer: unknown;
  function clear(): void { if (timer !== undefined) scheduler.clear(timer); timer = undefined; }
  function emit(): void {
    if (!current) return;
    if (!current.sealed && SOURCES.every(k => current!.inputs[k].state !== 'pending')) { current = {...current, sealed: true}; sealed = current; clear(); }
    publish(current);
  }
  function arm(generation: number): void {
    clear();
    timer = scheduler.set(() => {
      timer = undefined;
      if (!current || current.generation !== generation || current.sealed) return;
      const inputs = {...current.inputs};
      for (const source of SOURCES) if (inputs[source].state === 'pending') inputs[source] = {state: 'timedout', ...(source === 'forecast' ? {reason: 'timeout' as const} : {})};
      current = {...current, inputs}; emit();
    }, VERDICT_SETTLE_MS);
  }
  /** A new region: every source pending under one new ticket. Returns that ticket (also the epoch's generation). */
  function start(region: string): number {
    const generation = ++serial, parts = {forecast: null, coast: null};
    sealed = null;
    current = {generation, region, context: contextKey(region, parts), parts, sealed: false, inputs: pendingSlots(),
      tickets: {metadata: generation, daily: generation, conditions: generation, forecast: generation, coast: generation}};
    arm(generation); emit();
    return generation;
  }
  /**
   * Ask `sources` again for the current region under a new ticket. A sealed epoch, or a changed context part (the forecast point, or
   * the coast binding: an earlier binding's completion then holds a stale ticket and cannot settle the new one), starts a new generation
   * (and deadline) that carries the other sources' results and tickets over, so their requests in flight still complete it.
   */
  function request(sources: readonly Source[], context: Partial<VerdictContext> = {}): number {
    if (!current) return 0;
    const ticket = ++serial, parts = {...current.parts, ...context};
    // The first point or binding of an epoch establishes its context; a different one later changes it.
    const changed = (['forecast', 'coast'] as const).some(k => current!.parts[k] !== null && parts[k] !== current!.parts[k]);
    const inputs = {...current.inputs}, tickets = {...current.tickets};
    for (const source of sources) { inputs[source] = {state: 'pending'}; tickets[source] = ticket; }
    if (current.sealed || changed) {
      current = {generation: ticket, region: current.region, context: contextKey(current.region, parts), parts, sealed: false, inputs, tickets};
      arm(ticket);
    } else current = {...current, context: contextKey(current.region, parts), parts, inputs, tickets};
    emit();
    return ticket;
  }
  function settle<K extends Source>(ticket: number, source: K, slot: Slot<VerdictInputs[K]>): void {
    if (!current || current.sealed || current.tickets[source] !== ticket || current.inputs[source].state !== 'pending' || slot.state === 'pending') return;
    current = {...current, inputs: {...current.inputs, [source]: slot}}; emit();
  }
  function reset(): void { clear(); ++serial; current = null; sealed = null; publish(null); }
  return {start, request, settle, reset, peek: (): VerdictEpoch | null => current, published: (): VerdictEpoch | null => sealed};
}
export type VerdictLoad = ReturnType<typeof createVerdictLoad>;
