import type {RegionalSsh} from './habitat-feed.ts';

export type SshStatus =
  | {state: 'loading'}
  | {state: 'none'}
  | {state: 'error'; network: boolean}
  | {state: 'withheld'; reason: 'not-current'; layerStatus: string}
  | {state: 'withheld'; reason: 'bad-time' | 'before-forecast' | 'after-forecast' | 'no-frame' | 'no-cells'}
  | {state: 'shown'; cells: number; issuedAt: string; validAt: string};

/** Project the already-gated regional feed onto the selected dock instant. */
export function sshStatus(feed: RegionalSsh | null, validAt: string): SshStatus {
  if (feed === null) return {state: 'loading'};
  if (feed.state === 'none') return feed;
  if (feed.state === 'error') return {state: 'error', network: feed.network === true};
  if (feed.state === 'listed') return {state: 'withheld', reason: 'not-current', layerStatus: feed.layerStatus};

  const selected = Date.parse(validAt);
  if (Number.isNaN(selected)) return {state: 'withheld', reason: 'bad-time'};

  let first = Infinity, last = -Infinity;
  for (const frame of feed.frames) {
    const time = Date.parse(frame.validAt);
    if (Number.isNaN(time)) continue;
    if (time === selected) {
      const cells = frame.cells.length;
      if (cells === 0) return {state: 'withheld', reason: 'no-cells'};
      return {state: 'shown', cells, issuedAt: feed.issuedAt, validAt: frame.validAt};
    }
    first = Math.min(first, time);
    last = Math.max(last, time);
  }

  if (first === Infinity) return {state: 'withheld', reason: 'no-frame'};
  if (selected < first) return {state: 'withheld', reason: 'before-forecast'};
  if (selected > last) return {state: 'withheld', reason: 'after-forecast'};
  return {state: 'withheld', reason: 'no-frame'};
}
