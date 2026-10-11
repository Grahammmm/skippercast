// Conditions view (FE-32, docs/plans/front-end/design.md § 10): the heading, a
// summary row for the selected hour, packages/coast `chart()` through
// CoastMarkup (rows from web/conditions.ts), a caption, each source's clock,
// the selected day's tide events and the profile's before-you-go notes. The
// chart's cursor is the store's `hour`: a drag on the chart writes it as the
// time dock does, so the map's hour moves with it. The surface-current choice
// is the Currents rail entry's own control (`?current=`), not a copy.
import {signal} from '@preact/signals';
import {useEffect, useState} from 'preact/hooks';
import {Segmented} from '../../ui/Chip.tsx';
import {currentBrief} from '../../brief/Brief.tsx';
import {coastBinding, coastReport} from '../../coast-data.ts';
import {coastRows, conditionsRows, conditionsSpan, FAMILIES, forecastRows, loadConditionsForecast, readingsAt, sourceClocks, type ConditionsForecast, type Family} from '../../conditions.ts';
import {CDFW_REGULATIONS} from '../../map/habitat.ts';
import {PROFILE_TABLE} from '../../profile.ts';
import {profile, region} from '../../state.ts';
import {regionInfo, zone} from '../App.tsx';
import {CoastMarkup} from '../CoastMarkup.tsx';
import {CurrentSource} from '../LayerRail.tsx';
import {dockState, localParts, selectHour} from '../TimeDock.tsx';

/** The region's forecast at its chosen point; null before it loads, when it fails, or for another region. */
export const conditionsForecast = signal<ConditionsForecast | null>(null);
let requested: string | null = null;

/** Load the forecast for the region shown, once per region. */
function useForecast(): void {
  const id = region.value, near = regionInfo.value?.id === id ? regionInfo.value.center : null;
  useEffect(() => {
    const key = `${id}|${near?.join(',') ?? ''}`;
    if (!id || requested === key) return;
    requested = key;
    void loadConditionsForecast(id, near, fetch, location.href).then(f => { if (requested === key) conditionsForecast.value = f; });
  }, [id, near?.[0], near?.[1]]);
}

const FAMILY_OPTIONS = (Object.keys(FAMILIES) as Family[]).map(value => ({value, label: FAMILIES[value].label}));
const timeText = (iso: string, tz: string, withDay = false) => new Intl.DateTimeFormat('en-US', {...withDay ? {weekday: 'short'} : {}, hour: 'numeric', minute: '2-digit', timeZone: tz, timeZoneName: 'short'}).format(new Date(iso));
const value = (v: number | null, unit: string) => v === null ? '—' : `${Number(v.toFixed(unit === 'ft' ? 1 : 0))} ${unit}`;

export function Conditions({now = new Date()}: {now?: Date} = {}) {
  useForecast();
  const [family, setFamily] = useState<Family>('gfs');
  const tz = zone(), state = dockState(now, tz), selected = new Date(state.at).toISOString();
  const forecast = conditionsForecast.value?.region === region.value ? conditionsForecast.value : null;
  const report = coastReport.value?.data ?? null, binding = coastBinding.value;
  const span = conditionsSpan(now);
  const local = report && binding ? coastRows(report, binding.areaId, now) : {rows: [], site: null};
  const rows = conditionsRows(forecastRows(forecast, family, span.start), local.rows);
  const brief = currentBrief(now);
  const clocks = sourceClocks(forecast, family, report && binding ? report : null, local.site);
  const notes = PROFILE_TABLE[profile.value];
  return (
    <section class="app-conditions" aria-labelledby="app-conditions-title">
      <header class="app-conditions-head">
        <h2 id="app-conditions-title">Conditions</h2>
        <Segmented label="Forecast model" options={FAMILY_OPTIONS} value={family} onChange={setFamily} />
      </header>
      <dl class="app-conditions-now" aria-label={`Selected hour, ${timeText(selected, tz, true)}`}>
        {readingsAt(rows, selected).map(r => <div key={r.label}><dt class="ui-eyebrow">{r.label}</dt><dd class="ui-mono">{value(r.value, r.unit)}</dd></div>)}
      </dl>
      <div class="app-conditions-chart" role="region" aria-label="Conditions chart, scrolls sideways" tabIndex={0}>
        <CoastMarkup renderer="chart" args={[rows, span.start, span.end, selected, tz, {windows: [...brief?.windows ?? []]}]}
          onCursor={at => selectHour(now, tz, Date.parse(at))} />
      </div>
      <p class="app-conditions-caption">
        Drag the chart to move the hour. Wind, gusts, offshore seas, air and cloud: {FAMILIES[family].label} models at forecast point {forecast?.point.id ?? '—'}
        {local.rows.length ? '; nearshore and tide: the local coast report' : '; the local coast report is unavailable here'}. Independent row scales; gaps stay blank; shaded hours are lower exposure.
      </p>
      <h3 class="ui-eyebrow">Source clocks</h3>
      <ul class="app-conditions-clocks">
        {clocks.map(c => <li key={c.label}>{c.label} <span class="ui-mono">{c.at ? `${c.kind} ${timeText(c.at, tz, true)}` : 'unavailable'}</span></li>)}
      </ul>
      <h3 class="ui-eyebrow">Tide events</h3>
      {brief?.tideEvents.length ? (
        <ul class="app-conditions-tides">
          {brief.tideEvents.map(e => <li key={e.at}>{e.type === 'H' ? 'High' : 'Low'} <span class="ui-mono">{timeText(e.at, tz)} · {e.heightFt.toFixed(1)} ft {brief.tideDatum}</span></li>)}
        </ul>
      ) : <p class="app-empty">No tide predictions for {localParts(new Date(state.at), tz).weekday || 'this day'}.</p>}
      <h3 class="ui-eyebrow">Before you go</h3>
      <ul class="app-conditions-notes">
        <li>{notes.caveat}</li>
        {brief?.alerts.map(a => <li key={a.id}><a href={a.url} target="_blank" rel="noopener">{a.event}</a></li>)}
        {brief?.notice ? <li><a href={brief.notice.url} target="_blank" rel="noopener">Beach notice: {brief.notice.name}</a></li> : null}
        <li><a href={CDFW_REGULATIONS} target="_blank" rel="noopener">Current CDFW ocean fishing rules</a></li>
      </ul>
      <h3 class="ui-eyebrow">Surface current</h3>
      <div class="app-conditions-current"><CurrentSource /><p class="app-empty">The map draws the source chosen here or in the Currents layer.</p></div>
    </section>
  );
}
