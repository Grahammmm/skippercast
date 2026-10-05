// Trip labelling for the classifier's validation (docs/plans/charter-fleet/design.md § 11
// Validation, § 13 Labelling, D10; CF-48). #fleet-labels lists trips (newest first, filter
// labelled or not) with the progress toward the 30-trip target; #fleet-trip/<id> shows one
// trip's segments on a small map with a speed strip, and labels a time range as in-port,
// transit, fishing drift or fishing troll with the basis for it (server/fleet/admin/labels.ts).
// The labeller is recorded server-side (the admin's id; an agent set carries agent:<name>).
//
// Everything shown of the trip except the hand labels is inferred from movement: segment
// kinds, speeds and fishing minutes are the classifier's output, never confirmed fishing.
import {useEffect, useState} from 'preact/hooks';
import {ApiError, getFleet, postFleet, when} from './api.ts';
import {fleetHref, fleetTripHref, fleetVesselHref} from './route.ts';

const LABELS = ['in-port', 'transit', 'fishing-drift', 'fishing-troll'] as const;
const FILTERS = ['all', 'no', 'yes'] as const;
export const TRIP_COPY = {
  heading: 'Labelling', tripHeading: 'Label a trip', loading: 'Loading…', failed: 'Could not load. Try again.', none: 'No trips match.', more: 'More',
  saved: 'Label saved.', deleted: 'Label deleted.',
  filter: 'Show', filters: {all: 'All trips', no: 'Not labelled', yes: 'Labelled'} as Record<string, string>,
  inferred: 'Inferred from movement',
  inferredNote: 'Segment kinds, speeds and fishing minutes are inferred from movement (speed and track shape): the classifier’s output, never confirmed fishing. Your labels are what it is scored against.',
  progressHeading: 'Validation set',
  progress: (n: number, target: number) => `${n} of ${target} trips labelled`,
  progressParts: (admin: number, agent: number, ports: number) => `${admin} labels by admins, ${agent} by agents · ${ports} departure ports`,
  minutesHeading: 'Labelled minutes',
  howTo: 'Label trips across classes and ports. A labelled trip’s raw positions are copied to the validation store on the next processor run and kept while it has a label; raw positions are otherwise kept 30 days, so label recent trips.',
  date: 'Date', boat: 'Boat', port: 'Port', source: 'Source', status: 'Status', fishingMin: 'Fishing min (inferred from movement)', labels: 'Labels',
  window: 'Trip', departed: 'Departed', returned: 'Returned', open: 'still open', distance: 'Distance (nm)', offshore: 'Max offshore (nm)', rights: 'Rights',
  classifier: 'Classifier version', mapHeading: 'Track', mapLabel: 'Track by segment kind, inferred from movement',
  stripHeading: 'Speed', stripLabel: 'Mean speed over ground per segment, inferred from movement; labels below',
  stripHint: 'Pick a segment (in the strip or the table) to fill the range, then adjust the times if needed.',
  segmentsHeading: 'Segments (inferred from movement)', kind: 'Kind (inferred)', from: 'From', to: 'To', minutes: 'Minutes', sog: 'Mean SOG (kn)',
  straightness: 'Straightness', headingVar: 'Heading variance', use: 'Use range',
  formHeading: 'Add a label', start: 'Start', end: 'End', label: 'Label', basis: 'Basis', basisHint: 'What you went on, for example the track shape, a skipper’s log or a landing report.',
  add: 'Add label', labelsHeading: 'Labels', labelsNone: 'No labels yet.', labeller: 'Labeller', created: 'Added', remove: 'Delete', agent: 'agent',
  kinds: {'in-port': 'In port', 'transit': 'Transit', 'fishing-drift': 'Fishing, drift or anchor', 'fishing-troll': 'Fishing, troll', 'gap': 'Gap (no positions)'} as Record<string, string>,
  basisSuggestions: ['Track shape (speed and turns)', 'Skipper’s log', 'Landing report', 'Photo or video', 'On board'],
};
/** The nav and page-title label of the labelling views (web/admin/app.tsx FLEET_PAGES). */
export const LABELS_LABEL = TRIP_COPY.heading;
const COPY = TRIP_COPY;
const KIND_COLOR: Record<string, string> = {'in-port': 'var(--ink-2)', 'transit': 'var(--brand)', 'fishing-drift': 'var(--kelp)', 'fishing-troll': 'var(--caution)', 'gap': 'var(--line)'};

interface TripRow {
  id: string; region: string; vessel_id: string; vessel_name: string | null; vessel_class: string | null; mmsi: string; depart_port_id: string | null;
  return_port_id: string | null; departed_at: string; returned_at: string | null; local_date: string; status: string; distance_nm: number | null;
  fishing_min: number | null; source: string; rights: string; labels: number;
}
interface Progress {trips: number; labels: number; by_labeller: {admin: number; agent: number}; ports: number; minutes: Record<string, number>; target_trips: number}
interface Segment {id: string; seq: number; kind: string; started_at: string; ended_at: string; points_n: number | null; mean_sog: number | null;
  straightness: number | null; heading_var: number | null; coordinates: [number, number][]}
interface Label {id: string; started_at: string; ended_at: string; label: string; labeller: string; basis: string | null; created_at: string}
interface TripDetail {
  trip: TripRow & {classifier_version: string; max_offshore_nm: number | null};
  window: {from: string; to: string}; segments: Segment[]; labels: Label[];
}

const errorText = (e: unknown): string => (e instanceof ApiError && e.status !== 500 ? e.message : COPY.failed);
const value = (e: Event): string => (e.currentTarget as HTMLInputElement).value;
const ms = (iso: string): number => Date.parse(iso);
const minutesBetween = (a: string, b: string): number => Math.round((ms(b) - ms(a)) / 60000);
/** An ISO time as a datetime-local value in the browser's zone. */
function localInput(iso: string): string {
  const d = new Date(iso);
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
}
/** A datetime-local value (the browser's zone) as an ISO UTC time; null if empty or invalid. */
function fromLocalInput(v: string): string | null {
  const t = Date.parse(v);
  return v && Number.isFinite(t) ? new Date(t).toISOString() : null;
}

export function FleetLabelsView({region}: {region: string}) {
  const [filter, setFilter] = useState<string>('all');
  const [trips, setTrips] = useState<TripRow[] | null | 'failed'>(null);
  const [progress, setProgress] = useState<Progress | null>(null);
  const [next, setNext] = useState<string | null>(null);
  const load = (cursor: string | null): void => {
    getFleet<{trips: TripRow[]; next: string | null; progress: Progress}>('trips', {region, labelled: filter, cursor}).then(r => {
      setTrips(prior => (cursor && Array.isArray(prior) ? [...prior, ...r.trips] : r.trips)); setNext(r.next); setProgress(r.progress);
    }, () => setTrips('failed'));
  };
  useEffect(() => { setTrips(null); load(null); }, [region, filter]);
  return (
    <section class="admin-view" aria-labelledby="fleet-labels-heading">
      <h1 id="fleet-labels-heading" tabIndex={-1}>{COPY.heading}</h1>
      {progress ? (
        <section aria-labelledby="fleet-labels-progress">
          <h2 id="fleet-labels-progress">{COPY.progressHeading}</h2>
          <dl class="admin-fields">
            <dt>{COPY.labels}</dt><dd class={progress.trips >= progress.target_trips ? 'is-go' : 'is-caution'}>{COPY.progress(progress.trips, progress.target_trips)}</dd>
            <dt>{COPY.labeller}</dt><dd>{COPY.progressParts(progress.by_labeller.admin, progress.by_labeller.agent, progress.ports)}</dd>
            <dt>{COPY.minutesHeading}</dt><dd>{LABELS.map(k => `${COPY.kinds[k]}: ${progress.minutes[k] ?? 0}`).join(' · ')}</dd>
          </dl>
        </section>
      ) : null}
      <p class="admin-hint">{COPY.howTo}</p>
      <div class="admin-filters"><label for="fleet-labels-filter">{COPY.filter}
        <select id="fleet-labels-filter" value={filter} onChange={e => setFilter(value(e))}>
          {FILTERS.map(f => <option key={f} value={f}>{COPY.filters[f]}</option>)}
        </select></label></div>
      {trips === null ? <p>{COPY.loading}</p> : trips === 'failed' ? <p class="admin-error" role="alert">{COPY.failed}</p> : !trips.length ? <p>{COPY.none}</p> : (
        <>
          <div class="admin-scroll" tabIndex={0} role="region" aria-label={COPY.heading}><table class="admin-counts">
            <thead><tr><th scope="col">{COPY.date}</th><th scope="col">{COPY.boat}</th><th scope="col">{COPY.port}</th><th scope="col">{COPY.status}</th>
              <th scope="col">{COPY.source}</th><th scope="col">{COPY.fishingMin}</th><th scope="col">{COPY.labels}</th></tr></thead>
            <tbody>{trips.map(t => (
              <tr key={t.id}>
                <th scope="row"><a href={fleetTripHref(t.id)}>{t.local_date} {when(t.departed_at)}</a></th>
                <td>{t.vessel_name ?? t.vessel_id}{t.vessel_class ? ` · ${t.vessel_class}` : ''}</td>
                <td>{t.depart_port_id ?? '—'}</td><td>{t.status}</td><td>{t.source}</td><td>{t.fishing_min ?? '—'}</td><td>{t.labels}</td>
              </tr>
            ))}</tbody>
          </table></div>
          {next ? <p><button type="button" class="admin-button" onClick={() => load(next)}>{COPY.more}</button></p> : null}
        </>
      )}
    </section>
  );
}

export function FleetTripView({id}: {id: string}) {
  const [detail, setDetail] = useState<TripDetail | null | 'failed'>(null);
  const [range, setRange] = useState<{from: string; to: string} | null>(null);
  const [label, setLabel] = useState<string>('fishing-drift');
  const [basis, setBasis] = useState('');
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const load = (): Promise<void> => getFleet<TripDetail>(`trips/${encodeURIComponent(id)}`).then(setDetail, () => setDetail('failed'));
  useEffect(() => { void load(); }, [id]);

  if (detail === null) return <p>{COPY.loading}</p>;
  if (detail === 'failed') return <p class="admin-error" role="alert">{COPY.failed}</p>;
  const {trip, window: span, segments, labels} = detail;
  const pick = (s: {started_at: string; ended_at: string}): void => { setRange({from: s.started_at, to: s.ended_at}); setNotice(''); setError(''); };

  async function act(run: () => Promise<unknown>, done: string): Promise<boolean> {
    if (busy) return false;
    setBusy(true); setError(''); setNotice('');
    try { await run(); await load(); setNotice(done); return true; } catch (e) { setError(errorText(e)); return false; } finally { setBusy(false); }
  }
  async function submit(e: Event): Promise<void> {
    e.preventDefault();
    if (!range) return;
    // The inputs hold whole minutes: keep the range inside the trip.
    const from = ms(range.from) < ms(span.from) ? span.from : range.from, to = ms(range.to) > ms(span.to) ? span.to : range.to;
    if (await act(() => postFleet(`trips/${encodeURIComponent(id)}/labels`, {started_at: from, ended_at: to, label, basis}), COPY.saved)) { setRange(null); setBasis(''); }
  }

  return (
    <section class="admin-view" aria-labelledby="fleet-trip-heading">
      <p><a href={fleetHref('fleet-labels', trip.region)}>{COPY.heading}</a></p>
      <h1 id="fleet-trip-heading" tabIndex={-1}>{COPY.tripHeading}: <a href={fleetVesselHref(trip.vessel_id)}>{trip.vessel_name ?? trip.vessel_id}</a> · {trip.local_date}</h1>
      <p class="admin-hint">{COPY.inferredNote}</p>
      <p class="admin-notice" role="status">{notice}</p>
      {error ? <p class="admin-error" role="alert">{error}</p> : null}
      <dl class="admin-fields">
        <dt>{COPY.departed}</dt><dd>{when(trip.departed_at)}{trip.depart_port_id ? ` · ${trip.depart_port_id}` : ''}</dd>
        <dt>{COPY.returned}</dt><dd>{trip.returned_at ? when(trip.returned_at) : COPY.open}{trip.return_port_id ? ` · ${trip.return_port_id}` : ''}</dd>
        <dt>{COPY.status}</dt><dd>{trip.status}</dd>
        <dt>{COPY.distance}</dt><dd>{trip.distance_nm ?? '—'}</dd>
        <dt>{COPY.offshore}</dt><dd>{trip.max_offshore_nm ?? '—'}</dd>
        <dt>{COPY.fishingMin}</dt><dd>{trip.fishing_min ?? '—'}</dd>
        <dt>{COPY.source}</dt><dd>{trip.source} · {trip.rights}</dd>
        <dt>{COPY.classifier}</dt><dd>{trip.classifier_version}</dd>
      </dl>

      <h2>{COPY.mapHeading}</h2>
      <TrackMap segments={segments} range={range} />
      <h2>{COPY.stripHeading}</h2>
      <SpeedStrip span={span} segments={segments} labels={labels} range={range} onPick={pick} />
      <p class="admin-muted">{COPY.stripHint}</p>
      <Legend />

      <h2>{COPY.formHeading}</h2>
      <form class="admin-editor" onSubmit={e => void submit(e)}>
        <label for="fleet-trip-start">{COPY.start}
          <input id="fleet-trip-start" type="datetime-local" step={60} required value={range ? localInput(range.from) : ''}
            min={localInput(span.from)} max={localInput(span.to)}
            onChange={e => { const v = fromLocalInput(value(e)); if (v) setRange({from: v, to: range?.to ?? span.to}); }} /></label>
        <label for="fleet-trip-end">{COPY.end}
          <input id="fleet-trip-end" type="datetime-local" step={60} required value={range ? localInput(range.to) : ''}
            min={localInput(span.from)} max={localInput(span.to)}
            onChange={e => { const v = fromLocalInput(value(e)); if (v) setRange({from: range?.from ?? span.from, to: v}); }} /></label>
        <label for="fleet-trip-label">{COPY.label}
          <select id="fleet-trip-label" value={label} onChange={e => setLabel(value(e))}>
            {LABELS.map(k => <option key={k} value={k}>{COPY.kinds[k]}</option>)}
          </select></label>
        <label for="fleet-trip-basis">{COPY.basis}
          <input id="fleet-trip-basis" type="text" required minLength={2} maxLength={500} list="fleet-trip-bases" value={basis}
            aria-describedby="fleet-trip-basis-hint" onInput={e => setBasis(value(e))} /></label>
        <datalist id="fleet-trip-bases">{COPY.basisSuggestions.map(b => <option key={b} value={b} />)}</datalist>
        <p id="fleet-trip-basis-hint" class="admin-muted">{COPY.basisHint}</p>
        <button type="submit" class="admin-button is-primary" disabled={busy || !range || basis.trim().length < 2}>{COPY.add}</button>
      </form>

      <h2>{COPY.labelsHeading}</h2>
      {!labels.length ? <p>{COPY.labelsNone}</p> : (
        <div class="admin-scroll" tabIndex={0} role="region" aria-label={COPY.labelsHeading}><table class="admin-counts">
          <thead><tr><th scope="col">{COPY.from}</th><th scope="col">{COPY.to}</th><th scope="col">{COPY.label}</th><th scope="col">{COPY.basis}</th>
            <th scope="col">{COPY.labeller}</th><th scope="col">{COPY.created}</th><th scope="col"><span class="admin-visually-hidden">{COPY.remove}</span></th></tr></thead>
          <tbody>{labels.map(l => (
            <tr key={l.id}>
              <th scope="row">{when(l.started_at)}</th><td>{when(l.ended_at)}</td><td>{COPY.kinds[l.label] ?? l.label}</td><td>{l.basis ?? '—'}</td>
              <td>{l.labeller.startsWith('agent:') ? `${l.labeller.slice(6)} (${COPY.agent})` : l.labeller}</td><td>{when(l.created_at)}</td>
              <td><button type="button" class="admin-button is-danger" disabled={busy}
                onClick={() => void act(() => postFleet(`labels/${encodeURIComponent(l.id)}/delete`, {}), COPY.deleted)}>{COPY.remove}</button></td>
            </tr>
          ))}</tbody>
        </table></div>
      )}

      <h2>{COPY.segmentsHeading}</h2>
      <div class="admin-scroll" tabIndex={0} role="region" aria-label={COPY.segmentsHeading}><table class="admin-counts">
        <thead><tr><th scope="col">{COPY.kind}</th><th scope="col">{COPY.from}</th><th scope="col">{COPY.minutes}</th><th scope="col">{COPY.sog}</th>
          <th scope="col">{COPY.straightness}</th><th scope="col">{COPY.headingVar}</th><th scope="col"><span class="admin-visually-hidden">{COPY.use}</span></th></tr></thead>
        <tbody>{segments.map(s => (
          <tr key={s.id}>
            <th scope="row">{COPY.kinds[s.kind] ?? s.kind}</th><td>{when(s.started_at)}</td><td>{minutesBetween(s.started_at, s.ended_at)}</td>
            <td>{s.mean_sog ?? '—'}</td><td>{s.straightness ?? '—'}</td><td>{s.heading_var ?? '—'}</td>
            <td><button type="button" class="admin-button" onClick={() => pick(s)}>{COPY.use}</button></td>
          </tr>
        ))}</tbody>
      </table></div>
    </section>
  );
}

function Legend() {
  return (
    <p class="admin-muted">{COPY.inferred}: {(['in-port', 'transit', 'fishing-drift', 'fishing-troll', 'gap'] as const).map(k => (
      <span key={k}> <svg width="12" height="12" aria-hidden="true"><rect width="12" height="12" fill={KIND_COLOR[k]} /></svg> {COPY.kinds[k]}</span>
    ))}</p>
  );
}

const W = 600, MAP_H = 300, PAD = 10;
/** The segments' tracks on an equirectangular projection; the picked range drawn heavier. */
function TrackMap({segments, range}: {segments: Segment[]; range: {from: string; to: string} | null}) {
  const points = segments.flatMap(s => s.coordinates);
  if (!points.length) return <p class="admin-muted">—</p>;
  const lons = points.map(p => p[0]), lats = points.map(p => p[1]);
  const [w, e, s, n] = [Math.min(...lons), Math.max(...lons), Math.min(...lats), Math.max(...lats)];
  const k = Math.cos(((s + n) / 2) * Math.PI / 180);
  const spanX = Math.max((e - w) * k, 1e-6), spanY = Math.max(n - s, 1e-6);
  const scale = Math.min((W - 2 * PAD) / spanX, (MAP_H - 2 * PAD) / spanY);
  const xy = ([lon, lat]: [number, number]): string => `${(PAD + (lon - w) * k * scale).toFixed(1)},${(MAP_H - PAD - (lat - s) * scale).toFixed(1)}`;
  const inRange = (seg: Segment): boolean => !!range && ms(seg.started_at) < ms(range.to) && ms(seg.ended_at) > ms(range.from);
  return (
    <svg viewBox={`0 0 ${W} ${MAP_H}`} role="img" aria-label={COPY.mapLabel} style={{width: '100%', maxWidth: `${W}px`, background: 'var(--surface)'}}>
      {segments.filter(seg => seg.coordinates.length).map(seg => (
        <polyline key={seg.id} points={seg.coordinates.map(xy).join(' ')} fill="none" stroke={KIND_COLOR[seg.kind] ?? 'var(--ink)'}
          stroke-width={inRange(seg) ? 5 : 2.5} stroke-dasharray={seg.kind === 'gap' ? '4 4' : undefined} stroke-linecap="round" stroke-linejoin="round">
          <title>{`${COPY.kinds[seg.kind] ?? seg.kind} (${COPY.inferred.toLowerCase()}), ${when(seg.started_at)}`}</title>
        </polyline>
      ))}
    </svg>
  );
}

const STRIP_H = 90, LANE = 18;
/** Mean SOG per segment across the trip's time; the labels lane under it; the picked range outlined. */
function SpeedStrip({span, segments, labels, range, onPick}: {span: {from: string; to: string}; segments: Segment[]; labels: Label[];
  range: {from: string; to: string} | null; onPick: (s: {started_at: string; ended_at: string}) => void}) {
  const t0 = ms(span.from), dt = Math.max(ms(span.to) - t0, 60000);
  const x = (iso: string): number => Math.max(0, Math.min(W, ((ms(iso) - t0) / dt) * W));
  const top = Math.max(10, ...segments.map(s => s.mean_sog ?? 0));
  const height = STRIP_H + LANE + 6;
  return (
    <svg viewBox={`0 0 ${W} ${height}`} role="img" aria-label={COPY.stripLabel} style={{width: '100%', maxWidth: `${W}px`, background: 'var(--surface)'}}>
      {segments.map(s => {
        const h = Math.max(2, ((s.mean_sog ?? 0) / top) * (STRIP_H - 4));
        return (
          <rect key={s.id} x={x(s.started_at)} y={STRIP_H - h} width={Math.max(1, x(s.ended_at) - x(s.started_at))} height={h}
            fill={KIND_COLOR[s.kind] ?? 'var(--ink)'} style={{cursor: 'pointer'}} onClick={() => onPick(s)}>
            <title>{`${COPY.kinds[s.kind] ?? s.kind} (${COPY.inferred.toLowerCase()}): ${s.mean_sog ?? '—'} kn, ${when(s.started_at)}`}</title>
          </rect>
        );
      })}
      {labels.map(l => (
        <rect key={l.id} x={x(l.started_at)} y={STRIP_H + 4} width={Math.max(1, x(l.ended_at) - x(l.started_at))} height={LANE}
          fill={KIND_COLOR[l.label] ?? 'var(--ink)'} stroke="var(--ink)" stroke-width={1}>
          <title>{`${COPY.kinds[l.label] ?? l.label}: ${l.basis ?? ''}`}</title>
        </rect>
      ))}
      {range ? <rect x={x(range.from)} y={1} width={Math.max(1, x(range.to) - x(range.from))} height={height - 2} fill="none" stroke="var(--ink)" stroke-width={2} /> : null}
    </svg>
  );
}
