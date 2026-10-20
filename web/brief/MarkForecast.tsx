// The mark card's forecast (BP CI6-06): wind, seas and surface current for a
// reef mark or a ranked trip spot at the dock's hour, from the regional
// forecast the brief loads (web/brief/mark-forecast.ts has the rules). Model
// wind and seas are point series in every region, so the block says so and
// shows them at the regional point, named. The WCOFS surface current reads the
// sampled ocean cell nearest the mark, with its distance, when one is in
// reach. NOAA and ECMWF keep their own rows. A gap reads "—" with its reason.
import {useEffect} from 'preact/hooks';
import {regionInfo, zone} from '../app/App.tsx';
import {dockState} from '../app/TimeDock.tsx';
import {Popover} from '../ui/Popover.tsx';
import {ensureRegionalForecast, regionalForecast} from './Brief.tsx';
import {CELL_REACH, hourText, markForecast, readingSource, type LatLon, type MarkReading} from './mark-forecast.ts';

const basis = (point: string) => 'The regional forecast feed carries model wind and seas as series interpolated at a few named points, '
  + `so those rows are forecast point ${point}'s values, the point the brief reads, not values at this mark or at a model cell. `
  + `The NOAA WCOFS surface current is published as ocean-cell samples: the row reads the sampled cell nearest this mark when one lies within ${CELL_REACH} grid lengths, `
  + `otherwise forecast point ${point}'s sample. The two model families keep their own rows and are never averaged. `
  + 'A run older than 36 hours, a feed retrieved over 6 hours ago or a missing value leaves a gap.';

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
      <p class="app-mark-forecast-head"><span class="ui-eyebrow">Regional forecast</span> <span class="ui-mono">valid {hourText(at, tz)}</span></p>
      {!f ? <p class="app-mark-forecast-note">The regional forecast has not loaded, so these rows are empty.</p> : (
        <>
          <p class="app-mark-forecast-note">This region's wind and seas forecast is a few named points, with no model grid to sample at this mark. Wind and seas at forecast point {f.point}.</p>
          <dl>
            {f.families.flatMap(family => family.rows.map(r => <Row key={`${family.family}-${r.label}`} name={`${family.label} ${r.label.toLowerCase()}`} r={r} at={at} tz={tz} />))}
            <Row name="Surface current" r={f.current} at={at} tz={tz} />
          </dl>
          <Popover>{basis(f.point)}</Popover>
        </>
      )}
    </section>
  );
}
