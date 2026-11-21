import type {SshFrames} from './ssh-reading.ts';
import {sshScale} from './ssh-scale.ts';

export function sshDockScale(
  f: SshFrames, validAt: string,
): {validAt: string; limitCm: number; ticks: readonly number[]} | {none: 'no-frame' | 'no-values'} {
  let frame: SshFrames['frames'][number] | undefined;
  try {
    const instant = Date.parse(validAt);
    const frames = f.frames;
    if (Number.isNaN(instant) || !Array.isArray(frames)) return {none: 'no-frame'};
    frame = frames.find(candidate => Date.parse(candidate.validAt) === instant);
  } catch {
    return {none: 'no-frame'};
  }
  if (!frame) return {none: 'no-frame'};

  try {
    const scale = sshScale(frame.cells.map(c => c.sshCm));
    return scale ? {validAt: frame.validAt, ...scale} : {none: 'no-values'};
  } catch {
    return {none: 'no-values'};
  }
}
