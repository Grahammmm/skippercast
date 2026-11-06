// Connectivity for ocean-layer status, independent of the saved-at banner.
// A failed read is labelled offline only after the reader tried saved data.
import {signal} from '@preact/signals';
import {t} from '../i18n.ts';
import {sp, type StatusCopy} from './status-copy.ts';

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

// SC1352-02: the English strings come from the catalogue; the descriptors let a layer's status show them in the page's language.
export const NOT_SAVED = t('map.status.offline.notSaved', 'en');
export const COAST_NOT_SAVED = t('map.status.offline.coastNotSaved', 'en');
export const TILES_NOT_SAVED = t('map.status.offline.tilesNotSaved', 'en');
export const COAST_OFFLINE_COPY: StatusCopy = {note: [sp('map.status.offline.notSaved')], reason: [sp('map.status.offline.coastNotSaved')]};
export const TILES_OFFLINE_COPY: StatusCopy = {note: [sp('map.status.offline.notSaved')], reason: [sp('map.status.offline.tilesNotSaved')]};
