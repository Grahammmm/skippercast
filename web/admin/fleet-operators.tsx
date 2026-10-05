// The fleet admin's operators and outreach (docs/plans/charter-fleet/design.md § 13; D14,
// US-S1..S4; CF-32): #fleet-operators ranks operators by lead score with its parts;
// #fleet-operator/<id> shows contact, consent (who and when), outreach status, notes and
// drafts. Nothing here sends a message: a draft is approved, discarded, or logged once
// the owner has sent it themselves (server/fleet/admin/operators.ts).
import {useEffect, useState} from 'preact/hooks';
import {ApiError, getFleet, postFleet, when} from './api.ts';
import {fleetVesselHref} from './route.ts';

const CONSENT = ['unknown', 'contacted', 'declined', 'content-sharing', 'partner'] as const;
const OUTREACH = ['none', 'drafted', 'contacted', 'declined', 'replied', 'partner', 'do-not-contact'] as const;
const SCOPES = ['profile', 'photos', 'catch-logs', 'offerings', 'social-posts'] as const;
const KINDS = ['note', 'draft', 'reply'] as const;
const CHANNELS = ['email', 'phone', 'instagram', 'facebook', 'in-person', 'other'] as const;
const COPY = {
  heading: 'Operators', loading: 'Loading…', failed: 'Could not load. Try again.', none: 'No operators match.', saved: 'Saved.',
  filter: 'Outreach status', all: 'All', score: 'Lead score', outreach: 'Outreach', consent: 'Consent', vessels: 'Boats', lastTouch: 'Last touch', drafts: 'Open drafts',
  revoked: (at: string) => `revoked ${at}`, missing: 'missing, counted as zero', parts: 'Lead score parts', part: 'Input', raw: 'Value', points: 'Points',
  partNames: {landing_report_volume: 'Landing-report trips (365 days)', reporting_frequency: 'Weeks with a report (of 12)',
    social_presence: 'Social link on own site', ais_seen_30d: 'AIS seen in 30 days'} as Record<string, string>,
  contact: 'Contact', website: 'Website', phone: 'Business phone', email: 'Business email', recorded: (by: string, at: string) => `recorded by ${by}, ${at}`,
  scope: 'Scope', consentNote: 'How consent was given or withdrawn', saveConsent: 'Record consent', revoke: 'Revoke consent', saveStatus: 'Set status',
  log: 'Notes and drafts', logNone: 'Nothing logged yet.', kind: 'Kind', channel: 'Channel', body: 'Text', add: 'Add',
  neverSent: 'Drafts are never sent from here. Send it yourself, then log it as sent.', dnc: 'Do not contact: no new drafts.',
  approve: 'Approve', discard: 'Discard', logSent: 'Log as sent by owner', by: (by: string, at: string) => `${by}, ${at}`,
};

type Part = {part: string; raw: number | null; points: number; missing: boolean};
interface Lead {score: number; parts: Part[]; missing: string[]}
interface OperatorRow {id: string; name: string; outreach_status: string; consent_status: string; consent_revoked_at: string | null; vessels: number;
  last_touch: string | null; open_drafts: number; lead_score: Lead}
interface Outreach {id: string; kind: string; channel: string | null; body: string; status: string; created_by: string; created_at: string; approved_by: string | null; approved_at: string | null}
interface OperatorDetail {
  operator: {id: string; name: string; website: string | null; phone_business: string | null; email_business: string | null; consent_status: string;
    consent_scope: {scope: string[]; note: string} | null; consent_recorded_at: string | null; consent_recorded_by: string | null; consent_revoked_at: string | null; outreach_status: string};
  vessels: {id: string; name: string}[]; lead_score: Lead; outreach: Outreach[];
}
/** The nav and page-title label of the operator views (web/admin/app.tsx FLEET_PAGES). */
export const OPERATORS_LABEL = COPY.heading;
const errorText = (e: unknown): string => (e instanceof ApiError && e.status !== 500 ? e.message : COPY.failed);
const value = (e: Event): string => (e.currentTarget as HTMLInputElement).value;

export function FleetOperatorsView({region}: {region: string}) {
  const [status, setStatus] = useState('');
  const [rows, setRows] = useState<OperatorRow[] | null | 'failed'>(null);
  useEffect(() => {
    setRows(null);
    getFleet<{operators: OperatorRow[]}>('operators', {region, outreach_status: status}).then(r => setRows(r.operators), () => setRows('failed'));
  }, [region, status]);
  return (
    <section class="admin-view" aria-labelledby="fleet-operators-heading">
      <h1 id="fleet-operators-heading" tabIndex={-1}>{COPY.heading}</h1>
      <div class="admin-filters"><label for="fleet-operators-status">{COPY.filter}
        <select id="fleet-operators-status" value={status} onChange={e => setStatus(value(e))}>
          <option value="">{COPY.all}</option>{OUTREACH.map(s => <option key={s} value={s}>{s}</option>)}
        </select></label></div>
      {rows === null ? <p>{COPY.loading}</p> : rows === 'failed' ? <p class="admin-error" role="alert">{COPY.failed}</p> : !rows.length ? <p>{COPY.none}</p> : (
        <div class="admin-scroll" tabIndex={0} role="region" aria-label={COPY.heading}><table class="admin-counts">
          <thead><tr><th scope="col">{COPY.heading}</th><th scope="col">{COPY.score}</th><th scope="col">{COPY.outreach}</th><th scope="col">{COPY.consent}</th>
            <th scope="col">{COPY.vessels}</th><th scope="col">{COPY.lastTouch}</th><th scope="col">{COPY.drafts}</th></tr></thead>
          <tbody>{rows.map(o => (
            <tr key={o.id}>
              <th scope="row"><a href={`#fleet-operator/${encodeURIComponent(o.id)}`}>{o.name}</a></th>
              <td title={o.lead_score.parts.map(p => `${COPY.partNames[p.part]}: ${p.points}${p.missing ? ` (${COPY.missing})` : ''}`).join('\n')}>{o.lead_score.score}</td>
              <td>{o.outreach_status}</td>
              <td>{o.consent_status}{o.consent_revoked_at ? ` (${COPY.revoked(when(o.consent_revoked_at))})` : ''}</td>
              <td>{o.vessels}</td><td>{when(o.last_touch)}</td><td>{o.open_drafts}</td>
            </tr>
          ))}</tbody>
        </table></div>
      )}
    </section>
  );
}

export function FleetOperatorView({id}: {id: string}) {
  const [detail, setDetail] = useState<OperatorDetail | null | 'failed'>(null);
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const load = (): Promise<void> => getFleet<OperatorDetail>(`operators/${encodeURIComponent(id)}`).then(setDetail, () => setDetail('failed'));
  useEffect(() => { void load(); }, [id]);

  async function run(path: string, body: Record<string, unknown>): Promise<boolean> {
    if (busy) return false;
    setBusy(true); setError(''); setNotice('');
    try { await postFleet(path, body); await load(); setNotice(COPY.saved); return true; } catch (e) { setError(errorText(e)); return false; } finally { setBusy(false); }
  }
  if (detail === null) return <p>{COPY.loading}</p>;
  if (detail === 'failed') return <p class="admin-error" role="alert">{COPY.failed}</p>;
  const {operator: op, lead_score: lead} = detail, base = `operators/${encodeURIComponent(id)}`;
  return (
    <section class="admin-view" aria-labelledby="fleet-operator-heading">
      <h1 id="fleet-operator-heading" tabIndex={-1}>{op.name} <span class="admin-reason">{COPY.score} {lead.score}</span></h1>
      <p class="admin-notice" role="status">{notice}</p>
      {error ? <p class="admin-error" role="alert">{error}</p> : null}
      <table class="admin-counts" aria-label={COPY.parts}><thead><tr><th scope="col">{COPY.part}</th><th scope="col">{COPY.raw}</th><th scope="col">{COPY.points}</th></tr></thead>
        <tbody>{lead.parts.map(p => <tr key={p.part}><th scope="row">{COPY.partNames[p.part]}</th><td>{p.missing ? COPY.missing : p.raw}</td><td>{p.points}</td></tr>)}</tbody></table>
      <dl class="admin-fields">
        <dt>{COPY.contact}</dt><dd>{[op.website, op.phone_business, op.email_business].filter(Boolean).join(' · ') || '—'}</dd>
        <dt>{COPY.vessels}</dt><dd>{detail.vessels.map(v => <a key={v.id} href={fleetVesselHref(v.id)}>{v.name} </a>)}</dd>
        <dt>{COPY.consent}</dt><dd>{op.consent_status}{op.consent_scope?.scope.length ? ` · ${op.consent_scope.scope.join(', ')}` : ''}
          {op.consent_revoked_at ? ` (${COPY.revoked(when(op.consent_revoked_at))})` : ''}
          {op.consent_recorded_by ? ` · ${COPY.recorded(op.consent_recorded_by, when(op.consent_recorded_at))}` : ''}</dd>
      </dl>
      <ConsentForm key={op.consent_recorded_at} op={op} busy={busy} onSave={body => run(base, body)} />
      <StatusForm key={op.outreach_status} current={op.outreach_status} busy={busy} onSave={status => run(base, {outreach_status: status})} />
      <h2>{COPY.log}</h2>
      <p class="admin-muted">{op.outreach_status === 'do-not-contact' ? COPY.dnc : COPY.neverSent}</p>
      <NewEntry busy={busy} onAdd={body => run(`${base}/outreach`, body)} />
      {detail.outreach.length ? <ol class="admin-queue">{detail.outreach.map(o => (
        <li key={o.id}><article class={`admin-card is-${o.status}`}>
          <p class="admin-meta">{o.kind} · {o.status}{o.channel ? ` · ${o.channel}` : ''} · {COPY.by(o.created_by, when(o.created_at))}
            {o.approved_by ? ` · ${COPY.approve}: ${COPY.by(o.approved_by, when(o.approved_at))}` : ''}</p>
          <p class="admin-caption">{o.body}</p>
          {o.kind === 'draft' && (o.status === 'draft' || o.status === 'approved') ? <div class="admin-actions">
            {o.status === 'draft' ? <button type="button" class="admin-button is-primary" disabled={busy} onClick={() => void run(`outreach/${o.id}`, {action: 'approve'})}>{COPY.approve}</button>
              : <button type="button" class="admin-button is-primary" disabled={busy} onClick={() => void run(`outreach/${o.id}`, {action: 'log-sent'})}>{COPY.logSent}</button>}
            <button type="button" class="admin-button is-danger" disabled={busy} onClick={() => void run(`outreach/${o.id}`, {action: 'discard'})}>{COPY.discard}</button>
          </div> : null}
        </article></li>
      ))}</ol> : <p>{COPY.logNone}</p>}
    </section>
  );
}

function StatusForm({current, busy, onSave}: {current: string; busy: boolean; onSave: (status: string) => Promise<boolean>}) {
  const [status, setStatus] = useState(current);
  return (
    <form class="admin-editor" onSubmit={e => { e.preventDefault(); void onSave(status); }}>
      <div class="admin-editor-row">
        <label for="fleet-operator-status">{COPY.outreach}<select id="fleet-operator-status" value={status} onChange={e => setStatus(value(e))}>
          {OUTREACH.map(s => <option key={s} value={s}>{s}</option>)}</select></label>
      </div>
      <div class="admin-actions"><button type="submit" class="admin-button" disabled={busy || status === current}>{COPY.saveStatus}</button></div>
    </form>
  );
}

function ConsentForm({op, busy, onSave}: {op: OperatorDetail['operator']; busy: boolean; onSave: (body: Record<string, unknown>) => Promise<boolean>}) {
  const [status, setStatus] = useState(op.consent_status);
  const [scope, setScope] = useState<string[]>(op.consent_scope?.scope ?? []);
  const [note, setNote] = useState('');
  const toggle = (s: string): void => setScope(all => all.includes(s) ? all.filter(x => x !== s) : [...all, s]);
  return (
    <form class="admin-editor" onSubmit={e => { e.preventDefault(); void onSave({consent_status: status, consent_scope: scope, consent_note: note}); }}>
      <div class="admin-editor-row">
        <label for="fleet-consent-status">{COPY.consent}<select id="fleet-consent-status" value={status} onChange={e => setStatus(value(e))}>
          {CONSENT.map(s => <option key={s} value={s}>{s}</option>)}</select></label>
        <fieldset class="admin-targets"><legend>{COPY.scope}</legend>{SCOPES.map(s => (
          <label key={s} class="admin-check"><input type="checkbox" checked={scope.includes(s)} onChange={() => toggle(s)} />{s}</label>))}</fieldset>
      </div>
      <label for="fleet-consent-note">{COPY.consentNote}<input id="fleet-consent-note" type="text" required maxLength={2000} value={note} onInput={e => setNote(value(e))} /></label>
      <div class="admin-actions">
        <button type="submit" class="admin-button is-primary" disabled={busy}>{COPY.saveConsent}</button>
        {op.consent_revoked_at ? null : <button type="button" class="admin-button is-danger" disabled={busy || !note.trim()}
          onClick={() => void onSave({revoke_consent: true, consent_note: note})}>{COPY.revoke}</button>}
      </div>
    </form>
  );
}

function NewEntry({busy, onAdd}: {busy: boolean; onAdd: (body: Record<string, unknown>) => Promise<boolean>}) {
  const [kind, setKind] = useState<string>('note');
  const [channel, setChannel] = useState('');
  const [body, setBody] = useState('');
  async function add(e: Event): Promise<void> {
    e.preventDefault();
    if (await onAdd({kind, body, ...(channel ? {channel} : {})})) setBody('');
  }
  return (
    <form class="admin-editor" onSubmit={e => void add(e)}>
      <div class="admin-editor-row">
        <label for="fleet-entry-kind">{COPY.kind}<select id="fleet-entry-kind" value={kind} onChange={e => setKind(value(e))}>{KINDS.map(k => <option key={k} value={k}>{k}</option>)}</select></label>
        <label for="fleet-entry-channel">{COPY.channel}<select id="fleet-entry-channel" value={channel} onChange={e => setChannel(value(e))}>
          <option value="">—</option>{CHANNELS.map(c => <option key={c} value={c}>{c}</option>)}</select></label>
      </div>
      <label for="fleet-entry-body">{COPY.body}<textarea id="fleet-entry-body" required maxLength={8000} rows={5} value={body} onInput={e => setBody(value(e))} /></label>
      <div class="admin-actions"><button type="submit" class="admin-button" disabled={busy}>{COPY.add}</button></div>
    </form>
  );
}
