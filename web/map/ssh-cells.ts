import type {SshFrames} from './ssh-reading.ts';
import {sshPosition, sshScale} from './ssh-scale.ts';

export type SshCellFeature = {
  type: 'Feature';
  geometry: {type: 'Polygon'; coordinates: [number, number][][]};
  properties: {sshCm: number; pos: ReturnType<typeof sshPosition>};
};

export type SshCells =
  | {state: 'none'; reason: 'bad-time' | 'no-frame' | 'bad-grid' | 'no-cells'}
  | {
    state: 'ready';
    validAt: string;
    limitCm: number;
    ticks: readonly number[];
    features: {type: 'FeatureCollection'; features: SshCellFeature[]};
  };

export function sshCells(frames: SshFrames, validAt: string): SshCells {
  const instant = Date.parse(validAt);
  if (Number.isNaN(instant)) return {state: 'none', reason: 'bad-time'};
  const frame = frames.frames.find(frame => Date.parse(frame.validAt) === instant);
  if (!frame) return {state: 'none', reason: 'no-frame'};

  const {resolution} = frames;
  if (!Array.isArray(resolution) || resolution.length !== 2) return {state: 'none', reason: 'bad-grid'};
  const [dLat, dLon] = resolution;
  if (!Number.isFinite(dLat) || dLat <= 0 || !Number.isFinite(dLon) || dLon <= 0) {
    return {state: 'none', reason: 'bad-grid'};
  }

  const cells = frame.cells.filter(({lat, lon, sshCm}) =>
    Number.isFinite(lat) && Number.isFinite(lon) && Number.isFinite(sshCm));
  const scale = sshScale(cells.map(cell => cell.sshCm));
  if (!scale) return {state: 'none', reason: 'no-cells'};

  const {limitCm, ticks} = scale;
  const features = cells.map(({lat, lon, sshCm}): SshCellFeature => {
    const s = lat - dLat / 2, n = lat + dLat / 2;
    const w = lon - dLon / 2, e = lon + dLon / 2;
    return {
      type: 'Feature',
      geometry: {type: 'Polygon', coordinates: [[[w, s], [e, s], [e, n], [w, n], [w, s]]]},
      properties: {sshCm, pos: sshPosition(sshCm, limitCm)},
    };
  });

  return {state: 'ready', validAt: frame.validAt, limitCm, ticks, features: {type: 'FeatureCollection', features}};
}
