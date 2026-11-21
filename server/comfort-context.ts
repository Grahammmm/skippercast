type Phase = 'outbound' | 'fishing' | 'return';

export type ComfortContext = {
  phase: Phase;
  wind: number | null;
  sea: number | null;
  period: number | null;
  heading: number | null;
  point: string | null;
  boat: string | null;
  swell_from: number | null;
};

type ContextResult =
  | {ok: true; context: ComfortContext}
  | {ok: false; error: 'invalid feedback' | 'invalid feedback context' | 'invalid feedback point'};
type ContextInput = Record<string, unknown> & {phase: Phase};

const limits = {wind: 200, sea: 100, period: 60, heading: 360, swell_from: 360};
const numericKeys = ['wind', 'sea', 'period', 'heading', 'swell_from'] as const;

function hasPhase(value: unknown): value is ContextInput {
  if (typeof value !== 'object' || value === null || Array.isArray(value) || !('phase' in value)) return false;
  return value.phase === 'outbound' || value.phase === 'fishing' || value.phase === 'return';
}

function numberInRange(value: unknown, max: number): number | null {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0 && value <= max ? value : null;
}

// Undefined means invalid; null means the name was absent or blank.
function boatName(value: unknown): string | null | undefined {
  if (value == null) return null;
  if (typeof value !== 'string') return undefined;
  const trimmed = value.trim();
  return trimmed.length <= 80 ? trimmed || null : undefined;
}

function project(b: ContextInput, boat: string | null): ComfortContext {
  return {
    phase: b.phase,
    wind: numberInRange(b.wind, limits.wind),
    sea: numberInRange(b.sea, limits.sea),
    period: numberInRange(b.period, limits.period),
    heading: numberInRange(b.heading, limits.heading),
    point: typeof b.point === 'string' ? b.point : null,
    boat,
    swell_from: numberInRange(b.swell_from, limits.swell_from),
  };
}

export function comfortContext(b: unknown, forecastPoints: readonly string[]): ContextResult {
  if (!hasPhase(b)) return {ok: false, error: 'invalid feedback'};
  const boat = boatName(b.boat);
  if (boat === undefined) return {ok: false, error: 'invalid feedback context'};
  const context = project(b, boat);
  if (numericKeys.some(key => b[key] != null && context[key] === null)) {
    return {ok: false, error: 'invalid feedback context'};
  }
  if (b.point != null && (context.point === null || !forecastPoints.includes(context.point))) {
    return {ok: false, error: 'invalid feedback point'};
  }
  return {ok: true, context};
}

export function readComfortContext(json: string): ComfortContext | null {
  let b: unknown;
  try {
    b = JSON.parse(json);
  } catch {
    return null;
  }
  return hasPhase(b) ? project(b, boatName(b.boat) ?? null) : null;
}
