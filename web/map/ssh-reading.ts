import {cellIndex, sampleAt, type HabitatCellIndex} from './habitat-sample.ts';

export type SshFrames = {
  product: string;
  issuedAt: string;
  resolution: readonly [number, number];
  frames: readonly {validAt: string; cells: readonly {lat: number; lon: number; sshCm: number}[]}[];
};

export type SshReading =
  | {kind: 'value'; sshCm: number; validAt: string; issuedAt: string; product: string; cell: {lat: number; lon: number}}
  | {kind: 'none'; reason: 'no-frame' | 'gap' | 'outside' | 'bad-grid'};

const fields = ['latitude', 'longitude', 'ssh_cm'] as const;

export function sshReader(f: SshFrames): (at: {lat: number; lon: number}, validAt: string) => SshReading {
  const {product, issuedAt, resolution} = f;
  const byInstant = new Map<number, {validAt: string; index: HabitatCellIndex | null}>();
  for (const frame of f.frames) {
    const {validAt} = frame;
    let index: HabitatCellIndex | null = null;
    try {
      index = cellIndex(frame.cells.map(({lat, lon, sshCm}) => [lat, lon, sshCm]), resolution, fields, 'ssh_cm');
    } catch {
      // Keep the failed frame selectable without affecting its neighbours.
    }
    const instant = Date.parse(validAt);
    if (!byInstant.has(instant)) byInstant.set(instant, {validAt, index});
  }

  return (at, validAt) => {
    const instant = Date.parse(validAt);
    const frame = Number.isNaN(instant) ? undefined : byInstant.get(instant);
    if (!frame) return {kind: 'none', reason: 'no-frame'};
    if (!frame.index) return {kind: 'none', reason: 'bad-grid'};
    try {
      const sample = sampleAt(frame.index, at.lat, at.lon);
      if ('reason' in sample) return {kind: 'none', reason: sample.reason};
      if (sample.value === null) return {kind: 'none', reason: 'gap'};
      return {kind: 'value', sshCm: sample.value, validAt: frame.validAt, issuedAt, product, cell: {...sample.cell}};
    } catch {
      return {kind: 'none', reason: 'bad-grid'};
    }
  };
}
