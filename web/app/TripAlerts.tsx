// Saved-trip alerts and private comfort feedback in the account menu's dialog
// (US-R5, #602): a Preact component over web/alerts.ts, replacing v1's
// dist/trip-alerts.js. Same /api/ calls, the same saved records, the same
// limits from the saved boat and the same copy; the delete confirmation is in
// the page, never window.confirm. Styles: web/app/account.css (.app-alerts).
import {useEffect, useId, useMemo, useRef, useState} from 'preact/hooks';
import type {TargetedSubmitEvent} from 'preact';
import {Button} from '../ui/Button.tsx';
import {sharedFetch} from '../shared-fetch.ts';
import {
  alertDate, alertNames, alertSpecies, api, comfortBody, disablePush, enablePush, eventLine, feedbackPhase, tripBody, tripBoat, tripDefaults, tripLine,
  type AlertEvent, type AlertForm, type BoatFactors, type Feedback, type RegionAlerts, type SavedTrip,
} from '../alerts.ts';

type SessionAnswer = {signedIn?: boolean; signIn?: unknown; publicKey?: string | null};
type Boat = {factors: BoatFactors; saved: {boat?: {name?: unknown}} | null};
type Loaded =
  | {state: 'loading'} | {state: 'error'; message: string} | {state: 'offline'} | {state: 'disabled'}
  | {state: 'signed-out'; href: string}
  | {state: 'signed-in'; session: SessionAnswer; region: RegionAlerts; boat: Boat};

const hours = (v: FormDataEntryValue | null) => Number(v);

/** The region's points and species, the session and the saved boat; each a fresh read when the dialog opens. */
async function load(regionId: string): Promise<Loaded> {
  let session: SessionAnswer;
  try { session = await api<SessionAnswer>('session'); } catch { return {state: 'offline'}; }
  if (!session.signedIn) {
    const {signInHref} = await import('../../dist/account.js');
    const href = signInHref(session.signIn);
    return href ? {state: 'signed-out', href} : {state: 'disabled'};
  }
  const [response, handling] = await Promise.all([sharedFetch(`regions/${encodeURIComponent(regionId)}/region.json`), import('../../dist/boat-handling.js')]);
  if (!response.ok) return {state: 'error', message: 'The region could not be loaded. Try again when you are online.'};
  return {state: 'signed-in', session, region: await response.json() as RegionAlerts,
    boat: {factors: handling.activeBoatFactors() as BoatFactors, saved: handling.savedBoat() as Boat['saved']}};
}

function SignedOut({href}: {href: string}) {
  return (
    <>
      <details class="insight-card" open>
        <summary>Saved-trip alerts</summary>
        <p>Save a date, area and comfort limits. Receive material changes and a day-before assessment.</p>
        <p><a href={href}>Sign in or create an account</a>. SkipperCast accounts use a passkey: Face ID, Touch ID or your device PIN, no password.</p>
        <p class="small">The map stays public. Saved trips and delivery settings are private to your account.</p>
      </details>
      <p class="small"><a href={href}>Sign in or create an account</a> to save your boat comfort feedback.</p>
    </>
  );
}

/** "Yes, delete everything" in the page under the button; Cancel or Escape keeps everything. */
function ConfirmDelete({onConfirm, onCancel}: {onConfirm: () => void; onCancel: () => void}) {
  const id = useId(), box = useRef<HTMLDivElement>(null);
  useEffect(() => { box.current?.querySelector<HTMLButtonElement>('button')?.focus(); }, []);
  return (
    <div ref={box} class="account-confirm" role="alertdialog" aria-labelledby={id}
      onKeyDown={(e: KeyboardEvent) => { if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); onCancel(); } }}>
      <p id={id}>Delete your SkipperCast account and all saved trips, notification subscriptions, assessments and comfort feedback? This cannot be undone.</p>
      <div class="home-port-actions">
        <Button size="sm" onClick={onCancel}>Cancel</Button>
        <Button size="sm" class="account-destructive" onClick={onConfirm}>Yes, delete everything</Button>
      </div>
    </div>
  );
}

function SignedIn({session, region, boat, target}: {session: SessionAnswer; region: RegionAlerts; boat: Boat; target: string | null}) {
  const saved = tripBoat(boat.factors, boat.saved?.boat), limits = tripDefaults(boat.factors);
  const choice = alertSpecies(region, target), names = useMemo(() => alertNames(region), [region]);
  const [species, setSpecies] = useState(choice.value);
  const [status, setStatus] = useState('');
  const [trips, setTrips] = useState<{trips: SavedTrip[]; events: AlertEvent[]} | null>(null);
  const [feedback, setFeedback] = useState<Feedback[] | null>(null);
  const [comfortStatus, setComfortStatus] = useState('');
  const [confirming, setConfirming] = useState(false);
  const privacy = useRef<HTMLDetailsElement>(null);
  /** Cancel returns focus to the button that asked. */
  const keep = () => { setConfirming(false); requestAnimationFrame(() => privacy.current?.querySelector<HTMLButtonElement>('[data-delete-account]')?.focus()); };
  const fail = (error: unknown) => setStatus((error as Error).message);
  const refresh = () => api<{trips: SavedTrip[]; events: AlertEvent[]}>('trips').then(setTrips, fail);
  const refreshFeedback = () => api<{feedback: Feedback[]}>('comfort').then(d => setFeedback(d.feedback), () => {});
  useEffect(() => { void refresh(); void refreshFeedback(); }, []);

  const save = async (event: TargetedSubmitEvent<HTMLFormElement>) => {
    event.preventDefault();
    const f = new FormData(event.currentTarget);
    const form: AlertForm = {date: String(f.get('date')), point: String(f.get('point')), start_hour: hours(f.get('start_hour')), end_hour: hours(f.get('end_hour')),
      wind_limit: hours(f.get('wind_limit')), gust_limit: hours(f.get('gust_limit')), sea_limit: hours(f.get('sea_limit'))};
    try {
      await api('trips', {method: 'POST', body: JSON.stringify(tripBody(form, region.id, species, saved))});
      setStatus('Trip saved. Scheduled checks run about every 30 minutes; notifications require device permission.');
      void refresh();
    } catch (error) { fail(error); }
  };
  const act = (run: () => Promise<unknown>) => () => { run().catch(fail); };
  const remove = (id: string) => act(async () => { await api('trips', {method: 'DELETE', body: JSON.stringify({id})}); void refresh(); });
  const ack = (id: AlertEvent['id']) => act(async () => { await api('events/ack', {method: 'POST', body: JSON.stringify({id})}); void refresh(); });
  const exportRecords = act(async () => {
    const d = await api('privacy'), url = URL.createObjectURL(new Blob([JSON.stringify(d, null, 2)], {type: 'application/json'}));
    const a = document.createElement('a');
    a.href = url; a.download = 'SkipperCast-private-records.json'; a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  });
  const deleteAll = act(async () => {
    setConfirming(false);
    await api('privacy', {method: 'DELETE'});
    setStatus('Your account and records have been deleted.');
    setTimeout(() => location.reload(), 1200);
  });
  const sendComfort = async (event: TargetedSubmitEvent<HTMLFormElement>) => {
    event.preventDefault();
    const f = new FormData(event.currentTarget);
    try {
      await api('comfort', {method: 'POST', body: JSON.stringify(comfortBody(region.id, Number(f.get('rating')), String(f.get('phase'))))});
      setComfortStatus('Saved privately. Forecast context is attached only when the selected hour is near now.');
      void refreshFeedback();
    } catch (error) { setComfortStatus((error as Error).message); }
  };

  return (
    <>
      <label>Alert species
        <select id="species-select" value={species} onChange={e => setSpecies(e.currentTarget.value)}>
          {[...new Set(choice.options.map(o => o.group))].map(group => (
            <optgroup key={group} label={group}>{choice.options.filter(o => o.group === group).map(o => <option key={o.id} value={o.id}>{o.name}</option>)}</optgroup>
          ))}
        </select>
      </label>
      <details class="insight-card" open>
        <summary>My trip alerts</summary>
        <form id="save-alert" class="insight-form" onSubmit={e => void save(e)}>
          <label>Trip date<input name="date" type="date" defaultValue={alertDate(region.timezone)} required /></label>
          <label>Area<select name="point">{region.forecast_points.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select></label>
          <label>From · local hour<input name="start_hour" type="number" min="0" max="22" defaultValue="7" required /></label>
          <label>Until · local hour<input name="end_hour" type="number" min="1" max="23" defaultValue="13" required /></label>
          <label>Wind limit · kt<input name="wind_limit" type="number" min="1" max="30" defaultValue={limits.wind} required /></label>
          <label>Gust limit · kt<input name="gust_limit" type="number" min="1" max="40" defaultValue={limits.gust} required /></label>
          <label>Sea limit · ft<input name="sea_limit" type="number" min="0.5" max="10" step="0.5" defaultValue={limits.sea} required /></label>
          <Button type="submit" variant="primary">Save this fishing window</Button>
        </form>
        <p class="small" id="trip-boat-note">{saved
          ? `Limits start from your saved boat${saved.name ? ` (${saved.name})` : ''}; alerts judge wind chop for it too.`
          : 'Limits start from the reference 23 ft boat. Set your boat to tailor them.'}</p>
        <p class="small">Uses the selected target species. These alerts assess the saved area's weather window and reviewed rules; they do not plan navigation or predict catches.</p>
        <div class="inavx-actions">
          <Button size="sm" onClick={act(async () => { await enablePush(session.publicKey); setStatus('Notifications enabled on this device. Saved trips are checked automatically.'); })}>Enable notifications on this device</Button>
          <Button size="sm" onClick={act(async () => { await disablePush(); setStatus('Account notifications stopped. Saved assessments remain available here.'); })}>Stop notifications</Button>
        </div>
        <p id="alert-status" role="status">{status}</p>
        <div id="saved-trips">
          {trips ? trips.trips.length ? trips.trips.map(t => (
            <p key={t.id}><strong>{tripLine(t, names)}</strong> <Button size="sm" variant="quiet" onClick={remove(t.id)} aria-label={`Delete the trip on ${t.date} at ${names.point.get(t.point) ?? t.point}`}>Delete</Button></p>
          )) : <p>No saved trips.</p> : null}
        </div>
        {trips?.events.length ? (
          <details id="alert-history">
            <summary>Recent assessments ({trips.events.length})</summary>
            {trips.events.map(e => (
              <article key={e.id}>
                <strong>{eventLine(e)}</strong>
                <p style={{whiteSpace: 'pre-line'}}>{e.message}</p>
                {!['read', 'delivered'].includes(e.status) ? <Button size="sm" variant="quiet" onClick={ack(e.id)}>Mark read</Button> : null}
              </article>
            ))}
          </details>
        ) : null}
        <details ref={privacy}>
          <summary>Privacy & account data</summary>
          <p>Trips, notification endpoints and comfort feedback are stored privately. Delete a trip to stop its monitoring. Comfort feedback is retained for one year; trips and assessments for 90 days.</p>
          <Button size="sm" onClick={exportRecords}>Export my records</Button>{' '}
          <Button data-delete-account size="sm" disabled={confirming} onClick={() => setConfirming(true)}>Delete my account and records</Button>{' '}
          <a href="#account">Account, passkeys and sign out</a>
          {confirming ? <ConfirmDelete onConfirm={deleteAll} onCancel={keep} /> : null}
        </details>
      </details>
      <details id="comfort-feedback">
        <summary>How did your boat feel today?</summary>
        <form id="comfort-form" class="insight-form" onSubmit={e => void sendComfort(e)}>
          <label>Part of trip<select name="phase"><option value="outbound">Outbound</option><option value="fishing">Fishing</option><option value="return">Return</option></select></label>
          <label>Comfort · 1 rough to 10 excellent<input name="rating" type="number" min="1" max="10" defaultValue="7" required /></label>
          <Button type="submit">Save private feedback</Button>
        </form>
        <p id="comfort-status" role="status">{comfortStatus}</p>
        {feedback ? (
          <div id="comfort-history">
            <p class="small">{feedback.length} private reports. These describe your experience; they do not automatically alter public ratings or assert a boat-motion model.</p>
            {feedback.slice(0, 5).map((f, i) => <p key={i}>{new Date(f.observed_at).toLocaleDateString()} · {f.rating}/10 · {feedbackPhase(f)}</p>)}
          </div>
        ) : null}
      </details>
    </>
  );
}

/** The alerts dialog's body for `regionId`; the alert species starts on the app's target when the region lists it. */
export function TripAlerts({regionId, target}: {regionId: string; target: string | null}) {
  const [loaded, setLoaded] = useState<Loaded>({state: 'loading'});
  useEffect(() => {
    let live = true;
    setLoaded({state: 'loading'});
    load(regionId).then(l => { if (live) setLoaded(l); }, (e: Error) => { if (live) setLoaded({state: 'error', message: e.message}); });
    return () => { live = false; };
  }, [regionId]);
  return (
    <div class="app-alerts" id="trip-alerts">
      {loaded.state === 'loading' ? <p role="status">Loading your alerts…</p>
        : loaded.state === 'error' ? <p role="status">{loaded.message}</p>
        : loaded.state === 'offline' ? <p>Personal alerts are available on the published site. Retry after connecting.</p>
        : loaded.state === 'disabled' ? <p>Accounts are not available on this site. The map and forecasts stay public.</p>
        : loaded.state === 'signed-out' ? <SignedOut href={loaded.href} />
        : <SignedIn session={loaded.session} region={loaded.region} boat={loaded.boat} target={target} />}
    </div>
  );
}
