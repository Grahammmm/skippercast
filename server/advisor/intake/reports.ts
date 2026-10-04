// Skipper fish reports (docs/plans/text-advisor/05-skipper-intake.md § Count-board
// photo → report, § Plain-text report, § Catch and action photos, § Corrections,
// § Auto-publish; 04 § stage 2 pending confirmation and the media-only skipper
// path). Pure parsers and texts first, then the D1 writers the consumer runs,
// then the Stage 2 flow the engine registers.
//
//   board photo   classify (07) -> count board -> readCountBoard -> draftFromBoard
//                 -> report_draft (pending_confirm) + the confirmation text
//   count text    parseCountText (deterministic) -> the same draft and confirmation
//   pending       y/yes/ok/sí/publish -> report_publish; n/no -> report_withdraw;
//                 a correction -> report_edit + "Updated: ..." and the ask again;
//                 anything else -> the model, with the pending report in the brief
//   correction    on the boat's latest report of the last 7 days, pending or published
//   photo         fish/action/scenery: queued for the feed with consent (has_person
//                 -> a media review), the no-consent line once per 7 days otherwise
//   video         a Reel candidate (queued with consent); a file the intake
//                 rejected (over 300 MB, an unknown container) gets the upload link
//   auto-publish  (SC-5) after a clean confirm with clean_reports >= ADVISOR_AUTO_PUBLISH_AFTER
//                 the offer once; AUTO / ASK ME toggle; with auto_publish=1 a
//                 report posts at once and the one-line summary still goes out
//
// A second report for the same boat, day and source (the unique index
// report_boat_day_source) is an edit of the first, never a second row. Every
// write is an action applied by the consumer (consumer.ts), idempotent by a
// stable id derived from the message.
import {t} from '../strings.ts';
import type {StringKey} from '../strings.ts';
import {resolveLinks} from '../links.ts';
import {exactSpecies, fold, resolveSpecies} from '../answers/resolve.ts';
import {regionConfig} from '../answers/regions.ts';
import {addDays, daysBetween, localDate, PACIFIC} from '../answers/time.ts';
import {reportSpeciesKey} from '../vision/species.ts';
import {visionChain, decideAcceptReading, decideCountBoard, decideHold, decideReadingUsable, MediaTooLarge} from '../vision/index.ts';
import type {Classification, CountBoardReading, ImageInput, VisionChain} from '../vision/index.ts';
import {MAX_MEDIA_BYTES} from '../media.ts';
import {uploadLinkText} from '../tools/send_upload_link.ts';
import {advisorLog} from '../log.ts';
import {sha256} from '../ids.ts';
import {boatsForContact, consentActive, parseInstagram, YES_WORDS} from './skippers.ts';
import type {ContactBoat} from './skippers.ts';
import type {Action, AdvisorContactRow, AdvisorSettings, EngineDeps, EngineResult, Language, NewReport, ReportCount, ReportEditFields, ReportFields, ReportPatch} from '../types.ts';
import type {Env} from '../../env.ts';
import type {Flow, FlowContext} from '../engine.ts';

export const PENDING_MAX_AGE_MS = 24 * 3600000;   // 04 § stage 2: a pending report answers y/n for 24 h
export const CORRECTION_DAYS = 7;                 // 05 § corrections: the boat's latest report of the last 7 days
export const BOARD_DATE_DAYS = 3;                 // 05: the board's date when read with confidence >= 0.8 and within 3 days
export const BOARD_DATE_CONFIDENCE = 0.8;
export const MAX_LINES = 30, MAX_COUNT = 9999, NOTES_MAX = 280, TRIP_MAX = 30, LABEL_MAX = 40;
export const PAGES_VERSION_KEY = 'advisor.pages.version';
export const ONCE_PREFIX = 'advisor.once.';

// ---- small helpers ----------------------------------------------------------------------

/** Lower-cased, trimmed, inner spaces collapsed, trailing . ! removed (the command normaliser). */
export const norm = (text: string | null | undefined): string => String(text ?? '').normalize('NFC').trim().toLowerCase().replace(/\s+/g, ' ').replace(/[.!¡]+$/u, '').replace(/^¡/u, '').trim();
const clampInt = (v: unknown): number | null => typeof v === 'number' && Number.isInteger(v) && v >= 0 && v <= MAX_COUNT ? v : typeof v === 'string' && /^\d{1,4}$/.test(v) ? Number(v) : null;
const cleanText = (v: unknown, max: number): string | null => {
  if (typeof v !== 'string') return null;
  const s = v.replace(/[\u0000-\u001f\u007f]/g, ' ').replace(/\s+/g, ' ').trim();
  return s ? s.slice(0, max) : null;
};
/** The local date of `now` for a boat's region (America/Los_Angeles when unknown). */
export const boatToday = (boat: {region: string} | null, now: number): string => localDate(now, regionConfig(boat?.region)?.timezone ?? PACIFIC);
/** The report id a message makes: one report per message, the same on a retry. */
export const reportIdFor = async (messageId: string): Promise<string> => (await sha256(`report:${messageId}`)).slice(0, 32);

// ---- species and labels ---------------------------------------------------------------

/**
 * A report line's species key from the skipper's word (05 § count board):
 * species-synonyms.json and the catalog, filed under the catalog parent
 * ("reds"/"vermilion" -> rockfish); cabezon and kelp greenling keep their
 * species-extra keys (no catalog parent); anything else is 'other'.
 */
export function speciesKeyFor(label: string): string {
  const found = resolveSpecies(label);
  return found ? reportSpeciesKey(found.key) : 'other';
}
/** The label as shown: lower case, except an all-caps abbreviation ("WSB"). */
export const displayLabel = (label: string): string => (label.length > 1 && !/\p{Ll}/u.test(label.slice(1)) && /\p{Lu}/u.test(label) ? label : label.toLowerCase());

// ---- trip type and dates ---------------------------------------------------------------

const TRIP_WORDS: [RegExp, string][] = [
  [/\b(?:half[- ]?day|1\/2[- ]?day|medio[- ]?d[ií]a)\b/iu, 'half-day'],
  [/(?:\b3\/4[- ]?day\b|\bthree[- ]quarter[- ]day\b|\b3\/4[- ]?de[- ]?d[ií]a\b)/iu, '3/4 day'],
  [/\b(?:full[- ]?day|d[ií]a[- ]completo|todo el d[ií]a)\b/iu, 'full-day'],
  [/\b(?:overnight|over night|nocturno|de noche|toda la noche)\b/iu, 'overnight'],
];
/** A trip type from words ('half-day', 'full-day', 'overnight', '3/4 day'), free text up to 30 characters, or null. */
export function normalizeTrip(text: string | null | undefined): string | null {
  const v = cleanText(text, 200);
  if (!v) return null;
  for (const [re, key] of TRIP_WORDS) if (re.test(v)) return key;
  return v.slice(0, TRIP_MAX);
}

const WEEKDAY_NAMES: Record<string, number> = {
  sunday: 0, sun: 0, monday: 1, mon: 1, tuesday: 2, tue: 2, tues: 2, wednesday: 3, wed: 3, thursday: 4, thu: 4, thurs: 4, friday: 5, fri: 5, saturday: 6, sat: 6,
  domingo: 0, lunes: 1, martes: 2, miercoles: 3, jueves: 4, viernes: 5, sabado: 6,
};
const MONTHS: Record<string, number> = {
  jan: 1, january: 1, feb: 2, february: 2, mar: 3, march: 3, apr: 4, april: 4, may: 5, jun: 6, june: 6, jul: 7, july: 7, aug: 8, august: 8, sep: 9, sept: 9, september: 9,
  oct: 10, october: 10, nov: 11, november: 11, dec: 12, december: 12,
  ene: 1, enero: 1, febrero: 2, marzo: 3, abr: 4, abril: 4, mayo: 5, junio: 6, julio: 7, ago: 8, agosto: 8, septiembre: 9, set: 9, octubre: 10, noviembre: 11, dic: 12, diciembre: 12,
};
const weekdayOf = (date: string): number => new Date(`${date}T12:00:00Z`).getUTCDay();
/**
 * A trip date from words, relative to `today` (YYYY-MM-DD): today/hoy,
 * yesterday/ayer, a weekday (the most recent one, today included), M/D,
 * YYYY-MM-DD, "Oct 2" or "2 de oct". Only today and the `maxDays` before it;
 * anything else is null.
 */
export function parseDateWords(text: string, today: string, maxDays = CORRECTION_DAYS): string | null {
  const v = fold(text).replace(/\b(?:on|el|the|last|pasado)\b/g, ' ').replace(/\s+/g, ' ').trim();
  let date: string | null = null;
  if (/^(?:today|hoy)$/.test(v)) date = today;
  else if (/^(?:yesterday|ayer)$/.test(v)) date = addDays(today, -1);
  else if (Object.hasOwn(WEEKDAY_NAMES, v)) { const want = WEEKDAY_NAMES[v]!; const back = (weekdayOf(today) - want + 7) % 7; date = addDays(today, -back); }
  else {
    let m: RegExpExecArray | null, month = 0, day = 0, year = Number(today.slice(0, 4));
    if ((m = /^(\d{4}) (\d{1,2}) (\d{1,2})$/.exec(v))) { year = Number(m[1]); month = Number(m[2]); day = Number(m[3]); }
    else if ((m = /^(\d{1,2}) (\d{1,2})(?: (\d{2,4}))?$/.exec(String(text).trim().replace(/[/-]/g, ' ').replace(/\s+/g, ' ')))) { month = Number(m[1]); day = Number(m[2]); if (m[3]) year = Number(m[3].length === 2 ? `20${m[3]}` : m[3]); }
    else if ((m = /^([a-z]+) (\d{1,2})$/.exec(v)) && MONTHS[m[1]!]) { month = MONTHS[m[1]!]!; day = Number(m[2]); }
    else if ((m = /^(\d{1,2}) (?:de )?([a-z]+)$/.exec(v)) && MONTHS[m[2]!]) { month = MONTHS[m[2]!]!; day = Number(m[1]); }
    if (month) {
      const iso = `${String(year).padStart(4, '0')}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
      const parsed = new Date(`${iso}T12:00:00Z`);
      if (!Number.isNaN(parsed.getTime()) && parsed.toISOString().slice(0, 10) === iso) {
        // "Dec 30" read on Jan 2 is last year's.
        date = daysBetween(iso, today) < 0 && !/^\d{4}/.test(v) ? `${year - 1}${iso.slice(4)}` : iso;
      }
    }
  }
  if (!date) return null;
  const back = daysBetween(date, today);
  return back >= 0 && back <= maxDays ? date : null;
}

/** "Sat Oct 3" / "sáb 3 oct". */
export function formatDate(date: string, language: Language): string {
  const d = new Date(`${date}T12:00:00Z`);
  if (language === 'es') {
    const wd = new Intl.DateTimeFormat('es', {weekday: 'short', timeZone: 'UTC'}).format(d).replace(/\.$/, '');
    const mo = new Intl.DateTimeFormat('es', {month: 'short', timeZone: 'UTC'}).format(d).replace(/\.$/, '');
    return `${wd} ${d.getUTCDate()} ${mo}`;
  }
  const wd = new Intl.DateTimeFormat('en-US', {weekday: 'short', timeZone: 'UTC'}).format(d);
  const mo = new Intl.DateTimeFormat('en-US', {month: 'short', timeZone: 'UTC'}).format(d);
  return `${wd} ${mo} ${d.getUTCDate()}`;
}
const TRIP_KEYS: Record<string, StringKey> = {'half-day': 'trip_half_day', 'full-day': 'trip_full_day', overnight: 'trip_overnight'};
export const tripText = (trip: string, language: Language): string => (TRIP_KEYS[trip] ? t(language, TRIP_KEYS[trip]!) : trip);

// ---- the confirmation text (05 § count board step 3) ---------------------------------------

export interface ReportView extends ReportFields {boat_name: string}

/** One count line: "12 lingcod (2 released)", "12? lingcod" when uncertain, "? lingcod" when unreadable. */
export function countLine(c: ReportCount, language: Language): string {
  const n = `${c.kept ?? ''}${c.uncertain || c.kept === null ? '?' : ''}`;
  const rel = c.released ? ` (${t(language, 'report_released', {n: c.released})})` : '';
  return `${n} ${displayLabel(c.label)}${rel}`;
}
const countsText = (counts: readonly ReportCount[], language: Language): string => counts.length ? counts.map(c => countLine(c, language)).join(', ') : t(language, 'report_no_counts');
const header = (r: ReportView, language: Language): string => [r.boat_name, formatDate(r.report_date, language),
  ...(r.trip_type ? [tripText(r.trip_type, language)] : []), ...(r.anglers !== null ? [t(language, 'report_anglers', {n: r.anglers})] : [])].join(', ');

/** The report as two lines (header, counts) plus the notes when there are any. */
export function summaryText(r: ReportView, language: Language): string {
  return [`${header(r, language)}:`, countsText(r.counts, language), ...(r.notes ? [`${t(language, 'report_notes')}: ${r.notes}`] : [])].join('\n');
}
/** The one-line summary an auto-published report gets (05 § auto-publish). */
export const oneLine = (r: ReportView, language: Language): string => `${header(r, language)}: ${countsText(r.counts, language)}`;

/**
 * The confirmation (05 § count board step 3):
 *   Rita G, Sat Oct 3, full day, 22 anglers:
 *   45 vermilion, 12 lingcod (2 released), 8 copper, 3 cabezon
 *   Reply Y to post, or tell me what to fix.
 * Uncertain lines carry "?" (07 § thresholds); notes, when present, are shown too.
 */
export function confirmationText(report: ReportView, language: Language): string {
  return `${summaryText(report, language)}\n${t(language, 'report_confirm_ask')}`;
}

// ---- count board -> draft (05 § count board step 2) -----------------------------------------

/**
 * A draft from a count-board reading: the board's date when read with
 * confidence >= 0.8 and within 3 days (today included), else today in the
 * boat's region; anglers and trip type when present; each line mapped to a
 * species key with the board's label kept; lines below the acceptance
 * thresholds (07) marked uncertain for "?".
 */
export function draftFromBoard(reading: CountBoardReading, _contact: Pick<AdvisorContactRow, 'id'> | null, boat: {region: string}, now: number): ReportFields {
  const today = boatToday(boat, now);
  let date = today;
  if (reading.date_iso && reading.date_confidence >= BOARD_DATE_CONFIDENCE) {
    const back = daysBetween(reading.date_iso, today);
    if (back >= 0 && back <= BOARD_DATE_DAYS) date = reading.date_iso;
  }
  const uncertain = new Set(decideAcceptReading(reading).uncertain);
  const counts: ReportCount[] = [];
  reading.lines.slice(0, MAX_LINES).forEach((line, i) => {
    const label = cleanText(line.label, LABEL_MAX);
    if (!label) return;
    const c: ReportCount = {species_key: speciesKeyFor(label), label, kept: clampInt(line.count), released: clampInt(line.released)};
    if (uncertain.has(i)) c.uncertain = true;
    counts.push(c);
  });
  return {report_date: date, trip_type: normalizeTrip(reading.trip_type), anglers: clampInt(reading.anglers), counts, notes: cleanText(reading.notes, NOTES_MAX)};
}

// ---- plain-text report (05 § plain-text report) ---------------------------------------------

export const ANGLER_WORDS = String.raw`(?:anglers?|pax|people|persons|personas|pescadores|clientes|fishermen)`;
/** 05's pre-router trigger: "<n> anglers" (also pax, people, personas, pescadores). */
export const COUNT_TRIGGER = new RegExp(String.raw`\b\d{1,4}\s*${ANGLER_WORDS}\b`, 'iu');
const RELEASED = String.raw`(?:rel(?:eased|'d|d)?|released|liberad[oa]s?|suelt[oa]s?|lib)`;
const ITEM = new RegExp(String.raw`^(\d{1,4})\s*(?:x\s+)?([\p{L}][\p{L}'’ .-]*?)\s*(?:\(\s*(\d{1,4})\s*${RELEASED}\.?\s*\)|\s+\+?\s*(\d{1,4})\s*${RELEASED}\.?|\s+(${RELEASED}))?$`, 'iu');
const RELEASED_ONLY = new RegExp(String.raw`^\(?\+?\s*(\d{1,4})\s*${RELEASED}\.?\)?$`, 'iu');
/** Words after a number that are not fish (units, times): such an item goes to the notes. */
const NOT_FISH = new Set(['am', 'pm', 'hr', 'hrs', 'hour', 'hours', 'horas', 'hora', 'min', 'mins', 'minutes', 'minutos', 'mile', 'miles', 'millas', 'mi', 'ft', 'feet', 'foot', 'pies',
  'fathom', 'fathoms', 'fa', 'brazas', 'knot', 'knots', 'kt', 'kts', 'nudos', 'lb', 'lbs', 'pound', 'pounds', 'libras', 'kg', 'kilos', 'in', 'inch', 'inches', 'pulgadas', 'day', 'days',
  'dias', 'días', 'boat', 'boats', 'barcos', 'trip', 'trips', 'viajes', 'degree', 'degrees', 'grados', 'deg', 'percent', 'am.', 'pm.', 'st', 'nd', 'rd', 'th', 'limits', 'limit']);

export interface ParsedCountText {day_offset: 0 | -1 | null; trip_type: string | null; anglers: number | null; counts: ReportCount[]; notes: string | null}

/**
 * The deterministic plain-text report grammar (05 § plain-text report): comma
 * or newline separated "<n> <label>" items (also ";", " and ", " y ", and a
 * new item starting at a number), "(<n> rel)" or "<n> released" after an item
 * (or as its own item, for the line before), "yesterday"/"ayer",
 * "half day"/"full day"/"overnight" (es too), "<n> anglers|pax|people|personas"
 * anywhere. Whatever does not parse is kept as notes. Null when there are fewer
 * than two count items and no anglers.
 */
export function parseCountText(text: string): ParsedCountText | null {
  let rest = String(text ?? '').replace(/[\u0000-\u0009\u000b-\u001f\u007f]/g, ' ').slice(0, 2000);
  let day: 0 | -1 | null = null, trip: string | null = null, anglers: number | null = null;
  rest = rest.replace(/\b(?:yesterday|ayer)\b/giu, () => { day = -1; return ' '; }).replace(/\b(?:today|hoy)\b/giu, () => { day ??= 0; return ' '; });
  for (const [re, key] of TRIP_WORDS) rest = rest.replace(new RegExp(String.raw`${re.source}(?:\s+trip|\s+viaje)?`, 'giu'), () => { trip ??= key; return ' '; });
  rest = rest.replace(new RegExp(String.raw`\b(\d{1,4})\s*${ANGLER_WORDS}\b`, 'giu'), (_w, n: string) => { anglers ??= Number(n); return ' , '; })
    .replace(new RegExp(String.raw`\b${ANGLER_WORDS}\s*[:=]?\s*(\d{1,4})\b`, 'giu'), (_w, n: string) => { anglers ??= Number(n); return ' , '; });
  const tidy = (x: string): string => x.replace(/^[\s:.\-–—]+|[\s:.\-–—]+$/gu, '').trim();
  const pieces = rest.split(/[,;\n]|\s+(?:and|y|&|\+)\s+/u).map(tidy).filter(Boolean);
  const counts: ReportCount[] = [], notes: string[] = [];
  const item = (piece: string, last: ReportCount | undefined): ReportCount | 'released' | null => {
    const rel = RELEASED_ONLY.exec(piece);
    if (rel && last) { last.released = (last.released ?? 0) + Number(rel[1]); return 'released'; }
    const m = ITEM.exec(piece);
    const label = m ? m[2]!.replace(/[.\s]+$/u, '').trim() : '';
    if (!m || !label || label.length > LABEL_MAX || NOT_FISH.has(fold(label)) || /^(?:of|de|del|for|para)\b/i.test(label)) return null;
    const n = Number(m[1]), allReleased = Boolean(m[5]);
    return {species_key: speciesKeyFor(label), label, kept: allReleased ? 0 : n, released: allReleased ? n : m[3] ? Number(m[3]) : m[4] ? Number(m[4]) : null};
  };
  for (const piece of pieces) {
    // "45 vermilion 12 lings" without commas: a new item starts at each number after a word; a piece
    // none of whose parts is an item ("water 58 degrees") stays whole in the notes.
    const subs = piece.split(/(?<=[\p{L}).])\s+(?=\d)/u).map(tidy).filter(Boolean);
    const found: ReportCount[] = [], loose: string[] = [];
    let released = false;
    for (const sub of subs) {
      const out = item(sub, found[found.length - 1] ?? (subs.length === 1 ? counts[counts.length - 1] : undefined));
      if (out === 'released') released = true; else if (out) found.push(out); else loose.push(sub);
    }
    if (!found.length && !(released && subs.length === 1)) { notes.push(piece); continue; }
    counts.push(...found); notes.push(...loose);
  }
  if (counts.length < 2 && anglers === null) return null;
  return {day_offset: day, trip_type: trip, anglers, counts: counts.slice(0, MAX_LINES), notes: cleanText(notes.join('; '), NOTES_MAX)};
}

/** The pre-router test (05): "<n> anglers", or at least two "<n> <species word>" pairs. */
export function looksLikeCountText(text: string): boolean {
  if (!text || text.length > 600) return false;
  if (COUNT_TRIGGER.test(text)) return true;
  const parsed = parseCountText(text);
  return Boolean(parsed && parsed.counts.filter(c => c.species_key !== 'other').length >= 2);
}

/** A ParsedCountText (or the model's propose_report input) as report fields, dated in the boat's region. */
export function fieldsFromText(parsed: ParsedCountText, boat: {region: string}, now: number): ReportFields {
  const today = boatToday(boat, now);
  return {report_date: parsed.day_offset === -1 ? addDays(today, -1) : today, trip_type: parsed.trip_type, anglers: parsed.anglers, counts: parsed.counts, notes: parsed.notes};
}

// ---- corrections (05 § corrections) -------------------------------------------------------

export type Change = {kind: 'count'; line: ReportCount} | {kind: 'removed'; label: string} | {kind: 'anglers'; n: number} | {kind: 'date'; date: string} | {kind: 'trip'; trip: string};
export interface Correction {fields: ReportEditFields; patch: ReportPatch[]; changes: Change[]}

const VERB = String.raw`(?:were|was|is|are|should be|=|:|eran|era|fueron|fue|son|es)`;
const REL_SUFFIX = String.raw`(?:\s*\(\s*(\d{1,4})\s*${RELEASED}\.?\s*\)|\s*,?\s+(\d{1,4})\s*${RELEASED}\.?)?`;
const SET_LABEL_FIRST = new RegExp(String.raw`^(?:the\s+|los\s+|las\s+|el\s+|la\s+)?([\p{L}][\p{L}'’ -]*?)\s*${VERB}?\s*(\d{1,4})${REL_SUFFIX}$`, 'iu');
const SET_NUMBER_FIRST = new RegExp(String.raw`^(\d{1,4})\s+([\p{L}][\p{L}'’ -]*?)${REL_SUFFIX}$`, 'iu');
const ADD = new RegExp(String.raw`^(?:add|plus|agrega|agregar|añade|anade|añadir|suma)\s+(\d{1,4})\s+([\p{L}][\p{L}'’ -]*?)${REL_SUFFIX}$`, 'iu');
const REMOVE = /^(?:remove|drop|take off|take out|no|quita|quitar|elimina|eliminar|borra|sin)\s+(?:the\s+|los\s+|las\s+|el\s+|la\s+)?([\p{L}][\p{L}'’ -]*)$/iu;
const ANGLERS_SET = new RegExp(String.raw`^(?:(?:it was|there were|we had|had|fueron|eran|[ée]ramos|tuvimos)\s+)?(\d{1,4})\s*${ANGLER_WORDS}$|^${ANGLER_WORDS}\s*${VERB}?\s*(\d{1,4})$`, 'iu');
const DATE_SET = /^(?:(?:it|that|this|the trip|the report)\s+(?:was|is)\s+|was\s+|fue\s+|era\s+|es\s+de\s+|it'?s\s+(?:from\s+)?)?(.+)$/iu;
const TRIP_SET = /^(?:(?:it|that)\s+was\s+(?:a\s+)?|fue\s+(?:un\s+)?|was\s+(?:a\s+)?)?(.+?)(?:\s+trip|\s+viaje)?$/iu;

/** The report line a correction names: same label, same word, the one line of that species; null when none, 'ambiguous' when several. */
function findLine(counts: readonly ReportCount[], label: string): number | 'ambiguous' | null {
  const f = fold(label), stem = (s: string) => fold(s).replace(/(?:es|s)$/, '');
  let i = counts.findIndex(c => fold(c.label) === f || stem(c.label) === stem(label));
  if (i >= 0) return i;
  const specific = exactSpecies(label)?.key;
  if (!specific) return null;
  i = counts.findIndex(c => resolveSpecies(c.label)?.key === specific);
  if (i >= 0) return i;
  const key = reportSpeciesKey(specific);
  const same = counts.flatMap((c, j) => c.species_key === key ? [j] : []);
  return same.length === 1 ? same[0]! : same.length > 1 ? 'ambiguous' : null;
}

/**
 * A correction to `report` (05 § corrections), every comma, ";" or "and"
 * separated part parsed or null: "<label|species> (were|was|is|=|:)? <n>"
 * with an optional "(<n> rel)", "<n> <label>", "add <n> <label>" (adds to an
 * existing line), "remove <label>", "<n> anglers", "it was (yesterday|<date>)"
 * (today and the 7 days before), "half day|full day|overnight". Spanish forms
 * too. `today` is the boat's local date.
 */
export function parseCorrection(text: string, report: ReportFields, today: string = localDate(Date.now())): Correction | null {
  const parts = String(text ?? '').split(/[,;\n]|\s+(?:and|y|&)\s+/u).map(s => norm(s).replace(/^(?:no,?\s+)?(?:actually|sorry|oops|correction|fix|en realidad|perd[oó]n|correcci[oó]n)[:,]?\s+/u, '').trim()).filter(Boolean);
  if (!parts.length || parts.length > 8) return null;
  const counts = report.counts.map(c => ({...c}));
  const fields: ReportEditFields = {};
  const changes: Change[] = [];
  for (const part of parts) {
    let m: RegExpExecArray | null;
    if ((m = ANGLERS_SET.exec(part))) { const n = Number(m[1] ?? m[2]); fields.anglers = n; changes.push({kind: 'anglers', n}); continue; }
    if ((m = ADD.exec(part))) {
      const label = m[2]!.trim(), n = Number(m[1]), rel = m[3] ?? m[4];
      const at = findLine(counts, label);
      if (at === 'ambiguous') return null;
      if (at === null) {
        if (!exactSpecies(label) && label.split(' ').length > 3) return null;
        counts.push({species_key: speciesKeyFor(label), label, kept: n, released: rel ? Number(rel) : null});
        changes.push({kind: 'count', line: counts[counts.length - 1]!});
      } else {
        const line = counts[at]!;
        line.kept = (line.kept ?? 0) + n; if (rel) line.released = (line.released ?? 0) + Number(rel); delete line.uncertain;
        changes.push({kind: 'count', line});
      }
      continue;
    }
    if ((m = REMOVE.exec(part))) {
      const at = findLine(counts, m[1]!.trim());
      if (at === null || at === 'ambiguous') return null;
      const [gone] = counts.splice(at, 1);
      changes.push({kind: 'removed', label: gone!.label});
      continue;
    }
    const trip = TRIP_SET.exec(part);
    const tripKey = trip ? normalizeTrip(trip[1]) : null;
    if (tripKey && ['half-day', 'full-day', 'overnight', '3/4 day'].includes(tripKey) && TRIP_WORDS.some(([re]) => re.test(trip![1]!) && trip![1]!.replace(re, '').trim() === '')) {
      fields.trip_type = tripKey; changes.push({kind: 'trip', trip: tripKey}); continue;
    }
    const dm = DATE_SET.exec(part);
    const date = dm ? parseDateWords(dm[1]!, today) : null;
    if (date) { fields.report_date = date; changes.push({kind: 'date', date}); continue; }
    m = SET_LABEL_FIRST.exec(part) ?? null;
    let label: string | null = null, n = 0, rel: string | undefined;
    if (m) { label = m[1]!.trim(); n = Number(m[2]); rel = m[3] ?? m[4]; }
    else if ((m = SET_NUMBER_FIRST.exec(part))) { label = m[2]!.trim(); n = Number(m[1]); rel = m[3] ?? m[4]; }
    if (!label || label.length > LABEL_MAX || NOT_FISH.has(fold(label))) return null;
    const at = findLine(counts, label);
    if (at === 'ambiguous') return null;
    if (at === null) {
      if (!exactSpecies(label)) return null;   // a new line needs a species word ("water was 58" is not one)
      counts.push({species_key: speciesKeyFor(label), label, kept: n, released: rel ? Number(rel) : null});
      changes.push({kind: 'count', line: counts[counts.length - 1]!});
    } else {
      const line = counts[at]!;
      line.kept = n; if (rel !== undefined) line.released = Number(rel); delete line.uncertain;
      changes.push({kind: 'count', line});
    }
  }
  if (!changes.length) return null;
  if (changes.some(c => c.kind === 'count' || c.kind === 'removed')) fields.counts = counts;
  return {fields, patch: patchOf(report, fields), changes};
}

/** The {field, from, to} list for advisor_report_edits (02), only fields that change. */
export function patchOf(report: ReportFields, fields: ReportEditFields): ReportPatch[] {
  const out: ReportPatch[] = [];
  for (const key of ['report_date', 'trip_type', 'anglers', 'counts', 'notes'] as const) {
    if (!Object.hasOwn(fields, key)) continue;
    const from = report[key], to = fields[key];
    if (JSON.stringify(from) !== JSON.stringify(to)) out.push({field: key, from, to});
  }
  return out;
}

/** "Updated: 14 lingcod (2 released)." (05 § corrections), the changed parts only. */
export function correctionText(changes: readonly Change[], language: Language): string {
  const parts = changes.map(c => c.kind === 'count' ? countLine(c.line, language) : c.kind === 'removed' ? t(language, 'report_removed', {label: displayLabel(c.label)})
    : c.kind === 'anglers' ? t(language, 'report_anglers', {n: c.n}) : c.kind === 'date' ? formatDate(c.date, language) : tripText(c.trip, language));
  return t(language, 'report_updated', {changes: parts.join(', ')});
}

// ---- D1 rows ------------------------------------------------------------------------------------

export interface ReportRow {
  id: string; boat_id: string; contact_id: string | null; region: string; port: string; report_date: string; trip_type: string | null; anglers: number | null;
  counts_json: string; source: string; media_id: string | null; status: string; verified: number; notes: string | null; version: number;
  confirmed_at: string | null; published_at: string | null; created_at: string; updated_at: string;
}

/** counts_json as report lines (bad entries dropped). */
export function countsOf(json: string | null): ReportCount[] {
  try {
    const v = JSON.parse(json ?? '[]');
    if (!Array.isArray(v)) return [];
    return v.filter(c => c && typeof c === 'object' && typeof c.label === 'string').slice(0, MAX_LINES).map(c => ({
      species_key: typeof c.species_key === 'string' ? c.species_key : 'other', label: String(c.label).slice(0, LABEL_MAX),
      kept: clampInt(c.kept), released: clampInt(c.released), ...(c.uncertain === true ? {uncertain: true} : {}),
    }));
  } catch { return []; }
}
export const fieldsOf = (row: ReportRow): ReportFields => ({report_date: row.report_date, trip_type: row.trip_type, anglers: row.anglers, counts: countsOf(row.counts_json), notes: row.notes});

/** Validated report fields (the propose_report and edit_report tools, the consumer). */
export function cleanFields(f: Partial<ReportFields>): Partial<ReportFields> {
  const out: Partial<ReportFields> = {};
  if (f.report_date !== undefined && typeof f.report_date === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(f.report_date)) out.report_date = f.report_date;
  if (f.trip_type !== undefined) out.trip_type = f.trip_type === null ? null : normalizeTrip(f.trip_type);
  if (f.anglers !== undefined) out.anglers = f.anglers === null ? null : clampInt(f.anglers);
  if (f.notes !== undefined) out.notes = f.notes === null ? null : cleanText(f.notes, NOTES_MAX);
  if (f.counts !== undefined && Array.isArray(f.counts)) out.counts = countsOf(JSON.stringify(f.counts));
  return out;
}

const iso = (ms: number): string => new Date(ms).toISOString();

/** The boat's report waiting for a yes/no (04: pending_confirm, last updated within 24 h), or the one this very message already published (a retried "y"). */
export async function pendingReport(db: D1Database, boatId: string, messageCreatedAt: string, now: number): Promise<ReportRow | null> {
  return db.prepare(`SELECT * FROM advisor_reports WHERE boat_id=? AND ((status='pending_confirm' AND updated_at>=?) OR (status='published' AND confirmed_at>=?))
    ORDER BY updated_at DESC, id LIMIT 1`).bind(boatId, iso(now - PENDING_MAX_AGE_MS), messageCreatedAt).first<ReportRow>();
}
/** The boat's latest report of the last 7 days, pending or published (05 § corrections). */
export async function latestReport(db: D1Database, boatId: string, today: string): Promise<ReportRow | null> {
  return db.prepare(`SELECT * FROM advisor_reports WHERE boat_id=? AND status IN ('pending_confirm','published') AND report_date>=? ORDER BY created_at DESC, id LIMIT 1`)
    .bind(boatId, addDays(today, -CORRECTION_DAYS)).first<ReportRow>();
}
/**
 * The report a new one for this boat and day becomes an edit of (02: "a second
 * real report the same day becomes an edit"): a live one (pending or
 * published) of any source, so a board and a typed report of the same trip
 * never both publish; else the row of the same source the unique index would
 * collide with (a withdrawn one comes back as pending).
 */
export async function sameDayReport(db: D1Database, boatId: string, date: string, source: string): Promise<ReportRow | null> {
  return db.prepare(`SELECT * FROM advisor_reports WHERE boat_id=? AND report_date=? AND (status IN ('pending_confirm','published') OR source=?)
    ORDER BY CASE WHEN status IN ('pending_confirm','published') THEN 0 ELSE 1 END, CASE WHEN source=? THEN 0 ELSE 1 END, created_at DESC LIMIT 1`).bind(boatId, date, source, source).first<ReportRow>();
}
/** The fields a second report of the day replaces: its counts, and anglers, trip and notes when it has them. */
export const replacementFields = (f: ReportFields): ReportEditFields => ({counts: f.counts, ...(f.anglers !== null ? {anglers: f.anglers} : {}),
  ...(f.trip_type ? {trip_type: f.trip_type} : {}), ...(f.notes ? {notes: f.notes} : {})});

// ---- writers (run by the consumer) -----------------------------------------------------------

/** job_state advisor.pages.version + 1: the boat and port pages' cache key (05 § boat page). */
export async function bumpPagesVersion(db: D1Database, now: number): Promise<void> {
  await db.prepare(`INSERT INTO job_state(key,value,updated_at) VALUES(?,'1',?) ON CONFLICT(key) DO UPDATE SET value=CAST(CAST(value AS INTEGER)+1 AS TEXT),updated_at=excluded.updated_at`)
    .bind(PAGES_VERSION_KEY, iso(now)).run();
}
/** The port's daily answers are deleted, so TA-A1 regenerates them with the new report (05 step 4). */
export async function invalidateDailyAnswer(db: D1Database, port: string, now: number): Promise<number> {
  const r = await db.prepare('DELETE FROM advisor_daily_answers WHERE substr(key,1,?)=?').bind(port.length + 1, `${port}:`).run();
  void now;
  return r.meta.changes ?? 0;
}
/** Publishing or editing a published report: pages version and the daily answer. */
async function republish(db: D1Database, port: string, now: number): Promise<void> {
  await bumpPagesVersion(db, now);
  await invalidateDailyAnswer(db, port, now);
}

/** True when this contact posts for the boat (its owner, or active crew). */
export async function postsFor(db: D1Database, contactId: string, boatId: string): Promise<boolean> {
  return (await boatsForContact(db, contactId)).some(b => b.id === boatId);
}

/**
 * report_draft: insert the pending report (region and port from the boat). A
 * retry finds its own row. A same-day report under another id (the unique
 * index) becomes an edit of that report. With `publish`, it is published at
 * once (auto_publish).
 */
export async function insertDraft(db: D1Database, contact: Pick<AdvisorContactRow, 'id'>, messageId: string, report: NewReport, publish: boolean, now: number, editKey: string): Promise<'inserted' | 'retry' | 'edited' | 'refused'> {
  if (!await postsFor(db, contact.id, report.boat_id)) return 'refused';
  const boat = await db.prepare('SELECT port,region FROM advisor_boats WHERE id=?').bind(report.boat_id).first<{port: string; region: string}>();
  if (!boat) return 'refused';
  const f = cleanFields(report) as ReportFields;
  if (!f.report_date) return 'refused';
  const at = iso(now);
  if (await db.prepare('SELECT 1 AS x FROM advisor_reports WHERE id=?').bind(report.id).first()) return 'retry';
  const other = await sameDayReport(db, report.boat_id, f.report_date, report.source);
  if (other) {
    // 02: "a second real report the same day becomes an edit (SC-4)" (here: one that arrived between the engine's read and this write).
    const fields = replacementFields({...f, counts: f.counts ?? [], anglers: f.anglers ?? null, trip_type: f.trip_type ?? null, notes: f.notes ?? null});
    await applyEdit(db, contact, messageId, editKey, other.id, fields, {reopen: other.status !== 'published', publish}, now);
    return 'edited';
  }
  await db.prepare(`INSERT INTO advisor_reports(id,boat_id,contact_id,region,port,report_date,trip_type,anglers,counts_json,source,media_id,status,verified,notes,version,created_at,updated_at)
    VALUES(?,?,?,?,?,?,?,?,?,?,?,'pending_confirm',0,?,1,?,?) ON CONFLICT(id) DO NOTHING`)
    .bind(report.id, report.boat_id, contact.id, boat.region, boat.port, f.report_date, f.trip_type ?? null, f.anglers ?? null, JSON.stringify(f.counts ?? []), report.source,
      report.media_id, f.notes ?? null, at, at).run();
  if (publish) await publishReport(db, contact, report.id, now, {auto: true});
  return 'inserted';
}

/**
 * Publish (05 step 4): status published, `verified` frozen from the boat,
 * confirmed_at and published_at, the "?" marks dropped; a clean confirm (no
 * edit, version 1) adds one to the boat's clean_reports; the pages version is
 * bumped and the port's daily answer invalidated. Auto-published reports are
 * not confirmations: no confirmed_at, no clean count.
 */
export async function publishReport(db: D1Database, contact: Pick<AdvisorContactRow, 'id'>, reportId: string, now: number, opts: {auto?: boolean} = {}): Promise<boolean> {
  const row = await db.prepare('SELECT * FROM advisor_reports WHERE id=?').bind(reportId).first<ReportRow>();
  if (!row || !['pending_confirm', 'draft'].includes(row.status) || !await postsFor(db, contact.id, row.boat_id)) return false;
  const at = iso(now);
  const counts = countsOf(row.counts_json).map(({uncertain: _u, ...c}) => c);
  const r = await db.prepare(`UPDATE advisor_reports SET status='published',verified=(SELECT CASE WHEN status='verified' THEN 1 ELSE 0 END FROM advisor_boats WHERE id=?),
      counts_json=?,confirmed_at=?,published_at=?,updated_at=? WHERE id=? AND status IN ('pending_confirm','draft')`)
    .bind(row.boat_id, JSON.stringify(counts), opts.auto ? null : at, at, at, reportId).run();
  if (!r.meta.changes) return false;
  if (!opts.auto && row.version === 1) await db.prepare('UPDATE advisor_boats SET clean_reports=clean_reports+1,updated_at=? WHERE id=?').bind(at, row.boat_id).run();
  await republish(db, row.port, now);
  advisorLog('info', 'advisor_report_published', {auto: Boolean(opts.auto), version: row.version});
  return true;
}

/** Withdraw a pending report ("n"): nothing was public, so nothing else changes. */
export async function withdrawReport(db: D1Database, contact: Pick<AdvisorContactRow, 'id'>, reportId: string, now: number): Promise<boolean> {
  const row = await db.prepare('SELECT boat_id FROM advisor_reports WHERE id=?').bind(reportId).first<{boat_id: string}>();
  if (!row || !await postsFor(db, contact.id, row.boat_id)) return false;
  const r = await db.prepare("UPDATE advisor_reports SET status='withdrawn',updated_at=? WHERE id=? AND status='pending_confirm'").bind(iso(now), reportId).run();
  return Boolean(r.meta.changes);
}

/**
 * An edit (05 § corrections, 02 § advisor_report_edits): one edits row per
 * message action (its id makes a retry a no-op), version + 1, the fields set.
 * While pending (or reopened: a withdrawn report the same day comes back as
 * pending) confirmed_at is cleared and the boat's clean_reports reset to 0.
 * A published report stays published: its pages version is bumped and the
 * port's daily answer invalidated. A date that another report of the boat
 * already has (same source) is refused.
 */
export async function applyEdit(db: D1Database, contact: Pick<AdvisorContactRow, 'id'>, messageId: string, key: string, reportId: string, input: ReportEditFields,
  opts: {reopen?: boolean; publish?: boolean} = {}, now: number = Date.now()): Promise<'edited' | 'retry' | 'refused'> {
  const row = await db.prepare('SELECT * FROM advisor_reports WHERE id=?').bind(reportId).first<ReportRow>();
  if (!row || !await postsFor(db, contact.id, row.boat_id)) return 'refused';
  const editId = (await sha256(`edit:${messageId}:${key}`)).slice(0, 32);
  if (await db.prepare('SELECT 1 AS x FROM advisor_report_edits WHERE id=?').bind(editId).first()) return 'retry';
  const fields = cleanFields(input);
  if (fields.report_date && fields.report_date !== row.report_date && await db.prepare('SELECT 1 AS x FROM advisor_reports WHERE boat_id=? AND report_date=? AND source=? AND id<>?')
    .bind(row.boat_id, fields.report_date, row.source, row.id).first()) { advisorLog('warn', 'advisor_report_date_taken', {}); return 'refused'; }
  const before = fieldsOf(row);
  const patch = patchOf(before, fields);
  const at = iso(now);
  const pending = row.status !== 'published';
  // Reopening brings a withdrawn (or draft) report of the day back for confirmation; a report the team rejected stays rejected.
  const status = opts.reopen && ['withdrawn', 'draft', 'pending_confirm'].includes(row.status) ? 'pending_confirm' : row.status;
  const sets: [string, unknown][] = [];
  if (fields.report_date !== undefined) sets.push(['report_date', fields.report_date]);
  if (fields.trip_type !== undefined) sets.push(['trip_type', fields.trip_type]);
  if (fields.anglers !== undefined) sets.push(['anglers', fields.anglers]);
  if (fields.notes !== undefined) sets.push(['notes', fields.notes]);
  if (fields.counts !== undefined) sets.push(['counts_json', JSON.stringify(row.status === 'published' ? fields.counts.map(({uncertain: _u, ...c}) => c) : fields.counts)]);
  const statements = [
    db.prepare('INSERT INTO advisor_report_edits(id,report_id,contact_id,message_id,patch_json,created_at) VALUES(?,?,?,?,?,?) ON CONFLICT(id) DO NOTHING')
      .bind(editId, row.id, contact.id, messageId, JSON.stringify(patch), at),
    db.prepare(`UPDATE advisor_reports SET ${sets.map(([k]) => `${k}=?,`).join('')}status=?,version=version+1,${pending ? 'confirmed_at=NULL,' : ''}updated_at=? WHERE id=?`)
      .bind(...sets.map(([, v]) => v), status, at, row.id),
  ];
  // 05: clean_reports "reset to 0 on any edit before confirm".
  if (pending) statements.push(db.prepare('UPDATE advisor_boats SET clean_reports=0,updated_at=? WHERE id=?').bind(at, row.boat_id));
  await db.batch(statements);
  if (row.status === 'published') await republish(db, row.port, now);
  if (opts.publish && row.status !== 'published') await publishReport(db, contact, row.id, now, {auto: true});
  advisorLog('info', 'advisor_report_edited', {fields: patch.length, published: row.status === 'published'});
  return 'edited';
}

// ---- the Stage 2 flow (04 § stage 2) ----------------------------------------------------------

const CONFIRM = new Set([...YES_WORDS, 's', 'publish', 'publish it', 'post', 'post it', 'post it up', 'looks good', 'good', 'correct', 'publica', 'publícalo', 'publicalo', 'publicar', 'correcto', 'todo bien']);
const WITHDRAW = new Set(['n', 'no', 'nope', 'nah', "don't post", 'dont post', 'do not post', "don't post it", 'dont post it', 'withdraw', 'scrap it', 'delete it', 'no lo publiques', 'no publicar', 'cancelar', 'cancela']);
const AUTO_ON = /^(?:auto|auto publish|autopublish|auto-publish|autom[aá]tico|publica sin preguntar)$/u;
const AUTO_OFF = /^(?:ask me|ask me first|ask first|preg[uú]ntame|preg[uú]ntame primero)$/u;
/** The one-time lines' job_state keys. */
export const onceKey = (what: string, id: string): string => `${what}.${id}`;

const say = (settings: AdvisorSettings, language: Language, key: StringKey, vars: Record<string, string | number> = {}): Action =>
  ({type: 'send_text', text: resolveLinks(t(language, key, vars), settings.publicBase).text});
const text = (settings: AdvisorSettings, value: string): Action => ({type: 'send_text', text: resolveLinks(value, settings.publicBase).text});
const view = (boat: {name: string}, f: ReportFields): ReportView => ({...f, boat_name: boat.name});

/** True when the one-time line `key` was said (within `withinMs` of `now` when given: the no-consent line repeats weekly). */
async function said(db: D1Database, key: string, within?: {ms: number; now: number}): Promise<boolean> {
  const row = await db.prepare('SELECT updated_at FROM job_state WHERE key=?').bind(ONCE_PREFIX + key).first<{updated_at: string}>();
  if (!row) return false;
  return !within || within.now - Date.parse(row.updated_at) < within.ms;
}
export const NO_CONSENT_REPEAT_MS = 7 * 24 * 3600000;   // the no-consent line at most once per 7 days per boat

/** The boat a skipper or crew contact posts for, or null. */
export async function contactBoat(db: D1Database, contact: Pick<AdvisorContactRow, 'id' | 'boat_id'>): Promise<ContactBoat | null> {
  if (!contact.boat_id) return null;
  return (await boatsForContact(db, contact.id)).find(b => b.id === contact.boat_id) ?? null;
}

export interface DraftArgs {db: D1Database; settings: AdvisorSettings; contact: AdvisorContactRow; boat: ContactBoat; messageId: string; language: Language; now: number;
  fields: ReportFields; source: 'count-board' | 'text'; mediaId: string | null}

/**
 * A new report (board, text or the model's tools): the draft action and the
 * confirmation, or with auto_publish (and no uncertain line) the report posted
 * at once with its one-line summary. A same-day report of the same source
 * becomes an edit: a pending one is re-confirmed, a published one is updated
 * in place.
 */
export async function draftActions(a: DraftArgs): Promise<{actions: Action[]; reportId: string; edited: boolean}> {
  const {db, settings, boat, language} = a;
  const id = await reportIdFor(a.messageId);
  const auto = boat.auto_publish === 1 && !a.fields.counts.some(c => c.uncertain || c.kept === null);
  const existing = await sameDayReport(db, boat.id, a.fields.report_date, a.source);
  if (existing && existing.id !== id) {
    if (existing.status === 'rejected') return {actions: [say(settings, language, 'report_day_held', {date: formatDate(existing.report_date, language)})], reportId: existing.id, edited: false};
    const fields = replacementFields(a.fields);
    const merged: ReportFields = {...fieldsOf(existing), ...fields};
    const published = existing.status === 'published';
    const edit: Action = {type: 'report_edit', reportId: existing.id, fields, patch: patchOf(fieldsOf(existing), fields), ...(published ? {} : {reopen: true}), ...(auto && !published ? {publish: true} : {})};
    if (published) return {actions: [edit, text(settings, `${t(language, 'report_replaced')}\n${summaryText(view(boat, merged), language)}`)], reportId: existing.id, edited: true};
    if (auto) return {actions: [edit, say(settings, language, 'report_auto_posted', {summary: oneLine(view(boat, merged), language), slug: boat.slug})], reportId: existing.id, edited: true};
    return {actions: [edit, text(settings, confirmationText(view(boat, merged), language))], reportId: existing.id, edited: true};
  }
  const report: NewReport = {id, boat_id: boat.id, source: a.source, media_id: a.mediaId, ...a.fields};
  if (auto) return {actions: [{type: 'report_draft', report, publish: true}, say(settings, language, 'report_auto_posted', {summary: oneLine(view(boat, a.fields), language), slug: boat.slug})], reportId: id, edited: false};
  return {actions: [{type: 'report_draft', report}, text(settings, confirmationText(view(boat, a.fields), language))], reportId: id, edited: false};
}

/** A correction's actions: the edit and "Updated: ..." (plus the ask again while pending), or the date-taken reply. */
export async function correctionActions(db: D1Database, settings: AdvisorSettings, language: Language, row: ReportRow, c: Correction): Promise<Action[]> {
  if (c.fields.report_date && c.fields.report_date !== row.report_date && await db.prepare('SELECT 1 AS x FROM advisor_reports WHERE boat_id=? AND report_date=? AND source=? AND id<>?')
    .bind(row.boat_id, c.fields.report_date, row.source, row.id).first()) return [say(settings, language, 'report_date_taken', {date: formatDate(c.fields.report_date, language)})];
  const updated = correctionText(c.changes, language);
  const ask = row.status === 'published' ? '' : ` ${t(language, 'report_confirm_ask')}`;
  return [{type: 'report_edit', reportId: row.id, fields: c.fields, patch: c.patch}, text(settings, updated + ask)];
}

/** The texts after a confirm: "Posted." with the boat link, and the SC-5 offer once when earned. */
async function confirmActions(f: FlowContext, boat: ContactBoat, row: ReportRow): Promise<Action[]> {
  const actions: Action[] = [{type: 'report_publish', reportId: row.id}, say(f.settings, f.language, 'report_posted', {slug: boat.slug})];
  const clean = boat.clean_reports + (row.status !== 'published' && row.version === 1 ? 1 : 0);
  const after = f.settings.autoPublishAfter;
  const key = onceKey('autopub', boat.id);
  if (after > 0 && boat.auto_publish === 0 && boat.relation === 'owner' && clean >= after && !await said(f.db, key)) {
    actions.push(say(f.settings, f.language, 'auto_offer', {n: clean}), {type: 'mark_once', key});
  }
  return actions;
}

/** The vision chain for this turn: the injected one, else visionChain(env) with the engine's fetcher, clock and sleep. */
export function chainFor(env: Env, deps: EngineDeps): VisionChain {
  return deps.vision ?? visionChain(env, {...(deps.fetcher ? {fetcher: deps.fetcher} : {}), ...(deps.clock ? {now: deps.clock} : {}), ...(deps.sleep ? {sleep: deps.sleep} : {})});
}

interface MediaRow {id: string; contact_id: string; boat_id: string | null; kind: string; mime: string; bytes: number; width: number | null; height: number | null; r2_key: string; publish_state: string}

/** The image a provider reads: the stored (metadata-stripped) original in ADVISOR_MEDIA. */
export function imageOf(env: Env, row: Pick<MediaRow, 'id' | 'mime' | 'width' | 'height' | 'r2_key'>): ImageInput {
  return {media_id: row.id, mime: row.mime, ...(row.width ? {width: row.width} : {}), ...(row.height ? {height: row.height} : {}),
    bytes: async () => { const obj = await env.ADVISOR_MEDIA!.get(row.r2_key); if (!obj) throw Error('media object missing'); return obj.arrayBuffer(); }};
}

/** The photo replies (05 § catch and action photos): queued with consent, the no-consent line once, the Instagram handle asked once. */
async function photoActions(f: FlowContext, boat: ContactBoat, row: MediaRow, c: Classification | null, video: boolean): Promise<Action[]> {
  const out: Action[] = [];
  if (!consentActive(boat)) {
    const key = onceKey('noconsent', boat.id);
    if (await said(f.db, key, {ms: NO_CONSENT_REPEAT_MS, now: f.now})) out.push(say(f.settings, f.language, video ? 'video_thanks' : 'photo_thanks'));
    else out.push(say(f.settings, f.language, 'photo_no_consent'), {type: 'mark_once', key});
    return out;
  }
  out.push({type: 'media_queue', mediaId: row.id});
  if (c && decideHold(c)) out.push({type: 'review_open', kind: 'media', refId: row.id, reason: c.nsfw ? 'nsfw' : 'has_person'});
  if (video) advisorLog('info', 'advisor_reel_candidate', {mime: row.mime, bytes: row.bytes});
  if (boat.instagram) { out.push(say(f.settings, f.language, video ? 'video_queued' : 'photo_queued', {instagram: boat.instagram})); return out; }
  const key = onceKey('instagram', boat.id);
  if (boat.relation === 'owner' && !await said(f.db, key)) out.push(say(f.settings, f.language, video ? 'video_queued_ask_handle' : 'photo_queued_ask_handle'), {type: 'mark_once', key});
  else out.push(say(f.settings, f.language, video ? 'video_queued_untagged' : 'photo_queued_untagged'));
  return out;
}

/**
 * A media-only message from a skipper or crew contact (04 § stage 2): each
 * stored item in order. A count board becomes the message's one report; a
 * catch, action or scenery photo or a video goes the photo path; a file the
 * intake rejected gets the upload link. Null when nothing stored is readable
 * (the engine's acknowledgement answers).
 */
async function mediaTurn(f: FlowContext, boat: ContactBoat): Promise<EngineResult | null> {
  const ids = f.media.slice(0, 10);
  const rows = (await f.db.prepare(`SELECT id,contact_id,boat_id,kind,mime,bytes,width,height,r2_key,publish_state FROM advisor_media WHERE contact_id=? AND id IN (${ids.map(() => '?').join(',')})`)
    .bind(f.contact.id, ...ids).all<MediaRow>()).results.sort((a, b) => ids.indexOf(a.id) - ids.indexOf(b.id));
  if (!rows.length) return null;
  const actions: Action[] = [];
  let intent = 'media', reported = false;
  const vision = chainFor(f.env, f.deps);
  const upload = async (key: StringKey): Promise<Action> => {
    const link = await uploadLinkText({env: f.env, contact: f.contact, language: f.language, settings: f.settings, now: f.now});
    return link.ok ? say(f.settings, f.language, key, {link: link.text.slice(link.text.lastIndexOf(' ') + 1)}) : text(f.settings, link.text);
  };
  for (const row of rows) {
    if (row.publish_state === 'rejected' || row.kind === 'unknown') {
      // 05 § videos: anything the intake could not keep (over 300 MB, an unknown container) goes through the upload page.
      advisorLog('info', 'advisor_media_upload_offered', {bytes: row.bytes, over: row.bytes > MAX_MEDIA_BYTES});
      actions.push(await upload('media_use_upload')); intent = 'media.upload_link'; continue;
    }
    if (row.kind === 'video') { actions.push(...await photoActions(f, boat, row, null, true)); intent = 'media.video'; continue; }
    if (row.kind !== 'image' || !row.r2_key || !f.env.ADVISOR_MEDIA) continue;
    let c: Classification;
    try {
      c = await vision.classify(imageOf(f.env, row));
    } catch (error) {
      if (error instanceof MediaTooLarge) {
        // TA-M1: the consumer already waited for the media job's public.jpg; none came, so the upload link.
        advisorLog('warn', 'advisor_media_too_large', {bytes: error.bytes});
        actions.push(await upload('media_too_large')); intent = 'media.upload_link'; continue;
      }
      advisorLog('warn', 'advisor_vision_failed', {name: (error as Error)?.name ?? 'Error'});
      actions.push(say(f.settings, f.language, 'media_unavailable')); intent = 'media.unreadable'; continue;
    }
    if (decideCountBoard(c) && !reported) {
      let reading: CountBoardReading | null = null;
      try { reading = await vision.readCountBoard(imageOf(f.env, row)); } catch (error) { advisorLog('warn', 'advisor_vision_failed', {name: (error as Error)?.name ?? 'Error'}); }
      if (!reading || !decideReadingUsable(reading)) { actions.push(say(f.settings, f.language, 'report_board_unreadable')); intent = 'report.board_unreadable'; continue; }
      const fields = draftFromBoard(reading, f.contact, boat, f.now);
      const draft = await draftActions({db: f.db, settings: f.settings, contact: f.contact, boat, messageId: f.message.id, language: f.language, now: f.now, fields, source: 'count-board', mediaId: row.id});
      actions.push(...draft.actions);
      // 05 step 5: the board photo itself is Story material, queued only with consent.
      if (consentActive(boat)) { actions.push({type: 'media_queue', mediaId: row.id}); if (decideHold(c)) actions.push({type: 'review_open', kind: 'media', refId: row.id, reason: c.nsfw ? 'nsfw' : 'has_person'}); }
      reported = true; intent = 'report.count_board'; continue;
    }
    if (c.kind === 'fish' || c.kind === 'action' || c.kind === 'scenery') { actions.push(...await photoActions(f, boat, row, c, false)); if (intent === 'media') intent = 'media.photo'; continue; }
    if (c.kind === 'count_board' || c.kind === 'unknown' || c.kind === 'document') {
      // 04 leaves an ambiguous photo to the model; a fixed question does the same without a model call.
      actions.push(say(f.settings, f.language, 'media_what')); if (intent === 'media') intent = 'media.unknown'; continue;
    }
    actions.push(say(f.settings, f.language, 'media_received'));
  }
  if (!actions.length) return null;
  if (actions.some(a => a.type === 'report_draft' || (a.type === 'report_edit' && a.reopen))) {
    // A report waiting for "Y" must not share the turn with the consent question (TA-I1's 7-day re-ask), or the
    // skipper's "Y" would answer the wrong one: the re-ask waits for the next photo. Anything else carried (the
    // one-time consent decline line) goes first, so the turn ends on "Reply Y to post".
    const at = f.carry.findIndex(a => a.type === 'flow_set' && a.state?.flow === 'consent' && a.state.step === 'asked');
    if (at > 0 && f.carry[at - 1]!.type === 'send_text') f.carry.splice(at - 1, 2);
    return {actions: [...f.carry.splice(0), ...actions], intent};
  }
  // A photo-path reply comes before anything a flow carried (the consent re-ask), as the plain acknowledgement does.
  return {actions: [...actions, ...f.carry.splice(0)], intent};
}

/**
 * TA-I2's Stage 2 flow (04 § stage 2): AUTO / ASK ME, the pending
 * confirmation, count text, corrections, then the media-only skipper path.
 * Only for a skipper or crew contact with a boat; null falls through.
 */
export async function reportFlow(f: FlowContext): Promise<EngineResult | null> {
  if (!f.contact.phone_enc && f.contact.web_session) return null;
  const boat = await contactBoat(f.db, f.contact);
  if (!boat) return null;
  const words = norm(f.text);
  const today = boatToday(boat, f.now);

  if (words && (AUTO_ON.test(words) || AUTO_OFF.test(words))) {
    if (boat.relation !== 'owner') return {actions: [say(f.settings, f.language, 'owner_only')], intent: 'report.auto.not_owner'};
    const on = AUTO_ON.test(words);
    return {actions: [{type: 'auto_publish', boatId: boat.id, on}, say(f.settings, f.language, on ? 'auto_on' : 'auto_off')], intent: on ? 'report.auto.on' : 'report.auto.off'};
  }

  // The Instagram handle asked once after a photo: "@ritag" (or the bare handle within a day of the ask).
  if (words && !boat.instagram && boat.relation === 'owner') {
    const asked = await f.db.prepare('SELECT updated_at FROM job_state WHERE key=?').bind(ONCE_PREFIX + onceKey('instagram', boat.id)).first<{updated_at: string}>();
    const handle = /^@[a-z0-9._]{1,30}$/.test(words) || (asked && f.now - Date.parse(asked.updated_at) <= PENDING_MAX_AGE_MS && /^[a-z0-9._]{3,30}$/.test(words) && /[._\d]/.test(words)) ? parseInstagram(words) : null;
    if (handle) return {actions: [{type: 'boat_instagram', boatId: boat.id, instagram: handle}, say(f.settings, f.language, 'instagram_saved', {instagram: handle})], intent: 'skipper.instagram'};
  }

  if (f.text) {
    const pending = await pendingReport(f.db, boat.id, f.message.created_at, f.now);
    const waiting = pending?.status === 'pending_confirm' ? pending : null;
    if (pending && CONFIRM.has(words)) return {actions: await confirmActions(f, boat, pending), intent: 'report.confirm'};
    if (waiting && WITHDRAW.has(words)) return {actions: [{type: 'report_withdraw', reportId: waiting.id}, say(f.settings, f.language, 'report_withdrawn')], intent: 'report.withdraw'};
    // A whole report (counts with anglers) is a new report, or an edit of the same day's; a pending
    // report takes a shorter count text ("40 vermilion, 12 lings") as a correction of those lines.
    const parsed = looksLikeCountText(f.text) ? parseCountText(f.text) : null;
    const whole = parsed && parsed.counts.length > 0 && (!waiting || parsed.anglers !== null) ? parsed : null;
    if (whole) {
      const draft = await draftActions({db: f.db, settings: f.settings, contact: f.contact, boat, messageId: f.message.id, language: f.language, now: f.now,
        fields: fieldsFromText(whole, boat, f.now), source: 'text', mediaId: null});
      return {actions: draft.actions, intent: 'report.text'};
    }
    // 05 § corrections: the pending report, else the boat's latest of the last 7 days.
    const target = waiting ?? await latestReport(f.db, boat.id, today);
    const c = target ? parseCorrection(f.text, fieldsOf(target), today) : null;
    if (target && c) return {actions: await correctionActions(f.db, f.settings, f.language, target, c), intent: 'report.edit'};
    return null;
  }
  if (f.media.length) return mediaTurn(f, boat);
  return null;
}

/** The brief lines for a skipper or crew contact: the pending report (04 § stage 2 "falls through to the model with the pending report in context") and the latest one. */
export async function reportBrief(db: D1Database, boat: ContactBoat, messageCreatedAt: string, now: number): Promise<string[]> {
  const pending = await pendingReport(db, boat.id, messageCreatedAt, now);
  const lines: string[] = [];
  if (pending?.status === 'pending_confirm') {
    lines.push(`- report waiting for confirmation: yes (report_id ${pending.id}; ${oneLine(view(boat, fieldsOf(pending)), 'en')}). "y" posts it and "n" drops it without you; for other fixes call edit_report with this report_id.`);
  } else {
    lines.push('- report waiting for confirmation: no');
    const latest = await latestReport(db, boat.id, boatToday(boat, now));
    if (latest) lines.push(`- latest report: report_id ${latest.id}, ${latest.status}, ${oneLine(view(boat, fieldsOf(latest)), 'en')}`);
  }
  return lines;
}

/** The flows TA-I2 registers in engine.ts STAGE_TWO_FLOWS, after TA-I1's. */
export const REPORT_FLOWS: readonly Flow[] = [{name: 'reports', run: reportFlow}];
