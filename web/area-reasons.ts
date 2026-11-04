// "Why this area" (BF-why-this-area, build sheet 51): up to three short dated reasons for a ranked area, each naming its
// source. Pure and offline: it reads the evidence records of the one area, never the ranker's score, and changes no rank.
// It explains the ranking from the records web/ranking.ts read for the place (`targetEvidence`: the atlas or published
// mark's own survey record and the atlas's protected-area check), so no second story can disagree with the number.
// Erasable syntax only: tests/test_area_reasons.mjs imports it.

/** One dated evidence record about one area, as a feed or the atlas carries it. */
export interface EvidenceRecord {
  /** The report's own id, the same whichever feed carries it. */ readonly id?: unknown;
  readonly area: unknown; readonly species?: unknown;
  /** The kind of reason (survey, screen, report, ...): a list shows at most one reason of each kind. */ readonly kind?: unknown;
  readonly text: unknown; readonly date: unknown; readonly source: unknown; readonly sourceURL?: unknown;
  /** The feed that carried it; never part of a record's identity. */ readonly feed?: unknown;
}
export interface Reason {readonly text: string; readonly date: string; readonly source: string; readonly sourceURL: string | null}

/** How many reasons an area shows. */
export const MAX_REASONS = 3;
/** The line for an area with no dated evidence; never a filler reason. */
export const NO_REASONS = 'No dated evidence for this area yet';
const MAX_TEXT = 140;

const str = (v: unknown): string => typeof v === 'string' ? v.replace(/\s+/g, ' ').trim() : '';
const https = (v: unknown): string | null => {
  try { const u = new URL(str(v)); return u.protocol === 'https:' && !u.username && !u.password ? u.href : null; } catch { return null; }
};

/** A usable date: a real calendar day (YYYY-MM-DD), a full ISO timestamp, or a bare year; not after `now`. Else null. */
function dated(v: unknown, now: number): {ms: number; label: string} | null {
  const s = typeof v === 'number' && Number.isInteger(v) ? String(v) : str(v);
  const m = /^(\d{4})(?:-(\d{2})-(\d{2})(T[\d:.]+(?:Z|[+-]\d{2}:\d{2}))?)?$/.exec(s);
  if (!m || !Number.isFinite(now)) return null;
  const year = Number(m[1]), month = Number(m[2] ?? 1), day = Number(m[3] ?? 1), cal = new Date(Date.UTC(year, month - 1, day));
  if (year < 1900 || cal.getUTCFullYear() !== year || cal.getUTCMonth() !== month - 1 || cal.getUTCDate() !== day) return null;
  const ms = m[4] ? Date.parse(s) : cal.getTime();
  return Number.isFinite(ms) && ms <= now ? {ms, label: m[2] ? s.slice(0, 10) : m[1]!} : null;
}

/** Same words, whatever the case or punctuation of the source's name ("SoCalFishReports.com" and "socalfishreports"). */
const named = (s: string): string => s.toLowerCase().replace(/\.(com|org|net)\b/g, '').replace(/[^a-z0-9]/g, '');

/**
 * A record's identity, so one report arriving through two feeds, or under two spellings of its source, counts once:
 * its own `id` when it has one, else the tuple (source, date, area, species).
 */
const identity = (r: EvidenceRecord, source: string, date: string): string =>
  str(r.id) ? `id:${str(r.id)}` : `tuple:${named(source)}|${date}|${str(r.area)}|${str(r.species).toLowerCase()}`;

/**
 * At most MAX_REASONS dated reasons for `area`, newest first, one per distinct kind. A record with a missing, malformed or
 * future date, no text or no source is left out (an undated reason is not shown), and so is any record of another area.
 * Ties on the date fall to kind, source, then text, so the same records always give the same list.
 */
export function reasonsFor(area: string, evidence: readonly EvidenceRecord[] | null | undefined, now: number): Reason[] {
  if (!Array.isArray(evidence) || !str(area)) return [];
  const eligible: {ms: number; key: string; kind: string; reason: Reason}[] = [];
  for (const r of evidence) {
    if (!r || typeof r !== 'object' || str(r.area) !== area) continue;
    const when = dated(r.date, now), text = str(r.text), source = str(r.source);
    if (!when || !text || !source) continue;
    eligible.push({ms: when.ms, key: identity(r, source, when.label), kind: str(r.kind) || 'report', reason: {
      text: text.length > MAX_TEXT ? `${text.slice(0, MAX_TEXT - 1).trimEnd()}…` : text, date: when.label, source, sourceURL: https(r.sourceURL)}});
  }
  // Sorted before anything is dropped, so which copy of a duplicate stands never depends on the order the feeds came in.
  eligible.sort((a, b) => b.ms - a.ms || a.kind.localeCompare(b.kind) || Number(!a.reason.sourceURL) - Number(!b.reason.sourceURL)
    || a.reason.source.localeCompare(b.reason.source) || a.reason.text.localeCompare(b.reason.text));
  const keys = new Set<string>(), kinds = new Set<string>();
  const fresh = (seen: Set<string>, k: string): boolean => !seen.has(k) && (seen.add(k), true);
  return eligible.filter(e => fresh(keys, e.key) && fresh(kinds, e.kind)).slice(0, MAX_REASONS).map(e => e.reason);
}

/** The mark fields the ranker read, whether from the atlas (`spot`) or the seafloor publication (`reef`). */
interface TargetLike {
  readonly id: string; readonly source_id?: string; readonly source_name?: string; readonly source_url?: string; readonly survey_year?: number;
  readonly terrain_interpretation?: string; readonly source_rights?: readonly {credit?: unknown}[];
  readonly recorded_validation?: {readonly closed_or_screened_area_clearance_m?: number}; readonly qualification?: {readonly closure_clearance_m?: number};
}
interface AtlasLike {
  readonly title?: string; readonly source_validation_date?: string; readonly sources?: readonly {id: string; name?: string; credit?: string; url?: string}[];
}

/**
 * The dated records behind one ranked place, from the fields web/ranking.ts and the mark card (web/map/habitat.ts `atlasCard`)
 * read: its survey (year, source, terrain note) and, for an atlas mark, the atlas's protected-area check (its date and clearance).
 * Nothing is added from any other source.
 */
export function targetEvidence(t: TargetLike, atlas?: AtlasLike | null, sourceNames: Readonly<Record<string, string>> = {}): EvidenceRecord[] {
  const src = atlas?.sources?.find(s => s.id === t.source_id), credit = t.source_rights?.find(c => str(c.credit))?.credit;
  const survey: EvidenceRecord = {area: t.id, kind: 'survey', date: t.survey_year, source: t.source_name ?? sourceNames[t.source_id ?? ''] ?? src?.name ?? credit ?? src?.credit ?? t.source_id,
    sourceURL: t.source_url ?? src?.url, text: t.terrain_interpretation ?? 'Surveyed reef terrain.'};
  const m = t.recorded_validation?.closed_or_screened_area_clearance_m ?? t.qualification?.closure_clearance_m;
  const screen: EvidenceRecord[] = atlas?.source_validation_date && typeof m === 'number' && m > 0
    ? [{area: t.id, kind: 'screen', date: atlas.source_validation_date, source: atlas.title ?? 'Survey reef atlas', text: `Passed the protected-area check with ${Math.round(m)} m clearance.`}] : [];
  return [survey, ...screen];
}
