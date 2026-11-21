import type {Calibration} from './comfort-calibration-view.ts';

type SeaGroup = keyof Calibration['groups'];

export function calibrationSummary(cal: Calibration): {
  reports: number;
  group: SeaGroup | null;
  points: number;
  direction: 'rougher' | 'smoother' | null;
} {
  let reports = 0;
  let group: SeaGroup | null = null;
  let bestResidual = 0;
  // A strict comparison keeps the first group on a tie.
  for (const id of ['head', 'beam', 'following'] as const) {
    const {n, residual} = cal.groups[id];
    reports += n;
    if (n >= 1 && Math.abs(residual) > Math.abs(bestResidual)) {
      group = id;
      bestResidual = residual;
    }
  }
  if (group === null) return {reports, group: null, points: 0, direction: null};
  return {
    reports,
    group,
    points: Math.round(Math.abs(bestResidual) * 10) / 10,
    direction: bestResidual < 0 ? 'rougher' : 'smoother',
  };
}
