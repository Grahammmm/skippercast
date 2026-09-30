// The spot sheet's confidence row (P4-04): the spot's badges (depth, terrain,
// fish) and the nearshore buoy's freshness pill, under the spot's name and
// answer line. app.js draws the sheet and sets spotConfidence; islands.tsx
// mounts this into #spot-confidence.
import {freshnessPill, type Badge, type Reading} from '../confidence.ts';
import {buoyReadingStatus} from '../views.ts';
import {ConfidenceBadge} from './ConfidenceBadge.tsx';
import {FreshnessPill} from './FreshnessPill.tsx';

export function SpotConfidence({badges, buoy}: {badges: Badge[]; buoy?: Reading | null}) {
  const reading = buoy === undefined ? buoyReadingStatus.value : buoy;
  return (
    <>
      {badges.map(({id, ...badge}) => <ConfidenceBadge key={id} {...badge} />)}
      {reading ? <FreshnessPill {...freshnessPill(reading)} /> : null}
    </>
  );
}
