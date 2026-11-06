// SC1137-03: the tide-station control's words and the sparkline's clock in the reader's language.
//
// web/tide-selection.ts keeps publishing its four English `error` / `notice` strings (read by tests, packs and other
// callers); this adapter says them in `lang` at render. It compares only against the English catalogue values of
// those ids: an unknown text passes through unchanged, and a provider or station name is never parsed.
//
// Erasable syntax only: Node tests import this file by type stripping.
import {localeOf, t, type Language, type StringId} from '../i18n.ts';

export const SELECTION_MESSAGE_IDS: readonly StringId[] = ['tideStation.err.directory', 'tideStation.err.missing', 'tideStation.err.partial', 'tideStation.err.cap'];

/** A model status in `lang`; English and any text that is not one of the four canonical messages come back untouched. */
export function selectionMessage(text: string, lang: Language | string = 'en'): string {
  if (lang === 'en') return text;
  const id = SELECTION_MESSAGE_IDS.find(candidate => t(candidate, 'en') === text);
  return id ? t(id, lang) : text;
}

/** A status the control keeps as data, said at render so a language switch reaches a retained or pending one. */
export interface TideNotice {readonly id: StringId; readonly vars: Readonly<Record<string, string>>}
export const noticeText = (notice: TideNotice, lang: Language | string): string => t(notice.id, lang, notice.vars);

/** An event's clock time in the chosen language: same instant and zone, minutes kept, lower case (English `1:00 pm`). */
export const eventClock = (iso: string, tz: string, lang: Language | string = 'en'): string =>
  new Intl.DateTimeFormat(localeOf(lang), {hour: 'numeric', minute: '2-digit', timeZone: tz}).format(new Date(iso)).toLowerCase();
