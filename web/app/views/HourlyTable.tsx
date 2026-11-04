// Hour by hour (BF-hourly-table): web/hourly-table.ts's rows for the dock's
// day, below the Conditions chart. The dock's hour is the current row
// (aria-current), kept in view inside the table's own scroll box, so the page
// never jumps; scrolling is instant, never smooth. Each row's time is a button
// that moves the dock (and so the chart cursor and the map) to that hour.
import {useEffect, useRef} from 'preact/hooks';
import {activeBoatFactors} from '../../../dist/boat-handling.js';
import type {Series} from '../../../packages/coast/src/charts/series.ts';
import type {ConditionsForecast} from '../../conditions.ts';
import {hourlyCells, hourlyTable, LIMITED_NOTE} from '../../hourly-table.ts';
import type {BoatFactors} from '../../score.ts';
import {hourText, localParts, selectHour, zoneName} from '../TimeDock.tsx';
import './hourly-table.css';

const HEADERS = ['Wind (kt)', 'Gust (kt)', 'Seas (ft)', 'Swell (ft · s · from)', 'Chop (ft · s)', 'Tide (where a local report exists)', 'Visibility (mi)', 'Comfort score (0–10)'];

export function HourlyTable({forecast, tide, at, tz, now}: {forecast: ConditionsForecast | null; tide: Series | null; at: number; tz: string; now: Date}) {
  const box = useRef<HTMLDivElement>(null);
  const local = localParts(new Date(at), tz), {rows, note} = hourlyTable(forecast, tide, local.day, tz, now, activeBoatFactors() as BoatFactors);
  useEffect(() => {
    const el = box.current, row = el?.querySelector<HTMLElement>('tr[aria-current="true"]');
    if (!el || !row) return;
    const b = el.getBoundingClientRect(), r = row.getBoundingClientRect(), head = el.querySelector('thead')?.getBoundingClientRect().height ?? 0;
    const up = r.top - b.top - head, down = r.bottom - b.bottom;
    if (up < 0) el.scrollTop += up; else if (down > 0) el.scrollTop += down;
  }, [at, rows.length]);
  const hourOf = (ms: number) => localParts(new Date(ms), tz).hour;
  const label = (ms: number) => rows.filter(x => hourOf(x.ms) === hourOf(ms)).length > 1 ? `${hourText(hourOf(ms))} ${zoneName(new Date(ms), tz)}` : hourText(hourOf(ms));
  const caption = <caption>Hour by hour, {local.weekday}</caption>;
  if (!rows.length) return <div class="app-hourly"><table>{caption}</table><p class="app-empty">{note}</p></div>;
  return (
    <div class="app-hourly">
      <div class="app-hourly-box" ref={box} role="region" aria-label="Hour by hour table, scrolls" tabIndex={0}>
        <table>
          {caption}
          <thead><tr><th scope="col">Time</th>{HEADERS.map(h => <th key={h} scope="col">{h}</th>)}</tr></thead>
          <tbody>
            {rows.map(r => (
              <tr key={r.at} data-at={r.at} aria-current={r.ms === at ? 'true' : undefined} class={r.ms === at ? 'is-current' : undefined}>
                <th scope="row"><button type="button" onClick={() => selectHour(now, tz, r.ms)}>{label(r.ms)}</button></th>
                {hourlyCells(r).map((c, i) => <td key={i} class="ui-mono">{c}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {rows.some(r => r.limited && r.score !== null) ? <p class="app-hourly-note">* {LIMITED_NOTE}</p> : null}
    </div>
  );
}
