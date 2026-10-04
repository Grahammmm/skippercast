// The admin Skippers view (08 § Admin, Skippers; TA-W3): the pilot's recruiting
// tool. Invite a skipper by number (hashed by the server on receipt; the field is
// cleared after sending and the number is never shown again), then each boat
// with its status, owner, last report, reports in 30 days, posts, consent and
// crew; verify or reject, edit the fields with the registration's rules, keep a
// consent note, remove a crew member. Contacts open by id (#contact/<id>).
import {useEffect, useState} from 'preact/hooks';
import type {ComponentChildren} from 'preact';
import {ADMIN_COPY as COPY} from '../advisor/copy.ts';
import {ApiError, contactHref, editBoat, getBoats, invite, removeCrew, when} from './api.ts';
import type {Boat, BoatEdit, BoatFields, BoatResult} from './api.ts';

const errorText = (e: unknown): string => (e instanceof ApiError && e.status !== 500 ? e.message : COPY.decisionFailed);

export function Skippers() {
  const [boats, setBoats] = useState<Boat[]>([]);
  const [state, setState] = useState<'loading' | 'ready' | 'failed'>('loading');
  const [notice, setNotice] = useState('');

  async function load(): Promise<void> {
    try { setBoats((await getBoats()).boats); setState('ready'); } catch { setState('failed'); }
  }
  useEffect(() => { void load(); }, []);
  const replace = (boat: Boat): void => setBoats(all => all.map(b => (b.id === boat.id ? boat : b)));

  return (
    <section class="admin-view" aria-labelledby="skippers-heading">
      <h1 id="skippers-heading" tabIndex={-1}>{COPY.skippersHeading}</h1>
      <Invite onDone={text => { setNotice(text); void load(); }} />
      <p class="admin-notice" role="status">{notice}</p>
      {state === 'loading' ? <p>{COPY.loading}</p> : state === 'failed' ? <p class="admin-error" role="alert">{COPY.loadFailed}</p> : boats.length === 0 ? <p>{COPY.boatsNone}</p> : (
        <ol class="admin-queue" aria-label={COPY.boatsCaption}>
          {boats.map(boat => <li key={boat.id}><BoatCard boat={boat} onChanged={(next, text) => { replace(next); setNotice(text); }} /></li>)}
        </ol>
      )}
    </section>
  );
}

function Invite({onDone}: {onDone: (text: string) => void}) {
  const [phone, setPhone] = useState('');
  const [boat, setBoat] = useState('');
  const [language, setLanguage] = useState<'en' | 'es'>('en');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  async function send(event: Event): Promise<void> {
    event.preventDefault();
    if (busy || !phone.trim()) return;
    setBusy(true); setError('');
    try {
      const result = await invite(phone, boat, language);
      setPhone(''); setBoat('');   // the number is not kept in the page once sent
      onDone(`${COPY.invited(result.created)}${result.sends ? '' : ` ${COPY.inviteHeld}`}`);
    } catch (e) { setError(errorText(e)); }
    finally { setBusy(false); }
  }

  return (
    <form class="admin-card admin-editor" onSubmit={send} aria-labelledby="invite-heading" autocomplete="off">
      <h2 id="invite-heading">{COPY.inviteHeading}</h2>
      <p class="admin-muted">{COPY.inviteHelp}</p>
      <div class="admin-editor-row">
        <label for="invite-phone">{COPY.invitePhone}<input id="invite-phone" type="tel" inputMode="tel" autocomplete="off" required maxLength={20} value={phone}
          onInput={e => setPhone((e.currentTarget as HTMLInputElement).value)} /></label>
        <label for="invite-boat">{COPY.inviteBoat}<input id="invite-boat" type="text" maxLength={60} value={boat} onInput={e => setBoat((e.currentTarget as HTMLInputElement).value)} /></label>
        <label for="invite-language">{COPY.inviteLanguage}
          <select id="invite-language" value={language} onChange={e => setLanguage((e.currentTarget as HTMLSelectElement).value === 'es' ? 'es' : 'en')}>
            <option value="en">{COPY.languages.en}</option>
            <option value="es">{COPY.languages.es}</option>
          </select>
        </label>
      </div>
      <div class="admin-actions"><button type="submit" class="admin-button is-primary" disabled={busy}>{COPY.inviteSend}</button></div>
      {error ? <p class="admin-error" role="alert">{error}</p> : null}
    </form>
  );
}

function Field({label, children}: {label: string; children: ComponentChildren}) {
  return <><dt>{label}</dt><dd>{children}</dd></>;
}

function BoatCard({boat, onChanged}: {boat: Boat; onChanged: (boat: Boat, notice: string) => void}) {
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const headingId = `boat-${boat.id}-title`;

  async function apply(run: () => Promise<BoatResult | {boat: Boat}>, done: string): Promise<void> {
    if (busy) return;
    setBusy(true); setError('');
    try {
      const result = await run();
      const sent = 'sends' in result && result.sends ? ` ${COPY.sentTexts(result.sends)}` : '';
      const held = 'held' in result && result.held ? ` ${COPY.heldTexts}` : '';
      setEditing(false);
      onChanged(result.boat, `${done}${sent}${held}`);
    } catch (e) { setError(errorText(e)); }
    finally { setBusy(false); }
  }
  const decide = (status: 'verified' | 'rejected'): Promise<void> => apply(() => editBoat(boat.id, {status}), COPY.saved);

  return (
    <article class={`admin-card is-boat is-${boat.status}`} aria-labelledby={headingId}>
      <header class="admin-card-head">
        <h2 id={headingId}>{boat.name} <span class="admin-reason">{COPY.boatStatus[boat.status]}</span></h2>
        <p class="admin-meta">{COPY.opened(when(boat.created_at))}{boat.review_open ? ` · ${COPY.reviewOpen}` : ''}</p>
      </header>
      <dl class="admin-fields">
        <Field label={COPY.port}>{boat.port}{boat.landing ? ` · ${boat.landing}` : ''}</Field>
        <Field label={COPY.owner}>{boat.owner
          ? <a href={contactHref(boat.owner.id)}>{boat.owner.display_name || COPY.unnamed}</a>
          : COPY.noOwner}{boat.owner ? ` · ${boat.owner.channel} · ${boat.owner.status}` : ''}</Field>
        <Field label={COPY.lastReport}>{boat.last_report_date ?? COPY.never}</Field>
        <Field label={COPY.reports30}>{boat.reports_30d}</Field>
        <Field label={COPY.posts}>{boat.posts}</Field>
        <Field label={COPY.consent}>{COPY.consentState[boat.consent]}</Field>
        {boat.consent_note ? <Field label={COPY.consentNote}>{boat.consent_note.note}</Field> : null}
        {boat.instagram ? <Field label={COPY.instagram}>@{boat.instagram}</Field> : null}
        {boat.booking_url ? <Field label={COPY.booking}>{boat.booking_url}</Field> : null}
        {boat.phone_public ? <Field label={COPY.publicPhone}>{boat.phone_public}</Field> : null}
        <Field label={COPY.boatPage}><a href={`/boats/${encodeURIComponent(boat.slug)}`} target="_blank" rel="noopener noreferrer">/boats/{boat.slug}</a></Field>
        <Field label={COPY.crew}>{boat.crew.length === 0 ? COPY.noCrew : (
          <ul class="admin-crew">
            {boat.crew.map(c => (
              <li key={c.contact_id}>
                <a href={contactHref(c.contact_id)}>{c.display_name || COPY.unnamed}</a>{` · ${c.channel}`}{' '}
                <button type="button" class="admin-button is-danger is-small" disabled={busy}
                  onClick={() => void apply(() => removeCrew(boat.id, c.contact_id), COPY.crewRemoved)}>{COPY.removeCrew(c.display_name || COPY.unnamed)}</button>
              </li>
            ))}
          </ul>
        )}</Field>
      </dl>
      {editing ? <BoatEditor boat={boat} busy={busy} onSave={edit => void apply(() => editBoat(boat.id, edit), COPY.saved)} onCancel={() => setEditing(false)} /> : (
        <div class="admin-actions">
          {boat.status !== 'verified' ? <button type="button" class="admin-button is-primary" disabled={busy} onClick={() => void decide('verified')}>{COPY.verifyBoat}</button> : null}
          {boat.status !== 'rejected' ? <button type="button" class="admin-button is-danger" disabled={busy} onClick={() => void decide('rejected')}>{COPY.rejectBoat}</button> : null}
          <button type="button" class="admin-button" disabled={busy} onClick={() => setEditing(true)}>{COPY.editBoat}</button>
        </div>
      )}
      {error ? <p class="admin-error" role="alert">{error}</p> : null}
    </article>
  );
}

function BoatEditor({boat, busy, onSave, onCancel}: {boat: Boat; busy: boolean; onSave: (edit: BoatEdit) => void; onCancel: () => void}) {
  const [values, setValues] = useState({name: boat.name, port: boat.port, landing: boat.landing ?? '', instagram: boat.instagram ?? '',
    booking_url: boat.booking_url ?? '', phone_public: boat.phone_public ?? '', note: boat.consent_note?.note ?? ''});
  const id = (name: string): string => `boat-${boat.id}-${name}`;
  const input = (key: keyof typeof values) => (e: Event): void => { const v = (e.currentTarget as HTMLInputElement).value; setValues(all => ({...all, [key]: v})); };

  function save(event: Event): void {
    event.preventDefault();
    const original: Record<string, string> = {name: boat.name, port: boat.port, landing: boat.landing ?? '', instagram: boat.instagram ?? '',
      booking_url: boat.booking_url ?? '', phone_public: boat.phone_public ?? ''};
    const fields: BoatFields = {};
    for (const key of ['name', 'port', 'landing', 'instagram', 'booking_url', 'phone_public'] as const)
      if (values[key].trim() !== original[key]) fields[key] = values[key].trim() || null;
    const note = values.note.trim();
    onSave({...(Object.keys(fields).length ? {fields} : {}), ...(note !== (boat.consent_note?.note ?? '') ? {consent_note: note || null} : {})});
  }

  return (
    <form class="admin-editor" onSubmit={save}>
      <div class="admin-editor-row">
        <label for={id('name')}>{COPY.name}<input id={id('name')} type="text" required maxLength={60} value={values.name} onInput={input('name')} /></label>
        <label for={id('port')}>{COPY.port}<input id={id('port')} type="text" required maxLength={60} value={values.port} onInput={input('port')} /></label>
        <label for={id('landing')}>{COPY.landing}<input id={id('landing')} type="text" maxLength={60} value={values.landing} onInput={input('landing')} /></label>
      </div>
      <div class="admin-editor-row">
        <label for={id('instagram')}>{COPY.instagram}<input id={id('instagram')} type="text" maxLength={31} value={values.instagram} onInput={input('instagram')} /></label>
        <label for={id('booking')}>{COPY.booking}<input id={id('booking')} type="url" maxLength={300} value={values.booking_url} onInput={input('booking_url')} /></label>
        <label for={id('phone')}>{COPY.publicPhone}<input id={id('phone')} type="tel" maxLength={20} value={values.phone_public} onInput={input('phone_public')} /></label>
      </div>
      <label for={id('note')}>{COPY.consentNote}<input id={id('note')} type="text" maxLength={280} aria-describedby={id('note-help')} value={values.note} onInput={input('note')} /></label>
      <p id={id('note-help')} class="admin-muted">{COPY.consentNoteHelp}</p>
      <div class="admin-actions">
        <button type="submit" class="admin-button is-primary" disabled={busy}>{COPY.save}</button>
        <button type="button" class="admin-button" onClick={onCancel}>{COPY.cancel}</button>
      </div>
    </form>
  );
}
