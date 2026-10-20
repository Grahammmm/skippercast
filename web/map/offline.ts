// Connectivity for ocean-layer status, independent of the saved-at banner.
// A failed read is labelled offline only after the reader tried saved data.
import {signal} from '@preact/signals';

export function watchOffline() {
  const offline = signal(globalThis.navigator?.onLine === false);
  const update = () => { offline.value = globalThis.navigator?.onLine === false; };
  globalThis.addEventListener?.('online', update);
  globalThis.addEventListener?.('offline', update);
  return {offline, destroy() {
    globalThis.removeEventListener?.('online', update);
    globalThis.removeEventListener?.('offline', update);
  }};
}

export const NOT_SAVED = 'not saved for offline';
export const COAST_NOT_SAVED = 'Coastal readings are not available offline. Save Coastal readings and check the saved pack before leaving coverage.';
export const TILES_NOT_SAVED = 'These ocean tiles are not available offline. The chart pack does not prefetch them; check the saved pack before leaving coverage.';
