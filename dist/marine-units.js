// Pure marine units shared by eager UI helpers and regional forecast readers.
export const HOUR = 3600;
export function directionTo(from) {
  return Number.isFinite(from) ? (from + 180) % 360 : null;
}
