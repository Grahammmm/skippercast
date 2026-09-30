// The spot sheet's confidence row (P4-04): the spot's badges (depth, terrain,
// fish) and its nearshore buoy's freshness pill, under the spot's name and
// answer line. app.js draws the sheet and sets spotConfidence; islands.tsx
// mounts this into #spot-confidence.
import type {Badge, Observation} from '../confidence.ts';
import {buoyObservations} from '../views.ts';
import {ConfidenceBadge} from './ConfidenceBadge.tsx';
import {FreshnessPill} from './FreshnessPill.tsx';

export function SpotConfidence({badges, buoy, observations}: {
  badges: Badge[];
  /** The spot's nearshore buoy (NDBC station id); null shows "Buoy unavailable". */
  buoy: string | null;
  observations?: Readonly<Record<string, Observation>>;
}) {
  const latest = observations ?? buoyObservations.value;
  // Only the spot's own buoy: a reading from another station is never shown in its place.
  const observation = buoy ? latest[buoy] ?? null : null;
  return (
    <>
      {badges.map(({id, open, ...badge}) => <ConfidenceBadge key={id} {...badge} defaultOpen={open} />)}
      <FreshnessPill observation={observation} />
    </>
  );
}
