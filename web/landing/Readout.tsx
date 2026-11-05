// Readout strip (FE-07, design § 7, D4, D9): the brief's stat tiles at a
// smaller size for wind, swell, water and tide, each with its source, age,
// stale state and basis; the feed's own clock beside a link to the app's
// Conditions view for the hour-by-hour detail; and the fleet line, drawn only
// when the page is given one (the fleet flag is on and a public fleet summary
// exists). Readings come from readings.ts; nothing is shown before they load.
// The strip names the region it reads ("Morro Bay & Avila area", from its
// region.json name), not the visitor's launch: the landing reads the default
// region until it follows the port input.
import {Tile, type TileHue} from '../ui/Tile.tsx';
import {language, t} from './i18n.ts';
import type {IconName} from '../ui/icons.tsx';
import {DEFAULT_PLACE, placeLabel} from './place.ts';
import type {Readout as Data, ReadingId} from './readings.ts';

const LOOK: Readonly<Record<ReadingId, {hue: TileHue; icon: IconName}>> = {
  wind: {hue: 'mint', icon: 'wind'}, swell: {hue: 'blue', icon: 'wave'}, water: {hue: 'coral', icon: 'temperature'}, tide: {hue: 'amber', icon: 'tide'},
};

export function Readout({data, fleet, conditions}: {data: Data | null; fleet?: string | null; /** The app's Conditions view for the region. */ conditions?: string}) {
  const lang = language.value, place = data?.place ?? DEFAULT_PLACE;
  return (
    <section class="landing-readout" aria-labelledby="landing-readout-title" aria-busy={data ? undefined : 'true'}>
      <h2 id="landing-readout-title" class="landing-readout-title ui-eyebrow">{t('landing.readout.title', lang, {place: lang === 'es' ? place.trim() : placeLabel(place)})}</h2>
      <ul class="landing-tiles">
        {data ? data.readings.map(r => (
          <li key={r.id} data-reading={r.id}>
            <Tile label={r.label} icon={LOOK[r.id].icon} hue={LOOK[r.id].hue} reading={r.reading} unit={r.unit} detail={r.detail}
              source={r.source} stale={r.stale} basis={r.basis} class="landing-tile" />
          </li>
        )) : <li class="landing-tiles-wait ui-eyebrow">{t('landing.readout.wait', lang)}</li>}
      </ul>
      <div class="landing-readout-foot">
        <p class="landing-fresh ui-eyebrow" data-state={!data ? 'unknown' : data.feed.stale ? 'stale' : 'ok'}>
          {!data ? t('landing.readout.checking', lang) : data.feed.age === null ? t('landing.readout.feedMissing', lang) : t(data.feed.stale ? 'landing.readout.feedStale' : 'landing.readout.feedFresh', lang, {age: data.feed.age})}
        </p>
        {conditions ? <a class="landing-more" href={conditions}>{t('landing.readout.more', lang)}</a> : null}
      </div>
      {fleet ? <p class="landing-fleet" data-fleet="true">{fleet}</p> : null}
    </section>
  );
}
