// SC1407-05 (#1762 R3): the time dock moves at once and the evidence settles once. A dock input
// (slider, keyboard, day chip, play step) replaces one preview instant that the dock's own thumb,
// readout, pressed day and aria-valuetext read before the next paint; nothing else reads it. After
// SETTLE_MS without another input, one batch writes the canonical ?day=/?hour= (setParams, replace
// history) and clears the preview, so the brief, map overlays, tide and URL follow the settled hour
// once, never once per passed hour. While a preview is pending the verdict surfaces show Updating
// (web/brief/Brief.tsx DockVerdictGuard), never the previous hour's answer under the new label.
// Share links, planner and export, alert defaults and print keep reading the canonical signals.
// Any URL sync (same values, Back/Forward, programmatic setParams), a region change, a new clock hour
// or zone, a hidden page and the last dock surface unmounting drop the preview instead of committing it.
import {batch, computed, effect, signal, untracked, type ReadonlySignal} from '@preact/signals';
import {useEffect} from 'preact/hooks';
import {dockTime, horizonDays, localParts, nearestHour, type DockTime} from './hour.ts';
import {day, hour, hourParam, region, setParams, urlEpoch} from './state.ts';

/** The pause after the last dock input before the selected hour settles. */
export const SETTLE_MS = 100;

/** Write hour `at` (epoch ms) at once: ?hour= ISO UTC, ?day= its local day unless that is today. */
export function commitDockHour(now: Date, tz: string, at: number): void {
  const d = localParts(new Date(at), tz).day;
  setParams({day: d === localParts(now, tz).day ? null : d, hour: hourParam(at / 1000)});
}

interface Preview {readonly at: number; readonly day: string; readonly now: Date; readonly tz: string; readonly context: string; readonly generation: number}

export interface DockSelectionOptions {
  delay?: number;
  schedule?: (run: () => void, ms: number) => unknown;
  cancel?: (handle: unknown) => void;
  /** The canonical context a preview belongs to; any change drops it. Read inside an effect while retained. */
  context?: () => string;
  /** The settled dock time for `now` in `tz`. */
  settled?: (now: Date, tz: string) => DockTime;
  commit?: (now: Date, tz: string, at: number) => void;
  /** The page whose hiding drops the preview; null outside a browser. */
  doc?: () => Document | null;
}

export interface DockSelection {
  /** True only while a preview waits to settle; changes on entry and exit, not on each sample. */
  readonly pending: ReadonlySignal<boolean>;
  /** The dock's shown time: the pending preview, else the settled one. */
  state(now: Date, tz: string): DockTime;
  /** Preview hour `at`; false (and nothing changes) when `at` is not a horizon hour. */
  request(now: Date, tz: string, at: number): boolean;
  /** A day chip: the shown local hour on day `d`, or the nearest hour that day has in the horizon. */
  requestDay(now: Date, tz: string, d: string, shown: DockTime): boolean;
  /** Drop the preview when the clock hour or zone it was made in has passed. */
  observe(now: Date, tz: string): void;
  /** Drop any preview without committing it. */
  cancel(): void;
  /** Hold the controller for a mounted dock surface; the returned release is idempotent. */
  retain(): () => void;
}

const hourOf = (now: Date): number => Math.floor(now.getTime() / 3_600_000);
const pageContext = (): string => `${urlEpoch.value}|${region.value}|${day.value}|${hour.value}`;
const pageSettled = (now: Date, tz: string): DockTime => dockTime(day.value, hour.value, now, tz);

export function createDockSelection(options: DockSelectionOptions = {}): DockSelection {
  const delay = options.delay ?? SETTLE_MS, context = options.context ?? pageContext, settled = options.settled ?? pageSettled;
  const schedule = options.schedule ?? ((run: () => void, ms: number) => setTimeout(run, ms));
  const unschedule = options.cancel ?? ((handle: unknown) => clearTimeout(handle as ReturnType<typeof setTimeout>));
  const commit = options.commit ?? commitDockHour;
  const doc = options.doc ?? ((): Document | null => typeof document === 'undefined' ? null : document);
  const preview = signal<Preview | null>(null);
  const pending = computed(() => preview.value !== null);
  let timer: unknown = null, generation = 0, holders = 0, release: (() => void) | null = null;

  const stop = (): void => { if (timer !== null) unschedule(timer); timer = null; generation++; };
  const cancel = (): void => { stop(); preview.value = null; };
  /** The preview when it still belongs to the current context. */
  const live = (tz: string): Preview | null => {
    const p = preview.value;
    return p && p.tz === tz && p.context === untracked(context) ? p : null;
  };

  function settle(g: number): void {
    timer = null;
    const p = preview.peek();
    if (!p || g !== generation || p.generation !== g) return;
    // A stale callback (unmounted, or the URL, region or pair moved) commits nothing.
    if (holders === 0 || p.context !== untracked(context)) { cancel(); return; }
    // The page went hidden before its visibilitychange handler ran: drop the preview, never publish it.
    if (doc()?.hidden) { cancel(); return; }
    batch(() => { preview.value = null; commit(p.now, p.tz, p.at); });
  }

  function request(now: Date, tz: string, at: number): boolean {
    if (!horizonDays(now, tz).some(d => d.hours.includes(at))) return false;
    const current = untracked(() => live(tz));
    if (current && current.at === at) return true;
    const base = untracked(() => settled(now, tz));
    // Back on the settled instant: drop the pending work and keep the URL's own form (null or explicit hour).
    if (base.index >= 0 && base.at === at) { cancel(); return true; }
    stop();
    const g = generation;
    preview.value = {at, day: localParts(new Date(at), tz).day, now, tz, context: untracked(context), generation: g};
    timer = schedule(() => settle(g), delay);
    return true;
  }

  function requestDay(now: Date, tz: string, d: string, shown: DockTime): boolean {
    const hours = horizonDays(now, tz).find(x => x.day === d)?.hours ?? [];
    const at = nearestHour(hours, localParts(new Date(shown.at), tz).hour, tz);
    return at !== null && request(now, tz, at);
  }

  function state(now: Date, tz: string): DockTime {
    const p = live(tz);
    return p ? dockTime(p.day, hourParam(p.at / 1000), now, tz) : settled(now, tz);
  }

  function observe(now: Date, tz: string): void {
    const p = preview.peek();
    if (p && (p.tz !== tz || hourOf(p.now) !== hourOf(now))) cancel();
  }

  function install(): () => void {
    let first = true;
    const dispose = effect(() => { context(); if (first) { first = false; return; } untracked(cancel); });
    const page = doc(), hidden = (): void => { if (page?.hidden) cancel(); };
    page?.addEventListener('visibilitychange', hidden);
    if (typeof addEventListener === 'function') addEventListener('pagehide', cancel);
    return () => {
      dispose();
      page?.removeEventListener('visibilitychange', hidden);
      if (typeof removeEventListener === 'function') removeEventListener('pagehide', cancel);
    };
  }

  function retain(): () => void {
    if (holders++ === 0) release = install();
    let held = true;
    return () => {
      if (!held) return;
      held = false;
      if (--holders > 0) return;
      cancel();
      release?.();
      release = null;
    };
  }

  return {pending, state, request, requestDay, observe, cancel, retain};
}

/** The page's one dock controller; importing it starts no timer or listener. */
export const dockSelection = createDockSelection();
export const dockPending = dockSelection.pending;
export const previewDockState = (now: Date, tz: string): DockTime => dockSelection.state(now, tz);
export const requestDockHour = (now: Date, tz: string, at: number): boolean => dockSelection.request(now, tz, at);
export const requestDockDay = (now: Date, tz: string, d: string, shown: DockTime): boolean => dockSelection.requestDay(now, tz, d, shown);

/** Hold the page controller while a dock surface is mounted, and drop its preview when the clock hour or zone changes. */
export function useDockSelection(now: Date, tz: string, controller: DockSelection = dockSelection): void {
  useEffect(() => controller.retain(), [controller]);
  useEffect(() => controller.observe(now, tz), [controller, tz, hourOf(now)]);
}
