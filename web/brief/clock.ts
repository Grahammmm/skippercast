// The brief's short clock, shared by the Boat run line (Run.tsx) and the Conditions daylight line (SC2252-08).
import {localeOf, type Language} from '../i18n.ts';

/** "8 am", "8:25 am": the lower-exposure line's clock; in Spanish the locale's own 24-hour clock in the same zone. */
export const clock = (iso: string, tz: string, lang: Language = 'en') => new Intl.DateTimeFormat(localeOf(lang), {hour: 'numeric', minute: '2-digit', timeZone: tz}).format(new Date(iso)).replace(':00', '').toLowerCase();
