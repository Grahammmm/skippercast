export type Prefill = {
  phase: 'outbound' | 'fishing' | 'return' | null;
  heading: number | null;
  wind: number | null;
  sea: number | null;
  period: number | null;
};

type PrefillInput = {
  at: number;
  plan: {departAt: number; fishFrom: number; fishTo: number} | null;
  bearings: {out: number | null; back: number | null} | null;
  hour: {wind: number | null; sea: number | null; period: number | null} | null;
};

function tripPhase(at: number, plan: PrefillInput['plan']): Prefill['phase'] {
  if (plan === null) return null;
  const {departAt, fishFrom, fishTo} = plan;
  if (![at, departAt, fishFrom, fishTo].every(Number.isFinite) || departAt > fishFrom || fishFrom > fishTo) return null;
  if (at < fishFrom) return 'outbound';
  if (at < fishTo) return 'fishing';
  return 'return';
}

function hourValue(value: number | null | undefined, max: number): number | null {
  if (value == null || !Number.isFinite(value) || value < 0 || value > max) return null;
  return Math.round(value * 10) / 10;
}

// Prepare editable defaults for POST /api/comfort without discarding partial context.
export function comfortPrefill({at, plan, bearings, hour}: PrefillInput): Prefill {
  const phase = tripPhase(at, plan);
  const bearing = phase === 'outbound' ? bearings?.out : phase === 'return' ? bearings?.back : null;
  const heading = bearing != null && Number.isFinite(bearing)
    ? ((Math.round(bearing) % 360) + 360) % 360
    : null;
  return {
    phase,
    heading,
    wind: hourValue(hour?.wind, 200),
    sea: hourValue(hour?.sea, 100),
    period: hourValue(hour?.period, 60),
  };
}
