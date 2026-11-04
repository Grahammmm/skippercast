// The evidence ladder (docs/evidence-ladder.md): every statement that a charter boat spent time somewhere
// carries one named rung, its evidence count and the coverage caveat of its source. A rung is never set
// directly: `reportClaim` and `aisClaim` are the only ways to get a Claim, and each builds the rung from
// the evidence it was given (zero evidence returns null, so no claim exists). A report's place stays the
// polygon it was reported as: nothing here computes a point, centroid or representative position.
//
// Erasable syntax only: Node tests import this file by type stripping.

/** In increasing strength. A rung is an enum value, not prose. */
export const RUNGS = ['named-report', 'repeated-report', 'ais-linger', 'ais-linger-verified'] as const;
export type Rung = typeof RUNGS[number];

export const CAVEATS: Readonly<Record<Rung, string>> = Object.freeze({
  'named-report': 'One named human report. Reports cover only the boats and days someone wrote up, and say where in words or as an area, never a position. No report is not evidence of no trip.',
  'repeated-report': 'Two or more independent named reports. Reports cover only the boats and days someone wrote up, and give an area, never a position. No report is not evidence of no trip.',
  'ais-linger': 'Apparent fishing effort inferred from AIS speed and track shape. AIS covers small vessels poorly, so no AIS linger is not evidence of no fishing. The boat\'s identity is not confirmed in the registry.',
  'ais-linger-verified': 'Apparent fishing effort inferred from AIS speed and track shape, on a boat whose identity is confirmed in the registry. AIS covers small vessels poorly, so no AIS linger is not evidence of no fishing.',
});

/** A report's area as it was reported: a GeoJSON Polygon or MultiPolygon, nothing else. */
export type Area = {readonly type: 'Polygon' | 'MultiPolygon'; readonly coordinates: readonly unknown[]};
/** One named report. `source` is the publisher the text came from: reports sharing a source are one voice, not two. */
export interface ReportEvidence {source: string; area?: unknown}
/** One AIS linger (a stop the classifier kept): `dwellMin` against the region's `thresholdMin`. */
export interface LingerEvidence {dwellMin: number; thresholdMin: number}

declare const made: unique symbol;
/** No point, centroid, coordinate or heat fields exist on this type. */
export interface Claim {
  readonly rung: Rung;
  readonly count: number;
  readonly caveat: string;
  /** Only report claims, only the polygons as reported. */
  readonly areas: readonly Area[];
  readonly [made]: true;
}

const isArea = (g: unknown): g is Area => {
  const t = (g as {type?: unknown} | null)?.type, c = (g as {coordinates?: unknown} | null)?.coordinates;
  return (t === 'Polygon' || t === 'MultiPolygon') && Array.isArray(c);
};

function make(rung: Rung, count: number, areas: readonly Area[]): Claim {
  return Object.freeze({rung, count, caveat: CAVEATS[rung], areas: Object.freeze(areas)}) as unknown as Claim;
}

/** Named reports -> `named-report` (one independent source) or `repeated-report` (two or more); count is independent sources. Null for none. */
export function reportClaim(reports: readonly ReportEvidence[]): Claim | null {
  const sources = new Set<string>(), areas: Area[] = [];
  for (const r of reports) {
    if (typeof r?.source !== 'string' || !r.source.trim()) continue; // an unnamed report is not a named report
    sources.add(r.source.trim().toLowerCase());
    // A Point (or any non-area) is dropped, never kept or widened into an area.
    if (isArea(r.area)) areas.push(JSON.parse(JSON.stringify({type: r.area.type, coordinates: r.area.coordinates})) as Area);
  }
  if (!sources.size) return null;
  return make(sources.size >= 2 ? 'repeated-report' : 'named-report', sources.size, areas);
}

/** Lingers at or over their threshold -> `ais-linger`, or `ais-linger-verified` when `identityConfirmed`; count is the lingers that met it. Null for none. */
export function aisClaim(lingers: readonly LingerEvidence[], identityConfirmed: boolean): Claim | null {
  const met = lingers.filter(l => Number.isFinite(l?.dwellMin) && Number.isFinite(l?.thresholdMin) && l.dwellMin >= l.thresholdMin);
  if (!met.length) return null;
  return make(identityConfirmed === true ? 'ais-linger-verified' : 'ais-linger', met.length, []);
}

/** Persisted classifier output has already passed the processor's regional thresholds.
 * Count retained fishing segments/events (or aggregate events), never AIS positions,
 * duration totals or vessel counts. Aggregates cannot confirm a named identity. */
export function classifiedAisClaim(count: number, identityConfirmed = false): Claim | null {
  if (!Number.isSafeInteger(count) || count < 1) return null;
  return make(identityConfirmed ? 'ais-linger-verified' : 'ais-linger', count, []);
}

/** True only for a Claim these constructors made. */
export const isClaim = (v: unknown): v is Claim => !!v && typeof v === 'object' && Object.isFrozen(v)
  && RUNGS.includes((v as Claim).rung) && (v as Claim).caveat === CAVEATS[(v as Claim).rung];
