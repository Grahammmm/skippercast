import type {SshReading} from './ssh-reading.ts';
import {sshOutside, sshPosition} from './ssh-scale.ts';

export function sshTapPosition(reading: SshReading, limitCm: number):
  | {kind: 'value'; sshCm: number; position: number; outside: 'below' | 'above' | null}
  | {kind: 'none'; reason: string} {
  if (reading.kind === 'none') return {kind: 'none', reason: reading.reason};

  const {sshCm} = reading;
  const position = sshPosition(sshCm, limitCm);
  if (position === null) return {kind: 'none', reason: 'bad-scale'};
  return {kind: 'value', sshCm, position, outside: sshOutside(sshCm, limitCm)};
}
