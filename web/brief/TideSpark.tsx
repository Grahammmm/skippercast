// The brief's tide sparkline (FE-33, design § 10): the day's station curve
// from the FE-31 model drawn by packages/coast `chart()` in mini mode through
// CoastMarkup, with night shading and the cursor at the brief's hour, and the
// day's high and low predictions listed under it with the reference level.
// A drag on the curve moves the hour, as on the Conditions chart. With fewer
// than two curve points (no local coast report binds the place, or the day
// is outside the curve) it still lists the events and says there is no curve
// for this place (TIDE_NO_CURVE), or "Tide series unavailable" with no events. The trend is the tide tile's (web/tides.ts).
// Its words and the events' clock follow the chosen language (SC1137-03); heights, datum and instants stay as published.
import {CoastMarkup} from '../app/CoastMarkup.tsx';
import {zone} from '../app/region-info.ts';
import {selectHour} from '../app/TimeDock.tsx';
import {language, t} from '../i18n.ts';
import {hour} from '../state.ts';
import {sparkArgs} from '../tides.ts';
import {eventClock} from './tide-copy.ts';
import {tideEmptyText} from './tile-copy.ts';
import type {Brief} from './types.ts';

/** The time the brief is read at: the chosen hour, else now (Brief.tsx briefFrom's pivot). */
export function sparkAt(chosen: string | null, now: Date): string {
  return chosen && Number.isFinite(Date.parse(chosen)) ? new Date(chosen).toISOString() : now.toISOString();
}

export function TideSpark({brief, now = new Date()}: {brief: Brief | null; now?: Date}) {
  const tz = zone(), lang = language.value;
  const built = brief ? sparkArgs(brief, sparkAt(hour.value, now), tz) : null;
  // Only the row's label is said in the chosen language; the series, colours, gaps and geometry are the model's.
  const args = built && lang !== 'en' ? [built[0].map(row => ({...row, label: t('tile.tide', lang)})), built[1], built[2], built[3], built[4], built[5]] as typeof built : built;
  return (
    <figure class="app-spark" aria-label={t('tideSpark.aria', lang)}>
      {args ? <CoastMarkup renderer="chart" args={args} onCursor={at => selectHour(now, tz, Date.parse(at))} />
        : <span class="app-spark-empty">{brief ? tideEmptyText(brief.tideEvents.length ? 'noCurve' : 'unavailable', lang) : '—'}</span>}
      {brief?.tideEvents.length ? (
        <figcaption>
          <ul class="app-spark-events">
            {brief.tideEvents.map(e => <li key={e.at}>{t(e.type === 'H' ? 'tideSpark.high' : 'tideSpark.low', lang)} <span class="ui-mono">{eventClock(e.at, tz, lang)} · {e.heightFt.toFixed(1)} ft {brief.tideDatum}</span></li>)}
          </ul>
        </figcaption>
      ) : null}
    </figure>
  );
}
