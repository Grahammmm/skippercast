export type Group = {n: number; residual: number};
type Groups = {head: Group; beam: Group; following: Group};
export type Calibration = {groups: Groups; minReports: number};

type CalibrationView =
  | {apply: false; tag: false; reason: 'off' | 'none' | 'too-few' | 'other-boat'}
  | {apply: true; tag: true; offsets: {head: number; beam: number; following: number}};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function readGroup(value: unknown): Group | null {
  if (!isRecord(value) || !Object.hasOwn(value, 'n') || !Object.hasOwn(value, 'residual')) return null;
  const {n, residual} = value;
  if (typeof n !== 'number' || !Number.isInteger(n) || n < 0) return null;
  if (typeof residual !== 'number' || !Number.isFinite(residual) || residual < -3 || residual > 3) return null;
  return {n, residual};
}

export function readCalibration(data: unknown): Calibration | null {
  try {
    if (!isRecord(data) || !Object.hasOwn(data, 'groups') || !Object.hasOwn(data, 'min_reports')) return null;
    const {groups, min_reports: minReports} = data;
    if (!isRecord(groups)) return null;
    if (!Object.hasOwn(groups, 'head') || !Object.hasOwn(groups, 'beam') || !Object.hasOwn(groups, 'following')) return null;
    if (typeof minReports !== 'number' || !Number.isInteger(minReports) || minReports < 1) return null;

    const head = readGroup(groups.head);
    const beam = readGroup(groups.beam);
    const following = readGroup(groups.following);
    if (!head || !beam || !following) return null;
    return {groups: {head, beam, following}, minReports};
  } catch {
    // Unknown input may have accessors or proxies that throw during inspection.
    return null;
  }
}

export function calibrationShown(
  cal: Calibration | null,
  choice: 'auto' | 'off',
  boat: string | null,
  calibratedBoat: string | null,
): CalibrationView {
  if (choice === 'off') return {apply: false, tag: false, reason: 'off'};
  if (cal === null) return {apply: false, tag: false, reason: 'none'};
  if (boat === null || calibratedBoat === null || boat !== calibratedBoat) {
    return {apply: false, tag: false, reason: 'other-boat'};
  }
  const {head, beam, following} = cal.groups;
  if (head.n + beam.n + following.n < cal.minReports) return {apply: false, tag: false, reason: 'too-few'};
  return {
    apply: true,
    tag: true,
    offsets: {
      head: head.n === 0 ? 0 : head.residual,
      beam: beam.n === 0 ? 0 : beam.residual,
      following: following.n === 0 ? 0 : following.residual,
    },
  };
}
