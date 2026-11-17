import {signal} from '@preact/signals';
const KEY = 'skippercast-keep-awake-v1';
type Environment = {nav?: Pick<Navigator, 'wakeLock'>; doc?: Document; store?: Storage};

/** One page-wide controller: desktop and phone controls share the same lock. */
export function createKeepAwake({nav, doc, store}: Environment) {
  const supported = () => typeof nav?.wakeLock?.request === 'function';
  const enabled = signal(false), status = signal('');
  let held: WakeLockSentinel | undefined, pending = false, generation = 0;
  const release = (lock?: WakeLockSentinel) => { void lock?.release().catch(() => {}); };
  const save = () => { try { if (enabled.value) store?.setItem(KEY, '1'); else store?.removeItem(KEY); } catch { /* session only */ } };
  const clear = () => { generation++; pending = false; const lock = held; held = undefined; release(lock); };
  const request = async () => {
    if (!supported() || !enabled.value || doc?.visibilityState !== 'visible' || pending || held) return;
    const attempt = generation; pending = true;
    try {
      const lock = await nav!.wakeLock.request('screen');
      if (attempt !== generation) { release(lock); return; }
      held = lock;
      lock.addEventListener('release', () => { if (held === lock) held = undefined; }, {once: true});
    } catch {
      if (attempt === generation) { enabled.value = false; status.value = 'keepAwake.failed'; save(); }
    } finally { if (attempt === generation) pending = false; }
  };
  const set = (on: boolean) => {
    enabled.value = on && supported(); status.value = ''; save();
    if (enabled.value) void request(); else clear();
  };
  doc?.addEventListener('visibilitychange', () => {
    if (doc.visibilityState === 'visible') void request(); else clear();
  });
  // Only a saved explicit opt-in can restore the choice; a fresh device stays off.
  try { if (store?.getItem(KEY) === '1') set(true); } catch { /* session only */ }
  return {supported, enabled, status, set};
}

let shared: ReturnType<typeof createKeepAwake> | undefined;
export function keepAwake() {
  let store: Storage | undefined;
  try { store = globalThis.localStorage; } catch { /* storage may be blocked */ }
  return shared ??= createKeepAwake({nav: typeof navigator === 'undefined' ? undefined : navigator,
    doc: typeof document === 'undefined' ? undefined : document, store});
}
