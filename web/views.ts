// View models the Preact islands render (P4-01b). Legacy modules write these
// signals instead of the DOM; web/islands.tsx renders them into existing
// slots. Erasable TypeScript only: Node tests import it through dist/*.js.
import {signal} from '@preact/signals';

/** The header's best-conditions badge (#best-day-banner). */
export interface Outlook {
  label: string;
  value: string;
  /** At least one morning rated 8+. */
  qualifying?: boolean;
  /** The button's accessible name; the static one is kept until set. */
  ariaLabel?: string;
  /** Epoch seconds of the best morning, opened on click; '' when none. */
  hour?: number | '';
}
export const INITIAL_OUTLOOK: Outlook = {label: '7-day outlook', value: 'Checking…'};
export const outlook = signal<Outlook>(INITIAL_OUTLOOK);

/** What the offline freshness banner needs; the text comes from offline-core.js. */
export interface OfflineStatus {
  online: boolean;
  /** ISO time of the oldest saved response on screen, or null. */
  savedAt: string | null;
  /** When the status was taken (epoch ms), so relative times advance. */
  now: number;
}
export const offlineStatus = signal<OfflineStatus>({online: true, savedAt: null, now: 0});
