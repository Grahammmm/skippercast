import {verdictFor, type Verdict} from '../score.ts';

export const ROSE_SIZE = 120;
export const ROSE_CENTRE = ROSE_SIZE / 2;
export const ROSE_COURSES = [0, 45, 90, 135, 180, 225, 270, 315] as const;

const HALF_WEDGE = 22.5;
const DEFAULT_RADIUS = 54;
const RAD = Math.PI / 180;

type SectorScore = {course: number; score: number | null};
type RunBearings = {out: number | null; back: number | null};

function validateScores(scores: readonly SectorScore[]): void {
  if (scores.length !== ROSE_COURSES.length || ROSE_COURSES.some((course, i) => scores[i]?.course !== course)) {
    throw new RangeError('Expected one score per rose course, in compass order');
  }
}

const round = (value: number): number => Math.round(value * 100) / 100 + 0;

function tip(bearing: number, radius: number): {x: number; y: number} {
  const angle = bearing * RAD;
  return {
    x: round(ROSE_CENTRE + radius * Math.sin(angle)),
    y: round(ROSE_CENTRE - radius * Math.cos(angle)),
  };
}

function normalise(bearing: number | null): number | null {
  if (bearing === null || !Number.isFinite(bearing)) return null;
  const remainder = bearing % 360;
  // Only add 360 to negative remainders so positive fractional bearings keep their precision.
  return remainder < 0 ? (remainder + 360) % 360 : remainder + 0;
}

export function roseWedges(scores: readonly SectorScore[], radius = DEFAULT_RADIUS): {course: number; verdict: Verdict; d: string}[] {
  validateScores(scores);
  if (!Number.isFinite(radius) || radius <= 0 || radius > ROSE_CENTRE) {
    throw new RangeError('Rose radius must be finite and within (0, 60]');
  }
  const r = String(round(radius));
  return scores.map(({course, score}) => {
    const start = tip(course - HALF_WEDGE, radius);
    const end = tip(course + HALF_WEDGE, radius);
    return {
      course,
      verdict: verdictFor({conditions: score}),
      d: `M${ROSE_CENTRE} ${ROSE_CENTRE} L${start.x} ${start.y} A${r} ${r} 0 0 1 ${end.x} ${end.y} Z`,
    };
  });
}

export function roseArrow(bearing: number | null, radius = DEFAULT_RADIUS): {bearing: number; x: number; y: number} | null {
  const angle = normalise(bearing);
  return angle === null ? null : {bearing: angle, ...tip(angle, radius)};
}

function markedCourse(bearing: number | null): number | null {
  const angle = normalise(bearing);
  if (angle === null) return null;
  // The first upper edge strictly above the angle owns it; north also wraps past the last edge.
  return ROSE_COURSES.find(course => angle < course + HALF_WEDGE) ?? 0;
}

export function roseRows(scores: readonly SectorScore[], bearings: RunBearings): {course: number; verdict: Verdict; score: number | null; out: boolean; back: boolean}[] {
  validateScores(scores);
  const out = markedCourse(bearings.out);
  const back = markedCourse(bearings.back);
  return scores.map(({course, score}) => ({
    course,
    verdict: verdictFor({conditions: score}),
    score,
    out: course === out,
    back: course === back,
  }));
}
