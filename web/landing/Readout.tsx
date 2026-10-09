// Readout strip (FE-07, design § 7, D4, D9): the brief's stat tiles at a
// smaller size for wind, swell, water and tide, each with its source, age,
// stale state and basis; the feed's own clock beside a link to the app's
// Conditions view for the hour-by-hour detail; and the fleet line, drawn only
// when the page is given one (the fleet flag is on and a public fleet summary
// exists). Readings come from readings.ts; nothing is shown before they load.
// The strip names the region it reads ("Morro Bay area"), not the visitor's
// launch: the landing reads the default region until it follows the port input.
import {Tile, type TileHue} from '../ui/Tile.tsx';
import type {IconName} from '../ui/icons.tsx';
import {DEFAULT_PLACE, type Readout as Data, type ReadingId} from './readings.ts';

const LOOK: Readonly<Record<ReadingId, {hue: TileHue; icon: IconName}>> = {
  wind: {hue: 'mint', icon: 'wind'}, swell: {hue: 'blue', icon: 'wave'}, water: {hue: 'coral', icon: 'temperature'}, tide: {hue: 'amber', icon: 'tide'},
};

export function Readout({data, fleet, conditions}: {data: Data | null; fleet?: string | null; /** The app's Conditions view for the region. */ conditions?: string}) {
  return (
    <section class="landing-readout" aria-labelledby="landing-readout-title" aria-busy={data ? undefined : 'true'}>
      <h2 id="landing-readout-title" class="landing-readout-title ui-eyebrow">Latest readings · {data?.place ?? DEFAULT_PLACE} area</h2>
      <ul class="landing-tiles">
        {data ? data.readings.map(r => (
          <li key={r.id} data-reading={r.id}>
            <Tile label={r.label} icon={LOOK[r.id].icon} hue={LOOK[r.id].hue} reading={r.reading} unit={r.unit} detail={r.detail}
              source={r.source} stale={r.stale} basis={r.basis} class="landing-tile" />
          </li>
        )) : <li class="landing-tiles-wait ui-eyebrow">Loading the latest readings…</li>}
      </ul>
      <div class="landing-readout-foot">
        <p class="landing-fresh ui-eyebrow" data-state={!data ? 'unknown' : data.feed.stale ? 'stale' : 'ok'}>
          {!data ? 'Checking the buoys' : data.feed.age === null ? 'Buoy feed unavailable' : `Buoy feed ${data.feed.stale ? 'stale, ' : ''}updated ${data.feed.age} ago`}
        </p>
        {conditions ? <a class="landing-more" href={conditions}>Hour by hour on the map</a> : null}
      </div>
      {fleet ? <p class="landing-fleet" data-fleet="true">{fleet}</p> : null}
    </section>
  );
}
