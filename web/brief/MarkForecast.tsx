// The mark card's forecast (BP CI6-06): wind, seas and surface current at a
// reef mark or a ranked trip spot for the dock's hour, from the regional
// forecast the brief loads (web/brief/mark-forecast.ts has the rules). A
// gridded region reads each model at the sampled cell nearest the mark and
// names the model, its grid and that cell's distance. A region with only named
// points says so and shows the regional point's values, named. NOAA and ECMWF
// keep their own rows. A gap reads "—" with its reason.
import {useEffect} from 'preact/hooks';
import {regionInfo, zone} from '../app/App.tsx';
import {dockState} from '../app/TimeDock.tsx';
import {Popover} from '../ui/Popover.tsx';
import {ensureRegionalForecast, regionalForecast} from './Brief.tsx';
import {CELL_REACH, hourText, markForecast, readingSource, type LatLon, type MarkReading} from './mark-forecast.ts';

const BASIS_GRID = `Model forecasts from the regional forecast feed, read at the sampled model cell nearest this mark; a cell more than ${CELL_REACH} grid lengths away is left blank. `
  + 'Each value is a model grid cell, never a measurement at the mark. The two model families keep their own rows and are never averaged. '
  + 'A run older than 36 hours, a feed retrieved over 6 hours ago or a missing value leaves a gap.';
const BASIS_POINTS = 'This region\'s forecast feed samples a few named points, so the values are the regional point\'s, the same point the brief reads. '
  + 'The two model families keep their own rows and are never averaged. A run older than 36 hours, a feed retrieved over 6 hours ago or a missing value leaves a gap.';

function Row({name, r, at, tz}: {name: string; r: MarkReading; at: number; tz: string}) {
  return (
    <div data-gap={r.value === null ? 'true' : undefined}>
      <dt>{name}</dt>
      <dd class="ui-mono">{r.value ?? '—'}</dd>
      <dd class="app-mark-forecast-source">{r.value === null ? `Gap: ${r.gap}.` : readingSource(r, at, tz)}</dd>
    </div>
  );
}

/** The forecast block for a mark at `place`; nothing until the region is known. */
export function MarkForecast({place, now = new Date()}: {place: LatLon; now?: Date}) {
  const info = regionInfo.value, id = info?.id ?? null;
  useEffect(() => { if (info) void ensureRegionalForecast(info.id, info.center); }, [id]);
  if (!info) return null;
  const tz = zone(), at = dockState(now, tz).at, f = markForecast(regionalForecast.value, info.id, place, at, now.getTime(), tz);
  return (
    <section class="app-mark-forecast" aria-label="Forecast at this mark">
      <p class="app-mark-forecast-head"><span class="ui-eyebrow">{f?.kind === 'points' ? 'Regional forecast' : 'Forecast here'}</span> <span class="ui-mono">valid {hourText(at, tz)}</span></p>
      {!f ? <p class="app-mark-forecast-note">The regional forecast has not loaded, so these rows are empty.</p> : (
        <>
          {f.kind === 'points'
            ? <p class="app-mark-forecast-note">This region's forecast is a few named points, with no grid to sample at this mark. Values at forecast point {f.point}.</p>
            : null}
          <dl>
            {f.families.flatMap(family => family.rows.map(r => <Row key={`${family.family}-${r.label}`} name={`${family.label} ${r.label.toLowerCase()}`} r={r} at={at} tz={tz} />))}
            <Row name="Surface current" r={f.current} at={at} tz={tz} />
          </dl>
          <Popover>{f.kind === 'points' ? BASIS_POINTS : BASIS_GRID}</Popover>
        </>
      )}
    </section>
  );
}
