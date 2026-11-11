// Saved-trip alerts and private comfort feedback in the account menu's dialog
// (US-R5, #602): a Preact component over web/alerts.ts, replacing v1's
// dist/trip-alerts.js. Same /api/ calls, the same saved records, the same
// limits from the saved boat and the same copy; the delete confirmation is in
// the page, never window.confirm. Styles: web/app/account.css (.app-alerts).
// SC0922-12: the sheet's own words come from the string catalogue and follow the page language when they are
// drawn. What the server wrote (assessment messages, hazard notes, its error bodies) is shown as received, in
// English; in Spanish the sheet says so once and marks those texts lang="en".
import {useEffect, useId, useMemo, useRef, useState} from 'preact/hooks';
import type {TargetedSubmitEvent} from 'preact';
import {Button} from '../ui/Button.tsx';
import {sharedFetch} from '../shared-fetch.ts';
import {profile} from '../state.ts';
import {DEFAULT_ZONE} from '../zone.ts';
import {hasOwnLimits, limitsFor} from '../limits.ts';
import {weekendDigest, toText} from '../digest.ts';
import {language, localeOf, t, type Language, type StringId} from '../i18n.ts';
import {
  alertDate, alertNames, alertSpecies, AlertCopyError, fillAlertForm, type FillableForm, reuseLimitsNote, reuseStatus, reuseTrip, reusedLimits, api, comfortBody, dateRange, enablePush, deviceStatus, latestCheck, deviceButtons, deviceLine, type DeviceStatus, eventLine, feedbackPhase, formProblemId, latestTripEvent, assessmentTimeOrNull, savedTripLimits, profileTripDefaults, readRecapCatchLog, stopNotificationsId, tripBody, tripBoat, tripDefaults, tripLine, tripPlanSummary, tripRecaps,
  type AlertEvent, type AlertForm, type AlertNames, type BoatFactors, type CatchLogEntry, type Feedback, type RecapCatchLog, type RegionAlerts, type ReuseOmission, type SavedTrip, type TripPlanSummary,
} from '../alerts.ts';

type SessionAnswer = {signedIn?: boolean; signIn?: unknown; publicKey?: string | null};
type Boat = {factors: BoatFactors; saved: {boat?: {name?: unknown}} | null};
/** A status line kept as what it is, so a language change redraws it: a catalogue id of this sheet's own words, or text from outside (the server, the browser) shown as received. */
type Say = {id: StringId} | {literal: string} | null;
type Loaded =
  | {state: 'loading'} | {state: 'error'; say: Say} | {state: 'offline'} | {state: 'disabled'}
  | {state: 'signed-out'; href: string}
  | {state: 'signed-in'; session: SessionAnswer; region: RegionAlerts; boat: Boat};

const hours = (v: FormDataEntryValue | null) => Number(v);
const sayError = (error: unknown): Say => error instanceof AlertCopyError ? {id: error.id} : {literal: (error as Error).message};
/** What a server wrote stays English: in Spanish it is marked as such, and only there. */
const englishOnly = (lang: Language) => lang === 'es' ? 'en' : undefined;

/** A status line in the page language; outside text is marked lang="en" in Spanish. */
function Said({say, lang}: {say: Say; lang: Language}) {
  if (!say) return <>{''}</>;
  if ('id' in say) return <>{t(say.id, lang)}</>;
  return lang === 'es' ? <span lang="en">{say.literal}</span> : <>{say.literal}</>;
}

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
  if (!response.ok) return {state: 'error', say: {id: 'alerts.err.region'}};
  return {state: 'signed-in', session, region: await response.json() as RegionAlerts,
    boat: {factors: handling.activeBoatFactors() as BoatFactors, saved: handling.savedBoat() as Boat['saved']}};
}

function SignedOut({href}: {href: string}) {
  const lang = language.value;
  return (
    <>
      <details class="insight-card" open>
        <summary>{t('alerts.out.title', lang)}</summary>
        <p>{t('alerts.out.intro', lang)}</p>
        <p><a href={href}>{t('alerts.out.link', lang)}</a>{t('alerts.out.passkey', lang)}</p>
        <p class="small">{t('alerts.out.public', lang)}</p>
      </details>
      <p class="small"><a href={href}>{t('alerts.out.link', lang)}</a>{t('alerts.out.feedback', lang)}</p>
    </>
  );
}

/** "Yes, delete everything" in the page under the button; Cancel or Escape keeps everything. */
function ConfirmDelete({onConfirm, onCancel}: {onConfirm: () => void; onCancel: () => void}) {
  const id = useId(), box = useRef<HTMLDivElement>(null), lang = language.value;
  useEffect(() => { box.current?.querySelector<HTMLButtonElement>('button')?.focus(); }, []);
  return (
    <div ref={box} class="account-confirm" role="alertdialog" aria-labelledby={id}
      onKeyDown={(e: KeyboardEvent) => { if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); onCancel(); } }}>
      <p id={id}>{t('alerts.confirm', lang)}</p>
      <div class="home-port-actions">
        <Button size="sm" onClick={onCancel}>{t('alerts.cancel', lang)}</Button>
        <Button size="sm" class="account-destructive" onClick={onConfirm}>{t('alerts.confirmYes', lang)}</Button>
      </div>
    </div>
  );
}

/** What the person logged, in their own words: fish with the count, a blank, or not sure. */
const catchLine = (c: CatchLogEntry, lang: Language) => c.outcome === 'fish' ? t('alerts.catchFish', lang, {count: c.count}) : t(c.outcome === 'blank' ? 'alerts.catchBlank' : 'alerts.catchUnknown', lang);

/** The catch-log read's state beside the recap: still reading, or finished with every page (complete) or not. Left out, the recap is drawn as a complete read. */
export type CatchRead = Pick<RecapCatchLog, 'complete'> & {loading: boolean};

/** The plan saved with an alert, as stored: names and leg totals only, never positions or notes, and not re-checked since it was saved. */
function SavedPlan({plan, lang}: {plan: TripPlanSummary; lang: Language}) {
  return <div class="small">
    <strong>{t('alerts.plan.title', lang)}</strong> {t('alerts.plan.stale', lang)}
    {plan.kind === 'unavailable' ? <p>{t('alerts.plan.unavailable', lang)}</p> : <>
      <p>{t('alerts.plan.targets', lang, {names: plan.targets.join(' · ')})}</p>
      <p>{t('alerts.plan.stops', lang)}</p>
      {plan.stops.length ? <ol>{plan.stops.map((s, i) => <li key={i}>{s}</li>)}</ol> : <p>{t('alerts.plan.noStops', lang)}</p>}
      <p>{plan.totals ? t('alerts.plan.totals', lang, {nm: plan.totals.nm, minutes: plan.totals.minutes}) : t('alerts.plan.noLegs', lang)}</p>
    </>}
  </div>;
}

export function SavedTrips({recaps, names, remove, useAgain, read = {loading: false, complete: true}, events = [], timeZone = DEFAULT_ZONE}: {recaps: ReturnType<typeof tripRecaps>; names: AlertNames; remove: (id: string) => () => void; useAgain: (trip: SavedTrip) => void; read?: CatchRead; events?: AlertEvent[]; timeZone?: string}) {
  const lang = language.value, only = englishOnly(lang);
  const standing = (trip: SavedTrip) => {
    const e = latestTripEvent(events, trip.id), at = e ? assessmentTimeOrNull(e, timeZone, lang) : null;
    const when = e && (at === null ? t('alerts.timeUnavailable', lang) : <time dateTime={e.created_at}>{at}</time>);
    return <><br /><span class="small">{savedTripLimits(trip, lang)} · {e ? <>{eventLine(e, lang)} · {when}</> : t('alerts.noRecent', lang)}</span></>;
  };
  const deletion = (trip: SavedTrip) => <Button size="sm" variant="quiet" onClick={remove(trip.id)} aria-label={t('alerts.deleteAria', lang, {date: trip.date, point: names.point.get(trip.point) ?? trip.point})}>{t('alerts.delete', lang)}</Button>;
  const again = (trip: SavedTrip) => <Button type="button" size="sm" variant="quiet" onClick={() => useAgain(trip)} aria-label={t('alerts.againAria', lang, {date: trip.date, point: names.point.get(trip.point) ?? trip.point})}>{t('alerts.again', lang)}</Button>;
  const planOf = (trip: SavedTrip) => { const s = tripPlanSummary(trip, names, lang); return s ? <SavedPlan plan={s} lang={lang} /> : null; };
  return <div id="saved-trips">
    {!recaps.upcoming.length && !recaps.past.length ? <p>{t('alerts.none', lang)}</p> : null}
    {recaps.upcoming.length ? <><h3>{t('alerts.upcoming', lang)}</h3>{recaps.upcoming.map(trip => {
      const row = <p key={trip.id}><strong>{tripLine(trip, names, lang)}</strong> {deletion(trip)} {again(trip)}{standing(trip)}</p>;
      const plan = planOf(trip);
      return plan ? <div key={trip.id}>{row}{plan}</div> : row;
    })}</> : null}
    {recaps.past.length ? <><h3>{t('alerts.past', lang)}</h3>
      <p class="small">{t('alerts.pastNote', lang)}</p>
      {read.loading ? <p class="small">{t('alerts.catchReading', lang)}</p> : !read.complete ? <p class="small">{t('alerts.catchPartial', lang)}</p> : null}
      {recaps.past.map(({trip, final, reports, catches}) => <article key={trip.id}>
        <details><summary>{tripLine(trip, names, lang)}</summary>
          {planOf(trip)}
          {final ? <><strong>{eventLine(final, lang)}</strong><p lang={only} style={{whiteSpace: 'pre-line'}}>{final.message}</p></> : <p>{t('alerts.noFinal', lang)}</p>}
          {reports.length ? <><h4>{t('alerts.comfortReports', lang)}</h4>{reports.map((f, i) => <p key={i}>{f.rating}/10 · {feedbackPhase(f, lang)}</p>)}</> : null}
          {catches.length ? <><h4>{t('alerts.catchLog', lang)}</h4><ul>{catches.map(c => <li key={c.id}>{catchLine(c, lang)}</li>)}</ul></> : null}
        </details>{deletion(trip)} {again(trip)}
      </article>)}
    </> : null}
  </div>;
}

function SignedIn({session, region, boat, target}: {session: SessionAnswer; region: RegionAlerts; boat: Boat; target: string | null}) {
  const lang = language.value, only = englishOnly(lang);
  const [p] = useState(() => profile.peek());
  const saved = p === 'boat' ? tripBoat(boat.factors, boat.saved?.boat) : null;
  // Own Boat limits are absolute, so they start the form as saved (clamped to the server's ranges) and are never scaled by the boat's factors.
  // Decided once at mount: a later signal change must not replace typed thresholds or make the note describe another source.
  const [{ownBoatLimits, limits}] = useState(() => {
    const own = p === 'boat' && hasOwnLimits('boat');
    return {ownBoatLimits: own, limits: own || p !== 'boat' ? profileTripDefaults(limitsFor(p)) : tripDefaults(boat.factors)};
  });
  const choice = alertSpecies(region, target, lang), names = useMemo(() => alertNames(region), [region]), range = dateRange(region.timezone);
  const [species, setSpecies] = useState(choice.value);
  const [status, setStatus] = useState<Say>(null);
  const [stopping, setStopping] = useState(false);
  const [device, setDevice] = useState<DeviceStatus | null>(null);
  const checkDevice = useMemo(() => latestCheck<DeviceStatus>(() => deviceStatus(), setDevice, () => 'unchecked'), []);
  useEffect(checkDevice, []);
  const [trips, setTrips] = useState<{trips: SavedTrip[]; events: AlertEvent[]} | null>(null);
  const digest = trips ? weekendDigest(trips.trips, names, range.min, lang) : null;
  const [feedback, setFeedback] = useState<Feedback[] | null>(null);
  const [catchRead, setCatchRead] = useState<RecapCatchLog & {loading: boolean}>({entries: [], complete: false, loading: true});
  const [comfortStatus, setComfortStatus] = useState<Say>(null);
  const [confirming, setConfirming] = useState(false);
  const privacy = useRef<HTMLDetailsElement>(null);
  const formRef = useRef<HTMLFormElement>(null);
  const [reuse, setReuse] = useState<{omitted: ReuseOmission[]; date: string; copied: 'all' | 'some' | 'none'} | null>(null);
  const unavailable = !region.forecast_points.length || !region.species.length;
  /** Use again: fills the form from a saved trip's still-available parts, clears the date and focuses it. Sends and saves nothing. */
  const useAgain = (trip: SavedTrip) => {
    const form = formRef.current, r = reuseTrip(trip, region);
    if (!form) return;
    fillAlertForm(form as unknown as FillableForm, r);
    if (r.species !== null) setSpecies(r.species);
    setStatus(null);
    setReuse({omitted: r.omitted, date: trip.date, copied: reusedLimits(r.fields)});
  };
  /** Cancel returns focus to the button that asked. */
  const keep = () => { setConfirming(false); requestAnimationFrame(() => privacy.current?.querySelector<HTMLButtonElement>('[data-delete-account]')?.focus()); };
  const fail = (error: unknown) => setStatus(sayError(error));
  const refresh = () => api<{trips: SavedTrip[]; events: AlertEvent[]}>('trips').then(setTrips, fail);
  const refreshFeedback = () => api<{feedback: Feedback[]}>('comfort').then(d => setFeedback(d.feedback), () => {});
  useEffect(() => { void refresh(); void refreshFeedback(); }, []);
  // GET /api/catch-log: this person's own log, read page by page (readRecapCatchLog) once per mount for the past-trip recap.
  // Closing the dialog aborts the chain; a stopped read keeps what it read and says so instead of implying nothing was logged.
  useEffect(() => {
    const ctl = new AbortController();
    void readRecapCatchLog(fetch, ctl.signal).then(r => { if (!ctl.signal.aborted) setCatchRead({...r, loading: false}); });
    return () => ctl.abort();
  }, []);

  const save = async (event: TargetedSubmitEvent<HTMLFormElement>) => {
    event.preventDefault();
    const f = new FormData(event.currentTarget);
    const form: AlertForm = {date: String(f.get('date')), point: String(f.get('point')), start_hour: hours(f.get('start_hour')), end_hour: hours(f.get('end_hour')),
      wind_limit: hours(f.get('wind_limit')), gust_limit: hours(f.get('gust_limit')), sea_limit: hours(f.get('sea_limit'))};
    const problem = formProblemId(form, dateRange(region.timezone));
    if (problem) { setStatus({id: problem}); return; }
    if (!region.forecast_points.some(point => point.id === form.point) || !region.species.includes(species)) { setStatus({id: 'alerts.status.choose'}); return; }
    try {
      await api('trips', {method: 'POST', body: JSON.stringify(tripBody(form, region.id, species, saved))});
      setStatus({id: 'alerts.status.saved'});
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
    setStatus({id: 'alerts.status.deleted'});
    setTimeout(() => location.reload(), 1200);
  });
  const sendComfort = async (event: TargetedSubmitEvent<HTMLFormElement>) => {
    event.preventDefault();
    const f = new FormData(event.currentTarget);
    try {
      await api('comfort', {method: 'POST', body: JSON.stringify(comfortBody(region.id, Number(f.get('rating')), String(f.get('phase'))))});
      setComfortStatus({id: 'alerts.status.comfort'});
      void refreshFeedback();
    } catch (error) { setComfortStatus(sayError(error)); }
  };

  return (
    <>
      {lang === 'es' ? <p class="small" id="alerts-english">{t('alerts.english', lang)}</p> : null}
      <label>{t('alerts.species', lang)}
        <select id="species-select" value={species} onChange={e => setSpecies(e.currentTarget.value)}>
          {[...new Set(choice.options.map(o => o.group))].map(group => (
            <optgroup key={group} label={group}>{choice.options.filter(o => o.group === group).map(o => <option key={o.id} value={o.id}>{o.name}</option>)}</optgroup>
          ))}
        </select>
      </label>
      <details class="insight-card" open>
        <summary>{t('alerts.myAlerts', lang)}</summary>
        <form id="save-alert" ref={formRef} class="insight-form" onSubmit={e => void save(e)}>
          <label>{t('alerts.date', lang)}<input name="date" type="date" defaultValue={alertDate(region.timezone)} min={range.min} max={range.max} required /></label>
          <label>{t('alerts.area', lang)}<select name="point">{region.forecast_points.map(point => <option key={point.id} value={point.id}>{point.name}</option>)}</select></label>
          <label>{t('alerts.from', lang)}<input name="start_hour" type="number" min="0" max="22" defaultValue="7" required /></label>
          <label>{t('alerts.until', lang)}<input name="end_hour" type="number" min="1" max="23" defaultValue="13" required /></label>
          <label>{t('alerts.wind', lang)}<input name="wind_limit" type="number" min="1" max="30" defaultValue={limits.wind} required /></label>
          <label>{t('alerts.gust', lang)}<input name="gust_limit" type="number" min="1" max="40" defaultValue={limits.gust} required /></label>
          <label>{t('alerts.sea', lang)}<input name="sea_limit" type="number" min="0.5" max="10" step="0.5" defaultValue={limits.sea} required /></label>
          <Button type="submit" variant="primary" disabled={unavailable}>{t('alerts.save', lang)}</Button>
        </form>
        <p id="reuse-status" role="status" class="small">{reuse ? reuseStatus(reuse.omitted, lang) : ''}</p>
        <p class="small" id="trip-boat-note">{reuse && reuse.copied !== 'none' ? reuseLimitsNote(reuse.date, reuse.copied, p === 'boat', lang) : p !== 'boat'
          ? t('alerts.noteNonBoat', lang, {profile: t(`where.profile.${p}` as StringId, lang)})
          : ownBoatLimits
          ? t(saved ? 'alerts.noteOwnSaved' : 'alerts.noteOwnNone', lang, {profile: t('where.profile.boat', lang)})
          : saved
          ? (saved.name ? t('alerts.noteSaved', lang, {name: saved.name}) : t('alerts.noteSavedUnnamed', lang))
          : t('alerts.noteReference', lang)}</p>
        <p class="small">{t('alerts.purpose', lang)}</p>
        <div class="inavx-actions">
          {deviceButtons(device).enable ? <Button size="sm" onClick={() => { enablePush(session.publicKey).then(() => setStatus({id: 'alerts.status.enabled'}), fail).finally(checkDevice); }}>{t('alerts.enable', lang)}</Button> : null}
          {(['device', 'all'] as const).filter(scope => scope === 'all' || deviceButtons(device).stopDevice).map(scope => <Button key={scope} size="sm" disabled={stopping} onClick={() => { setStopping(true); stopNotificationsId(scope).then(id => setStatus({id}), fail).finally(() => { setStopping(false); checkDevice(); }); }}>{t(scope === 'device' ? 'alerts.stopDevice' : 'alerts.stopAll', lang)}</Button>)}
        </div>
        <p id="device-status" role="status" class="small">{device ? deviceLine(device, lang) : ''}</p>
        <p id="alert-status" role="status"><Said say={status} lang={lang} /></p>
        {digest ? <section aria-labelledby="weekend-heading">
          <h3 id="weekend-heading">{t('alerts.weekend', lang)}</h3>
          <p style={{whiteSpace: 'pre-line'}}>{toText(digest, lang)}</p>
          <p class="small">{t('alerts.weekendNote', lang)}</p>
        </section> : null}
        {trips ? <SavedTrips recaps={tripRecaps(trips.trips, trips.events, feedback ?? [], dateRange(DEFAULT_ZONE).min, catchRead.entries)} names={names} remove={remove} useAgain={useAgain} read={catchRead} events={trips.events} timeZone={region.timezone} /> : <div id="saved-trips" />}
        {trips?.events.length ? (
          <details id="alert-history">
            <summary>{t('alerts.recent', lang, {n: trips.events.length})}</summary>
            {trips.events.map(e => (
              <article key={e.id}>
                <strong>{eventLine(e, lang)}</strong>
                <p lang={only} style={{whiteSpace: 'pre-line'}}>{e.message}</p>
                {!['read', 'delivered'].includes(e.status) ? <Button size="sm" variant="quiet" onClick={ack(e.id)}>{t('alerts.markRead', lang)}</Button> : null}
              </article>
            ))}
          </details>
        ) : null}
        <details ref={privacy}>
          <summary>{t('alerts.privacy.summary', lang)}</summary>
          <p>{t('alerts.privacy.body', lang)}</p>
          <Button size="sm" onClick={exportRecords}>{t('alerts.export', lang)}</Button>{' '}
          <Button data-delete-account size="sm" disabled={confirming} onClick={() => setConfirming(true)}>{t('alerts.deleteAccount', lang)}</Button>{' '}
          <a href="#account">{t('alerts.accountLink', lang)}</a>
          {confirming ? <ConfirmDelete onConfirm={deleteAll} onCancel={keep} /> : null}
        </details>
      </details>
      <details id="comfort-feedback">
        <summary>{t('alerts.comfort.title', lang)}</summary>
        <form id="comfort-form" class="insight-form" onSubmit={e => void sendComfort(e)}>
          <label>{t('alerts.comfort.phase', lang)}<select name="phase"><option value="outbound">{t('alerts.comfort.outbound', lang)}</option><option value="fishing">{t('alerts.comfort.fishing', lang)}</option><option value="return">{t('alerts.comfort.return', lang)}</option></select></label>
          <label>{t('alerts.comfort.rating', lang)}<input name="rating" type="number" min="1" max="10" defaultValue="7" required /></label>
          <Button type="submit">{t('alerts.comfort.save', lang)}</Button>
        </form>
        <p id="comfort-status" role="status"><Said say={comfortStatus} lang={lang} /></p>
        {feedback ? (
          <div id="comfort-history">
            <p class="small">{t('alerts.comfort.history', lang, {n: feedback.length})}</p>
            {feedback.slice(0, 5).map((f, i) => <p key={i}>{new Date(f.observed_at).toLocaleDateString(lang === 'es' ? localeOf(lang) : undefined)} · {f.rating}/10 · {feedbackPhase(f, lang)}</p>)}
          </div>
        ) : null}
      </details>
    </>
  );
}

/** The alerts dialog's body for `regionId`; the alert species starts on the app's target when the region lists it. */
export function TripAlerts({regionId, target}: {regionId: string; target: string | null}) {
  const [loaded, setLoaded] = useState<Loaded>({state: 'loading'});
  const lang = language.value;
  useEffect(() => {
    let live = true;
    setLoaded({state: 'loading'});
    load(regionId).then(l => { if (live) setLoaded(l); }, (e: Error) => { if (live) setLoaded({state: 'error', say: sayError(e)}); });
    return () => { live = false; };
  }, [regionId]);
  return (
    <div class="app-alerts" id="trip-alerts">
      {loaded.state === 'loading' ? <p role="status">{t('alerts.loading', lang)}</p>
        : loaded.state === 'error' ? <p role="status"><Said say={loaded.say} lang={lang} /></p>
        : loaded.state === 'offline' ? <p>{t('alerts.offline', lang)}</p>
        : loaded.state === 'disabled' ? <p>{t('alerts.disabled', lang)}</p>
        : loaded.state === 'signed-out' ? <SignedOut href={loaded.href} />
        : <SignedIn session={loaded.session} region={loaded.region} boat={loaded.boat} target={target} />}
    </div>
  );
}
