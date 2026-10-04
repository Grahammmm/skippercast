// Reply post-processing shared by the model turn (engine.ts) and the answers
// built outside it (the fish ID, the daily answer): the length rule
// (docs/plans/text-advisor/04-advisor-engine.md § stage 3, 00 principle 2:
// three SMS segments) and the rules guard (04 § stage 3, principle 4).
import {t} from './strings.ts';
import type {Language} from './types.ts';

export const REPLY_MAX = 480;

/**
 * At most three SMS segments (480 characters) unless the reply is a list: cut
 * at sentence boundaries; a link that would be cut is kept at the end.
 */
export function capReply(text: string, links: readonly string[], max = REPLY_MAX): string {
  if (text.length <= max) return text;
  const link = links[0];
  const body = link ? text.replace(link, '').replace(/\s{2,}/g, ' ').trim() : text;
  const room = link ? max - link.length - 1 : max;
  const sentences = body.split(/(?<=[.!?])\s+/);
  let out = '';
  for (const s of sentences) { if ((out ? out.length + 1 : 0) + s.length > room) break; out = out ? `${out} ${s}` : s; }
  if (!out) out = body.slice(0, Math.max(0, room - 1)).replace(/\s+\S*$/, '') + '…';
  return link ? `${out} ${link}` : out;
}


// A number next to a rule word (04 § rules guard). Three shapes:
//   a length:   "14 inch", "14-inch", '14"', "14 in.", "35 pulgadas"
//   a limit:    "10 fish limit", "a bag of 5", "limit is 2", "bag limit: 10", "límite de 10"
//   a season:   "season opens April 1", "closed until May 15", "open through Dec 31", "temporada abre el 1"
const RULE_NUMBER = new RegExp([
  String.raw`\d+(?:\.\d+)?\s*(?:-\s*)?(?:inch(?:es)?\b|in\b\.?|["”″]|pulgadas?\b)`,
  String.raw`\d+\s*(?:-\s*)?(?:fish\s+|per\s+person\s+|a\s+day\s+)?(?:bag|limits?|límites?)\b`,
  String.raw`\b(?:bag|limit|limits|límite)\s*(?:limit\s*)?(?:is|of|de|es|:|=)?\s*(?:only\s+|up\s+to\s+)?\d`,
  String.raw`\b(?:season|seasons|closed|closes|closure|closing|open|opens|opening|temporada|cerrad[ao]s?|cierra|abiert[ao]s?|abre)\b[^.!?\n\d]{0,24}\d`,
  String.raw`\d[^.!?\n\d]{0,12}\b(?:season|temporada)\b`,
].join('|'), 'i');

/** True when a sentence states a rule-like number. */
export const statesRuleNumber = (sentence: string): boolean => RULE_NUMBER.test(sentence);

/**
 * The rules guard (04 § stage 3, principle 4): when the turn has no usable
 * get_rules result, every sentence that puts a number next to inch, ",
 * limit, bag, season, closed or open is removed, and the first is replaced by
 * the CDFW line. Returns the new text and whether it fired.
 */
export function rulesGuard(text: string, language: Language): {text: string; fired: boolean} {
  const parts = String(text ?? '').split(/(?<=[.!?])\s+|\n+/);
  let fired = false;
  const kept: string[] = [];
  for (const part of parts) {
    if (!statesRuleNumber(part)) { kept.push(part); continue; }
    if (!fired) kept.push(t(language, 'rules_cdfw'));
    fired = true;
  }
  return {text: fired ? kept.filter(p => p.trim()).join(' ') : text, fired};
}

/** Plain text from a model reply that slipped into markdown: emphasis, headings, bullets, code and [text](url) links. */
export function stripMarkdown(text: string): string {
  return String(text ?? '')
    .replace(/\[([^\]]+)\]\((?:[^)]+)\)/g, '$1')
    .replace(/```[\s\S]*?```/g, m => m.replace(/```\w*\n?/g, ''))
    .replace(/`([^`]+)`/g, '$1')
    .replace(/^\s{0,3}#{1,6}\s+/gm, '')
    .replace(/^\s*[-*•]\s+/gm, '')
    .replace(/(\*\*|__)(.+?)\1/g, '$2')
    .replace(/(^|[\s(])[*_]([^*_\n]+)[*_](?=[\s).,!?]|$)/g, '$1$2')
    .replace(/\n{3,}/g, '\n\n')
    .trim();
}
