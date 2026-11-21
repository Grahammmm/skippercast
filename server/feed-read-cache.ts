/** Create one cache per request for reads through the caller's loader. */
export function createFeedReadCache<T>(
  load: (key: string) => Promise<T>,
  maxKeys = 16,
): {get(key: string): Promise<T>; loads(): number} {
  if (!Number.isInteger(maxKeys) || maxKeys < 1 || maxKeys > 256) {
    throw new RangeError('maxKeys must be an integer from 1 to 256');
  }

  const held = new Map<string, Promise<T>>();
  let count = 0;

  function get(key: string): Promise<T> {
    const cached = held.get(key);
    if (cached !== undefined) return cached;
    if (held.size >= maxKeys) return Promise.reject(new RangeError('Feed read cache key limit reached'));

    let resolve!: (value: T) => void;
    let reject!: (error: unknown) => void;
    const pending = new Promise<T>((res, rej) => { resolve = res; reject = rej; });
    // Reserve the slot before calling the loader, even if it calls back into the cache.
    held.set(key, pending);
    const failed = (error: unknown) => {
      held.delete(key);
      reject(error);
    };
    count++;
    try {
      void load(key).then(resolve, failed);
    } catch (error) {
      failed(error);
    }
    return pending;
  }

  return {get, loads: () => count};
}
