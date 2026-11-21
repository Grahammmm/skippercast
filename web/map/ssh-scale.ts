export const SSH_MIN_LIMIT_CM = 5;
export const SSH_STEP_CM = 5;

export function sshScale(values: Iterable<number>): {limitCm: number; ticks: readonly number[]} | null {
  let maxAbs = -Infinity;
  for (const value of values) {
    if (Number.isFinite(value)) maxAbs = Math.max(maxAbs, Math.abs(value));
  }
  if (maxAbs === -Infinity) return null;

  const limitCm = Math.max(SSH_MIN_LIMIT_CM, Math.ceil(maxAbs / SSH_STEP_CM) * SSH_STEP_CM);
  const half = limitCm / 2;
  return {limitCm, ticks: [-limitCm, -half, 0, half, limitCm]};
}

function validInput(value: number, limitCm: number): boolean {
  return Number.isFinite(value) && Number.isFinite(limitCm) && limitCm > 0;
}

export function sshPosition(value: number, limitCm: number): number | null {
  if (!validInput(value, limitCm)) return null;
  const width = 2 * limitCm;
  // Divide through by the limit first if doubling it overflows.
  const position = Number.isFinite(width) ? (value + limitCm) / width : (value / limitCm + 1) / 2;
  return Math.max(0, Math.min(1, position));
}

export function sshOutside(value: number, limitCm: number): 'below' | 'above' | null {
  if (!validInput(value, limitCm)) return null;
  if (value < -limitCm) return 'below';
  if (value > limitCm) return 'above';
  return null;
}
