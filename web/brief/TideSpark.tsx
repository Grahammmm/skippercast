// The brief's tide sparkline (FE-33, design § 10): the day's station curve
// from the FE-31 model drawn by packages/coast `chart()` in mini mode through
// CoastMarkup, with night shading and the cursor at the brief's hour, and the
// day's high and low predictions listed under it with the reference level.
// A drag on the curve moves the hour, as on the Conditions chart. With fewer
// than two curve points (no local coast report binds the place, or the day
// is outside the curve) it says "Tide series unavailable" and still lists
// the events. The trend is the tide tile's (web/tides.ts).
import {CoastMarkup} from '../app/CoastMarkup.tsx';
import {zone} from '../app/App.tsx';
import {selectHour} from '../app/TimeDock.tsx';
import {hour} from '../state.ts';
import {sparkArgs, TIDE_UNAVAILABLE} from '../tides.ts';
import type {Brief} from './types.ts';

const clock = (iso: string, tz: string) => new Intl.DateTimeFormat('en-US', {hour: 'numeric', minute: '2-digit', timeZone: tz}).format(new Date(iso)).toLowerCase();

/** The time the brief is read at: the chosen hour, else now (Brief.tsx briefFrom's pivot). */
export function sparkAt(chosen: string | null, now: Date): string {
  return chosen && Number.isFinite(Date.parse(chosen)) ? new Date(chosen).toISOString() : now.toISOString();
}

export function TideSpark({brief, now = new Date()}: {brief: Brief | null; now?: Date}) {
  const tz = zone();
  const args = brief ? sparkArgs(brief, sparkAt(hour.value, now), tz) : null;
  return (
    <figure class="app-spark" aria-label="Tide curve">
      {args ? <CoastMarkup renderer="chart" args={args} onCursor={at => selectHour(now, tz, Date.parse(at))} />
        : <span class="app-spark-empty">{brief ? TIDE_UNAVAILABLE : '—'}</span>}
      {brief?.tideEvents.length ? (
        <figcaption>
          <ul class="app-spark-events">
            {brief.tideEvents.map(e => <li key={e.at}>{e.type === 'H' ? 'High' : 'Low'} <span class="ui-mono">{clock(e.at, tz)} · {e.heightFt.toFixed(1)} ft {brief.tideDatum}</span></li>)}
          </ul>
        </figcaption>
      ) : null}
    </figure>
  );
}
