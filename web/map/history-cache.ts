type Waiter<T> = {
  resolve(value: T): void;
  reject(reason: unknown): void;
};

type Flight<T> = {
  controller: AbortController;
  waiters: Set<Waiter<T>>;
  cacheable: boolean;
};

/** Session-local LRU for selected history days, independent of the underlying loader. */
export function createHistoryCache<T extends {readonly state: string}>(
  load: (region: string, layer: string, sampleAt: string, signal: AbortSignal) => Promise<T>,
  max = 32,
) {
  if (!Number.isInteger(max) || max < 1) throw new RangeError('max must be a positive integer');

  const results = new Map<string, T>();
  const pending = new Map<string, Flight<T>>();

  async function run(key: string, flight: Flight<T>, region: string, layer: string, sampleAt: string): Promise<void> {
    try {
      const value = await load(region, layer, sampleAt, flight.controller.signal);
      if (flight.cacheable && pending.get(key) === flight && (value.state === 'ready' || value.state === 'none')) {
        results.set(key, value);
        if (results.size > max) results.delete(results.keys().next().value!);
      }
      for (const waiter of flight.waiters) waiter.resolve(value);
    } catch (error) {
      for (const waiter of flight.waiters) waiter.reject(error);
    } finally {
      // An abandoned loader may settle after a replacement has started.
      if (pending.get(key) === flight) pending.delete(key);
      flight.waiters.clear();
    }
  }

  function get(region: string, layer: string, sampleAt: string, signal?: AbortSignal): Promise<T> {
    if (signal?.aborted) return Promise.reject(signal.reason);
    const key = JSON.stringify([region, layer, sampleAt]);
    const cached = results.get(key);
    if (cached !== undefined) {
      results.delete(key);
      results.set(key, cached);
      return Promise.resolve(cached);
    }

    const existing = pending.get(key);
    const flight: Flight<T> = existing ?? {controller: new AbortController(), waiters: new Set(), cacheable: true};
    const result = new Promise<T>((resolve, reject) => {
      const detach = () => signal?.removeEventListener('abort', abort);
      const waiter: Waiter<T> = {
        resolve(value) { detach(); resolve(value); },
        reject(reason) { detach(); reject(reason); },
      };
      const abort = () => {
        flight.waiters.delete(waiter);
        waiter.reject(signal!.reason);
        if (flight.waiters.size === 0) {
          pending.delete(key);
          flight.controller.abort();
        }
      };
      flight.waiters.add(waiter);
      signal?.addEventListener('abort', abort, {once: true});
    });
    if (!existing) {
      // Register the first waiter before invoking the loader, which may abort or re-enter synchronously.
      pending.set(key, flight);
      void run(key, flight, region, layer, sampleAt);
    }
    return result;
  }

  return {
    get,
    size: () => results.size,
    clear() {
      results.clear();
      // Current callers still share their load; its result no longer belongs in the cache.
      for (const flight of pending.values()) flight.cacheable = false;
    },
  };
}
