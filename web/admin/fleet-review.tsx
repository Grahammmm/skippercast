// The charter fleet's review queue (docs/plans/charter-fleet/design.md § 13, Fleet
// review; CF-31) at #fleet-review (?region=<id>): items by kind, newest first, from
// GET /api/admin/fleet/reviews. Each card shows the candidate's facts beside the
// proposed vessel with the score and its basis (and parts, when a run records them),
// and offers only the actions the server lists for its kind
// (server/fleet/admin/reviews.ts ACTIONS_BY_KIND): same vessel, new vessel, set or
// reject MMSI, set class, mark vanished or active, out of scope, confirm, dismiss.
// A decision is POST /api/admin/fleet/reviews/:id. Strings: ./fleet-copy.ts.
import {useEffect, useState} from 'preact/hooks';
import type {ComponentChildren, JSX} from 'preact';
import {ADMIN_COPY} from '../advisor/copy.ts';
import {FLEET_COPY as COPY} from './fleet-copy.ts';
import {ApiError, FLEET_REVIEW_KINDS, FLEET_REVIEW_STATUSES, VESSEL_CLASSES, VESSEL_STATUSES, decideFleetReview, getFleetReviews, httpsUrl, valueText, when} from './api.ts';
import type {FleetAction, FleetDecision, FleetReview} from './api.ts';
import {fleetHref, fleetVesselHref} from './route.ts';

const cardId = (id: string): string => `fleet-review-${id}`;
const errorText = (e: unknown): string => (e instanceof ApiError && e.status !== 500 ? e.message : ADMIN_COPY.decisionFailed);
const record = (value: unknown): Record<string, unknown> => (value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {});
const HEX32 = /^[0-9a-f]{32}$/;
const score = (n: unknown): string => (typeof n === 'number' ? n.toFixed(2) : '');

export function FleetReviewView({region}: {region: string}) {
  const [status, setStatus] = useState('open');
  const [kind, setKind] = useState('');
  const [items, setItems] = useState<FleetReview[]>([]);
  const [next, setNext] = useState<string | null>(null);
  const [state, setState] = useState<'loading' | 'ready' | 'failed'>('loading');
  const [notice, setNotice] = useState('');

  async function load(cursor: string | null = null): Promise<void> {
    if (!cursor) setState('loading');
    try {
      const page = await getFleetReviews(status, kind, region, cursor);
      setItems(all => (cursor ? [...all, ...page.reviews] : page.reviews));
      setNext(page.next);
      setState('ready');
    } catch { setState('failed'); }
  }
  useEffect(() => { void load(); }, [status, kind, region]);

  function decided(item: FleetReview, result: {review: FleetReview; repeated?: true}, label: string): void {
    const index = items.findIndex(i => i.id === item.id);
    const stays = status === 'all' || result.review.status === status;
    const rest = stays ? items.map(i => (i.id === item.id ? {...i, ...result.review, actions: []} : i)) : items.filter(i => i.id !== item.id);
    setItems(rest);
    setNotice(result.repeated ? COPY.repeated : COPY.decidedAs(label));
    const following = stays ? item : rest[Math.min(index, rest.length - 1)];
    requestAnimationFrame(() => document.getElementById(following ? cardId(following.id) : 'fleet-review-heading')?.focus());
  }

  return (
    <section class="admin-view" aria-labelledby="fleet-review-heading">
      <h1 id="fleet-review-heading" tabIndex={-1}>{COPY.reviewHeading}</h1>
      <p class="admin-hint">{COPY.reviewHelp}</p>
      <div class="admin-filters">
        <label>
          <span>{COPY.kindLabel}</span>
          <select value={kind} onChange={e => setKind((e.currentTarget as HTMLSelectElement).value)}>
            <option value="">{COPY.allKinds}</option>
            {FLEET_REVIEW_KINDS.map(k => <option key={k} value={k}>{COPY.kinds[k]}</option>)}
          </select>
        </label>
        <label>
          <span>{COPY.statusLabel}</span>
          <select value={status} onChange={e => setStatus((e.currentTarget as HTMLSelectElement).value)}>
            {FLEET_REVIEW_STATUSES.map(s => <option key={s} value={s}>{COPY.reviewStatuses[s]}</option>)}
          </select>
        </label>
        <RegionFilter region={region} onChange={r => { location.hash = fleetHref('fleet-review', r); }} />
      </div>
      <p class="admin-notice" role="status">{notice}</p>
      {state === 'loading' ? <p>{ADMIN_COPY.loading}</p> : state === 'failed' ? <p class="admin-error" role="alert">{ADMIN_COPY.loadFailed}</p> : items.length === 0 ? <p>{COPY.reviewsNone}</p> : (
        <ol class="admin-queue">
          {items.map(item => <li key={item.id}><FleetReviewCard review={item} onDecided={(result, label) => decided(item, result, label)} /></li>)}
        </ol>
      )}
      {next && state === 'ready' ? <button type="button" class="admin-button" onClick={() => void load(next)}>{ADMIN_COPY.more}</button> : null}
    </section>
  );
}

/** The region filter shared by the fleet list views: the route carries it (?region=), so a filtered view is a link. */
export function RegionFilter({region, onChange}: {region: string; onChange: (region: string) => void}) {
  return (
    <label>
      <span>{COPY.regionLabel}</span>
      <input type="text" maxLength={64} value={region} placeholder={COPY.regionHint} onChange={e => onChange((e.currentTarget as HTMLInputElement).value.trim())} />
    </label>
  );
}

/** A JSON value as nested definition lists; https strings become links (anything else is text). */
export function JsonValue({value}: {value: unknown}): JSX.Element {
  if (Array.isArray(value)) {
    if (value.every(v => v === null || typeof v !== 'object')) return <>{valueText(value)}</>;
    return <ul class="admin-crew">{value.map((v, i) => <li key={i}><JsonValue value={v} /></li>)}</ul>;
  }
  if (value && typeof value === 'object') {
    const entries = Object.entries(value as Record<string, unknown>).filter(([, v]) => v !== null && v !== undefined && v !== '');
    return <dl class="admin-fields">{entries.map(([k, v]) => <Pair key={k} label={k}><JsonValue value={v} /></Pair>)}</dl>;
  }
  const link = httpsUrl(value);
  return link ? <a href={link} target="_blank" rel="noopener noreferrer">{link}</a> : <>{valueText(value)}</>;
}

export function Pair({label, children}: {label: string; children: ComponentChildren}) {
  return <><dt>{label}</dt><dd>{children}</dd></>;
}

function FleetReviewCard({review, onDecided}: {review: FleetReview; onDecided: (result: {review: FleetReview; repeated?: true}, label: string) => void}) {
  const candidate = record(review.candidate), proposal = record(review.proposal);
  const choices = (Array.isArray(proposal.vessels) ? proposal.vessels : []).map(record)
    .filter(v => typeof v.vessel_id === 'string' && HEX32.test(v.vessel_id));
  const proposed = typeof proposal.vessel_id === 'string' && HEX32.test(proposal.vessel_id) ? proposal.vessel_id : '';
  const [vessel, setVessel] = useState(proposed || String(choices[0]?.vessel_id ?? ''));
  const [mmsi, setMmsi] = useState(typeof candidate.mmsi === 'string' ? candidate.mmsi : '');
  const [vesselClass, setVesselClass] = useState(typeof proposal.vessel_class === 'string' ? proposal.vessel_class : VESSEL_CLASSES[0]);
  const [vesselStatus, setVesselStatus] = useState<string>(VESSEL_STATUSES[0]);
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const actions = review.status === 'open' ? review.actions ?? [] : [];
  const idBase = cardId(review.id), headingId = `${idBase}-title`;

  async function submit(decision: FleetDecision, label: string): Promise<void> {
    if (busy) return;
    setBusy(true); setError('');
    try {
      const result = await decideFleetReview(review.id, note.trim() ? {...decision, note: note.trim()} : decision);
      onDecided(result, label);
    } catch (e) { setError(errorText(e)); }
    finally { setBusy(false); }
  }
  const has = (action: FleetAction): boolean => actions.includes(action);
  const button = (decision: FleetDecision, label: string, tone = ''): JSX.Element => (
    <button type="button" class={`admin-button${tone ? ` ${tone}` : ''}`} disabled={busy} onClick={() => void submit(decision, label)}>{label}</button>
  );
  // vanished and scope reviews offer their two statuses as buttons; a change review picks a status.
  const fixedStatus = review.kind === 'vanished' || review.kind === 'scope';
  const {vessels: _vessels, parts, basis, vessel_id: _vesselId, ...proposalRest} = proposal;

  return (
    <article id={idBase} class="admin-card" tabIndex={-1} aria-labelledby={headingId}>
      <header class="admin-card-head">
        <h2 id={headingId}>{COPY.kinds[review.kind] ?? review.kind} <span class="admin-reason">{review.region}</span></h2>
        <p class="admin-meta">
          {ADMIN_COPY.opened(when(review.opened_at))}
          {review.status !== 'open' ? ` · ${COPY.reviewStatuses[review.status]}${review.decided_at ? ` · ${COPY.decidedAt(when(review.decided_at))}` : ''}` : ''}
        </p>
      </header>
      <dl class="admin-fields">
        <Pair label={COPY.subject}>{review.subject_name && review.subject_id
          ? <a href={fleetVesselHref(review.subject_id)}>{review.subject_name}</a>
          : review.kind === 'advisor-link' && review.subject_id ? COPY.advisorBoat(review.subject_id) : review.subject_id ?? '—'}</Pair>
        {review.score !== null ? <Pair label={COPY.score}>{score(review.score)}</Pair> : null}
        {parts && typeof parts === 'object' ? <Pair label={COPY.scoreParts}><JsonValue value={parts} /></Pair> : null}
        {typeof basis === 'string' ? <Pair label={COPY.basis}>{basis}</Pair> : null}
      </dl>
      <div class="admin-media">
        <section aria-labelledby={`${idBase}-candidate`}>
          <h3 id={`${idBase}-candidate`}>{COPY.candidate}</h3>
          {Object.keys(candidate).length ? <JsonValue value={candidate} /> : <p class="admin-hint">—</p>}
        </section>
        <section aria-labelledby={`${idBase}-proposal`}>
          <h3 id={`${idBase}-proposal`}>{COPY.proposal}</h3>
          {proposed && !choices.length ? <p>{proposed === review.subject_id ? COPY.subjectItself : <a href={fleetVesselHref(proposed)}>{proposed}</a>}</p> : null}
          {Object.keys(proposalRest).length ? <JsonValue value={proposalRest} /> : null}
          {choices.length ? (has('same-vessel') ? (
            <fieldset class="admin-targets">
              <legend>{COPY.chooseVessel}</legend>
              {choices.map(c => {
                const id = String(c.vessel_id), name = String(c.name ?? id);
                return (
                  <p key={id}>
                    <label class="admin-check">
                      <input type="radio" name={`${idBase}-vessel`} value={id} checked={vessel === id} onChange={() => setVessel(id)} />
                      {name}{typeof c.score === 'number' ? ` · ${score(c.score)}` : ''}
                    </label>
                    {' '}<a href={fleetVesselHref(id)}>{COPY.openVessel(name)}</a>
                  </p>
                );
              })}
            </fieldset>
          ) : (
            <ul class="admin-crew" aria-label={COPY.candidates}>
              {choices.map(c => <li key={String(c.vessel_id)}><a href={fleetVesselHref(String(c.vessel_id))}>{String(c.name ?? c.vessel_id)}</a>
                {typeof c.score === 'number' ? ` · ${score(c.score)}` : ''}</li>)}
            </ul>
          )) : null}
        </section>
      </div>
      {review.decision ? <dl class="admin-fields"><Pair label={COPY.decisionLabel}><JsonValue value={review.decision} /></Pair></dl> : null}
      {actions.length ? (
        <div class="admin-actions">
          <label class="admin-note">
            <span>{COPY.noteLabel}</span>
            <input type="text" maxLength={2000} value={note} onInput={e => setNote((e.currentTarget as HTMLInputElement).value)} />
          </label>
          {has('same-vessel') ? button(review.kind === 'merge' && vessel ? {action: 'same-vessel', vessel_id: vessel} : {action: 'same-vessel'},
            COPY.actions['same-vessel']!, 'is-primary') : null}
          {has('new-vessel') ? button({action: 'new-vessel'}, COPY.actions['new-vessel']!) : null}
          {has('set-mmsi') || has('reject-mmsi') ? (
            <label class="admin-note">
              <span>{COPY.fieldLabels.mmsi}</span>
              <input type="text" inputMode="numeric" maxLength={9} value={mmsi} onInput={e => setMmsi((e.currentTarget as HTMLInputElement).value.trim())} />
            </label>
          ) : null}
          {has('set-mmsi') ? button({action: 'set-mmsi', ...(mmsi ? {mmsi} : {})}, COPY.actions['set-mmsi']!, 'is-primary') : null}
          {has('reject-mmsi') ? button({action: 'reject-mmsi', ...(mmsi ? {mmsi} : {})}, COPY.actions['reject-mmsi']!) : null}
          {has('set-class') ? (
            <label class="admin-note">
              <span>{COPY.fieldLabels.vessel_class}</span>
              <select value={vesselClass} onChange={e => setVesselClass((e.currentTarget as HTMLSelectElement).value)}>
                {VESSEL_CLASSES.map(c => <option key={c} value={c}>{COPY.classes[c]}</option>)}
              </select>
            </label>
          ) : null}
          {has('set-class') ? button({action: 'set-class', vessel_class: vesselClass}, COPY.actions['set-class']!, 'is-primary') : null}
          {has('set-status') && review.kind === 'vanished' ? button({action: 'set-status', status: 'inactive'}, COPY.markVanished, 'is-primary') : null}
          {has('set-status') && review.kind === 'scope' ? button({action: 'set-status', status: 'excluded'}, COPY.outOfScope, 'is-primary') : null}
          {has('set-status') && fixedStatus ? button({action: 'set-status', status: 'active'}, COPY.markActive) : null}
          {has('set-status') && !fixedStatus ? (
            <label class="admin-note">
              <span>{COPY.fieldLabels.status}</span>
              <select value={vesselStatus} onChange={e => setVesselStatus((e.currentTarget as HTMLSelectElement).value)}>
                {VESSEL_STATUSES.map(s => <option key={s} value={s}>{COPY.vesselStatuses[s]}</option>)}
              </select>
            </label>
          ) : null}
          {has('set-status') && !fixedStatus ? button({action: 'set-status', status: vesselStatus}, COPY.actions['set-status']!) : null}
          {has('confirm') ? button({action: 'confirm'}, COPY.actions.confirm!, 'is-primary') : null}
          {has('dismiss') ? button({action: 'dismiss'}, COPY.actions.dismiss!, 'is-danger') : null}
        </div>
      ) : null}
      {error ? <p class="admin-error" role="alert">{error}</p> : null}
    </article>
  );
}
