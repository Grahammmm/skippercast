// UXFIX-08: a size a fisher reads. Below 1 GB this is the shared offline-core formatter's text unchanged;
// from 1 GB it is one decimal in GB with the language's decimal separator. offline-core.js is shared with the
// service worker and stays as it is.
import {formatBytes} from '../dist/offline-core.js';
import {localeOf, type Language} from './i18n-core.ts';

export const sizeText = (bytes: number, lang: Language | string): string =>
  bytes >= 1e9
    ? `${new Intl.NumberFormat(localeOf(lang), {minimumFractionDigits: 1, maximumFractionDigits: 1, useGrouping: false}).format(bytes / 1e9)} GB`
    : formatBytes(bytes);
