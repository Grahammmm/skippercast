// One ticking hour clock (SC0452-05): the app shell, the dock, the hour edge and the map stage read the same
// current time, which moves on at each whole UTC hour, so a page left open past the hour shows one hour
// everywhere. Importing this module starts nothing: a clock samples and schedules only while something has
// retained it, and the last release cancels its timeout and listener. Play keeps its own fresh read.
import {signal, type ReadonlySignal} from '@preact/signals';
import {useEffect} from 'preact/hooks';

const HOUR_MS = 3_600_000;

export interface HourClock {
  /** The time last sampled; it moves on at each whole UTC hour and when a hidden page is shown again. */
  readonly now: ReadonlySignal<Date>;
  /** Start ticking (or join the ticking); the returned release is idempotent, and the last release stops everything. */
  retain(): () => void;
}

export interface HourClockOptions {
  read?: () => Date;
  schedule?: (callback: () => void, delay: number) => unknown;
  cancel?: (timer: unknown) => void;
  doc?: Pick<Document, 'hidden' | 'addEventListener' | 'removeEventListener'>;
}

export function createHourClock(options: HourClockOptions = {}): HourClock {
  const read = options.read ?? ((): Date => new Date());
  const schedule = options.schedule ?? ((callback: () => void, delay: number): unknown => setTimeout(callback, delay));
  const cancel = options.cancel ?? ((timer: unknown): void => clearTimeout(timer as ReturnType<typeof setTimeout>));
  const now = signal(read());
  let retained = 0, timer: unknown, armed = false, generation = 0, doc: HourClockOptions['doc'];

  const stopTimer = (): void => {
    if (armed) cancel(timer);
    armed = false; timer = undefined;
  };
  /** Take the real time, publish it, and keep exactly one timeout waiting for the next whole hour after it. */
  const sample = (): void => {
    const at = read();
    // Publishing is a reentrancy boundary: a signal subscriber may release (or release and re-retain) the clock
    // synchronously. So this sample takes ownership first, and arms a timeout only if it still owns it afterwards.
    stopTimer();
    const mine = ++generation;
    if (at.getTime() !== now.peek().getTime()) now.value = at;
    if (mine !== generation || retained === 0) return;
    timer = schedule(() => { if (mine === generation && retained > 0) { armed = false; sample(); } }, HOUR_MS - (at.getTime() % HOUR_MS));
    armed = true;
  };
  const visibility = (): void => { if (retained > 0 && doc && !doc.hidden) sample(); };

  return {
    now,
    retain() {
      if (retained++ === 0) {
        doc = options.doc ?? (typeof document === 'undefined' ? undefined : document);
        doc?.addEventListener?.('visibilitychange', visibility); // a page-less stub document has no listeners to add
        sample();
      }
      let released = false;
      return () => {
        if (released) return;
        released = true;
        if (--retained > 0) return;
        generation++;
        stopTimer();
        doc?.removeEventListener?.('visibilitychange', visibility);
        doc = undefined;
      };
    },
  };
}

/** The clock the app shares; nothing runs until a consumer retains it. */
export const appClock: HourClock = createHourClock();

/** The current time for a component: `fixed` when given (tests; no timer), else the shared clock, which ticks while the component is mounted. */
export function useHourNow(fixed?: Date, clock: HourClock = appClock): Date {
  useEffect(() => (fixed === undefined ? clock.retain() : undefined), [fixed === undefined, clock]);
  return fixed ?? clock.now.value;
}
