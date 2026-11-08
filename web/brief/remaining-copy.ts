// SC1607-09: the search plan's field labels and no-plan sentence, and the two selected-tide save refusals, in the reader's language.
//
// web/search-plan.ts keeps building English labels and web/tide-stations.ts keeps throwing English messages (read by tests,
// packs and other callers); these adapters say them in `lang` at render. They compare only against the plan file's own field
// names and the English catalogue values of the two refusals: reviewed plan text, station names and unknown errors pass through.
//
// Erasable syntax only: Node tests import this file by type stripping.
import {t, type Language, type StringId} from '../i18n.ts';

const LABEL: Readonly<Record<string, StringId>> = {life_stage: 'where.searchPlan.lifeStage', search_for: 'where.searchPlan.searchFor', habitat: 'where.searchPlan.habitat',
  presentation: 'where.searchPlan.presentation', method: 'where.searchPlan.presentation', timing: 'where.searchPlan.timing',
  condition_response: 'where.searchPlan.conditionResponse', caution: 'where.searchPlan.caution', required_to_confirm: 'where.searchPlan.confirm'};

/** A plan line's label in `lang`: English (and an unknown field) is the item's own label. */
export function searchPlanLabel(item: {readonly field: string; readonly label: string}, lang: Language | string = 'en'): string {
  if (lang === 'en' || !Object.hasOwn(LABEL, item.field)) return item.label;
  return t(LABEL[item.field]!, lang);
}

/** The no-plan sentence in `lang`; the same fallback as noPlanText (empty or missing name: "this region"). */
export function missingSearchPlanText(regionName: string | null | undefined, lang: Language | string = 'en'): string {
  return regionName ? t('where.searchPlan.none', lang, {region: regionName}) : t('where.searchPlan.noneGeneric', lang);
}

export const TIDE_PACK_MESSAGE_IDS: readonly StringId[] = ['tidePack.unavailable', 'tidePack.notLive'];

/** A save failure's message in `lang`: only the two complete canonical refusals change; any other text comes back untouched. */
export function tidePackMessage(message: string, lang: Language | string = 'en'): string {
  if (lang === 'en') return message;
  const id = TIDE_PACK_MESSAGE_IDS.find(candidate => t(candidate, 'en') === message);
  return id ? t(id, lang) : message;
}
