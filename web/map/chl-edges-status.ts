import {chlEdgesShown, type ChlEdgesFeed} from './chl-edges-feed.ts';

type ChlEdgesStatus =
  | {state: 'loading'}
  | {state: 'none'}
  | {state: 'error'}
  | {state: 'shown'; edges: number; observedPct: number | null}
  | {state: 'withheld'; reason: 'withheld-clear-water' | 'no-usable-frame' | 'no-observation' | 'stale' | 'future'; observedPct: number | null};

export function observedPercent(fraction: number | null): number | null {
  if (fraction === null) return null;
  if (fraction === 0) return 0;
  const pct = Math.floor(fraction * 100);
  if (fraction > 0 && pct === 0) return 1;
  return fraction < 1 ? Math.min(pct, 99) : pct;
}

export function chlEdgesStatus(feed: ChlEdgesFeed | null, now: Date): ChlEdgesStatus {
  if (feed === null) return {state: 'loading'};
  if (feed.state !== 'ready') return feed;
  const {doc} = feed;
  const eligibility = chlEdgesShown(doc, now);
  const observedPct = observedPercent(doc.observedFraction);
  return eligibility.show
    ? {state: 'shown', edges: doc.edges.length, observedPct}
    : {state: 'withheld', reason: eligibility.reason, observedPct};
}
