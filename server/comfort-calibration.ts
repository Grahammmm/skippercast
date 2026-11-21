export const MIN_REPORTS = 5;
export const SHRINK_K = 5;
export const CLAMP = 2;

const GROUPS = ['head', 'beam', 'following'] as const;
type Group = typeof GROUPS[number];
type CalibrationRow = {boat: string | null; group: Group | null; reported: number; model: number | null};
export type Calibration = {
  groups: Record<Group, {n: number; residual: number}>;
  min_reports: typeof MIN_REPORTS;
};

// Scale by a power of two so even a full array of finite residuals cannot overflow the sum.
const SUM_SCALE = 2 ** 32;

export function calibrationGroups(rows: readonly CalibrationRow[], boat: string): Calibration {
  const groups = {
    head: {n: 0, residual: 0},
    beam: {n: 0, residual: 0},
    following: {n: 0, residual: 0},
  };
  for (const row of rows) {
    const {group, reported, model} = row;
    if (row.boat !== boat || (group !== 'head' && group !== 'beam' && group !== 'following')) continue;
    if (!Number.isInteger(reported) || reported < 1 || reported > 10 || model === null || !Number.isFinite(model)) continue;
    groups[group].n++;
    groups[group].residual += (reported - model) / SUM_SCALE;
  }

  for (const group of GROUPS) {
    const result = groups[group];
    const {n, residual: scaledSum} = result;
    if (n < MIN_REPORTS) {
      result.residual = 0;
    } else {
      const mean = scaledSum / n * SUM_SCALE;
      const shrunk = mean * n / (n + SHRINK_K);
      const clamped = Math.max(-CLAMP, Math.min(CLAMP, shrunk));
      const rounded = Math.round(clamped * 100) / 100;
      result.residual = rounded === 0 ? 0 : rounded;
    }
  }
  return {groups, min_reports: MIN_REPORTS};
}
