// The Trip dialog's line saying how far a saved pack's forecast reaches, from the pack's own `forecast_end` (dist/offline-pack.js).
// Erasable syntax only (tests import it by type stripping).
import type {PackMeta} from './trip.ts';
import {frameTime} from './map/currents.ts';
import {DEFAULT_ZONE} from './zone.ts';
import {localeOf, t, type Language} from './i18n.ts';

/** The end in the region zone: English keeps the dock's frame time ("Sat 2 pm"), Spanish reads the platform's day and hour for the page locale (SC2052-06). */
const at = (iso: string, zone: string, lang: Language): string =>
  lang === 'es' ? new Intl.DateTimeFormat(localeOf(lang), {timeZone: zone, weekday: 'short', hour: 'numeric'}).format(new Date(iso)) : frameTime(iso, zone);

/** "Forecast saved through Sat 2 pm" in the region zone, the ended words once `now` reaches it, or "not recorded" when absent or unreadable; words from the catalogue in `lang`. */
export function forecastEndLine(meta: Pick<PackMeta, 'forecast_end'>, now: Date, zone: string = DEFAULT_ZONE, lang: Language = 'en'): string {
  const end = typeof meta.forecast_end === 'string' ? Date.parse(meta.forecast_end) : NaN;
  if (!Number.isFinite(end)) return t('trip.forecast.unrecorded', lang);
  return end > now.getTime() ? t('trip.forecast.through', lang, {at: at(meta.forecast_end!, zone, lang)}) : t('trip.forecast.ended', lang);
}
