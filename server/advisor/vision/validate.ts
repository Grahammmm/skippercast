// Vision result validation shared by every provider (docs/plans/text-advisor/07-vision.md
// § As built (TA-V1), Validation; TA-V2 moved it here from claude.ts so the
// Hermes client validates exactly as the Claude provider does). Nothing a
// provider returns reaches the advisor without passing through one of these:
// confidences clamped to 0..1, booleans only when literally true, dates real
// YYYY-MM-DD, counts non-negative integers, species keys limited to the set the
// client offered (a key outside it becomes null with its label kept), at most
// three fish candidates sorted by confidence.
import {IMAGE_KINDS} from './errors.ts';
import type {Classification, CountBoardReading, FishId, ImageKind} from './index.ts';

/** What the caller fills: the provider, the model it reported, the measured milliseconds. */
export type ResultMeta = {provider: 'hermes' | 'claude'; model: string; ms: number};

export const clamp01 = (v: unknown): number => typeof v === 'number' && Number.isFinite(v) ? Math.min(1, Math.max(0, v)) : 0;
const bool = (v: unknown): boolean => v === true;
function str(v: unknown, max: number): string | null {
  if (typeof v !== 'string') return null;
  const s = v.replace(/\s+/g, ' ').trim();
  return s ? s.slice(0, max) : null;
}
function int(v: unknown, max: number): number | null {
  const n = typeof v === 'string' && /^\d+$/.test(v.trim()) ? Number(v) : v;
  return typeof n === 'number' && Number.isInteger(n) && n >= 0 && n <= max ? n : null;
}
function isoDate(v: unknown): string | null {
  if (typeof v !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(v)) return null;
  const d = new Date(v + 'T00:00:00Z');
  return Number.isFinite(d.getTime()) && d.toISOString().slice(0, 10) === v ? v : null;
}
const obj = (v: unknown): Record<string, unknown> => v && typeof v === 'object' && !Array.isArray(v) ? v as Record<string, unknown> : {};
const list = (v: unknown): unknown[] => Array.isArray(v) ? v : [];

export function parseClassification(input: unknown, meta: ResultMeta): Classification {
  const i = obj(input);
  const kind = (IMAGE_KINDS as readonly unknown[]).includes(i.kind) ? i.kind as ImageKind : 'unknown';
  return {kind, kind_confidence: clamp01(i.kind_confidence), has_person: bool(i.has_person), person_confidence: clamp01(i.person_confidence),
    has_fish: bool(i.has_fish), text_present: bool(i.text_present), nsfw: bool(i.nsfw), ...meta};
}

export const MAX_BOARD_LINES = 40;
export function parseCountBoard(input: unknown, meta: ResultMeta): CountBoardReading {
  const i = obj(input);
  const lines = list(i.lines).flatMap(raw => {
    const l = obj(raw), label = str(l.label, 60);
    return label ? [{label, count: int(l.count, 100000), released: int(l.released, 100000), confidence: clamp01(l.confidence)}] : [];
  }).slice(0, MAX_BOARD_LINES);
  return {boat_name: str(i.boat_name, 80), date_text: str(i.date_text, 40), date_iso: isoDate(i.date_iso), date_confidence: clamp01(i.date_confidence),
    trip_type: str(i.trip_type, 40), anglers: int(i.anglers, 1000), lines, notes: str(i.notes, 300), overall_confidence: clamp01(i.overall_confidence), ...meta};
}

const REASON = /^[a-z_]{1,24}$/;
export function parseFishId(input: unknown, allowed: ReadonlySet<string>, meta: ResultMeta): FishId {
  const i = obj(input);
  const candidates = list(i.candidates).flatMap(raw => {
    const c = obj(raw), key = typeof c.species_key === 'string' && allowed.has(c.species_key) ? c.species_key : null;
    const label = str(c.label, 60) ?? (typeof c.species_key === 'string' ? str(c.species_key, 60) : null);
    if (!label) return [];
    return [{species_key: key, label, confidence: clamp01(c.confidence), cues: list(c.cues).flatMap(q => { const s = str(q, 80); return s ? [s] : []; }).slice(0, 3)}];
  }).sort((a, b) => b.confidence - a.confidence).slice(0, 3);
  const needs = bool(i.needs_better_photo) || candidates.length === 0;
  const reason = typeof i.reason === 'string' && REASON.test(i.reason) ? i.reason : needs ? (candidates.length ? 'other' : 'no_fish') : null;
  return {candidates, needs_better_photo: needs, reason, ...meta};
}
