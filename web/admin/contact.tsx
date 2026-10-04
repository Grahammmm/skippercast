// The admin Contact view (08 § Admin, Contacts; TA-W3): one contact, opened by
// id from a review item or a boat (#contact/<id>); there is deliberately no
// search by phone number. Its fields (never the number), its boats, the last 50
// messages, the export link and block / unblock.
import {useEffect, useState} from 'preact/hooks';
import {ADMIN_COPY as COPY} from '../advisor/copy.ts';
import {ApiError, getContact, setBlocked, when} from './api.ts';
import type {ContactDetail} from './api.ts';

export function ContactView({id}: {id: string}) {
  const [detail, setDetail] = useState<ContactDetail | null>(null);
  const [state, setState] = useState<'loading' | 'ready' | 'missing' | 'failed'>('loading');
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');

  async function load(): Promise<void> {
    setState('loading');
    try { setDetail(await getContact(id)); setState('ready'); }
    catch (e) { setState(e instanceof ApiError && e.status === 404 ? 'missing' : 'failed'); }
  }
  useEffect(() => { void load(); }, [id]);

  async function toggle(): Promise<void> {
    if (!detail || busy) return;
    setBusy(true); setError('');
    try {
      const blocked = detail.contact.status !== 'blocked';
      const result = await setBlocked(id, blocked);
      setDetail({...detail, contact: {...detail.contact, status: result.status}});
      setNotice(COPY.contactStatus[result.status as keyof typeof COPY.contactStatus] ?? result.status);
    } catch (e) { setError(e instanceof ApiError && e.status !== 500 ? e.message : COPY.decisionFailed); }
    finally { setBusy(false); }
  }

  const c = detail?.contact;
  return (
    <section class="admin-view" aria-labelledby="contact-heading">
      <h1 id="contact-heading" tabIndex={-1}>{COPY.contactHeading}{c?.display_name ? `: ${c.display_name}` : ''}</h1>
      <p><a href="#skippers">{COPY.backToSkippers}</a></p>
      <p class="admin-notice" role="status">{notice}</p>
      {state === 'loading' ? <p>{COPY.loading}</p> : state === 'missing' ? <p>{COPY.contactMissing}</p> : state === 'failed' || !detail || !c ? <p class="admin-error" role="alert">{COPY.loadFailed}</p> : (
        <>
          <dl class="admin-fields">
            <dt>{COPY.status}</dt><dd class={c.status === 'active' ? undefined : 'is-caution'}>{COPY.contactStatus[c.status as keyof typeof COPY.contactStatus] ?? c.status}</dd>
            <dt>{COPY.role}</dt><dd>{c.role}</dd>
            <dt>{COPY.channel}</dt><dd>{c.channel}</dd>
            <dt>{COPY.language}</dt><dd>{c.language}</dd>
            <dt>{COPY.source}</dt><dd>{c.source ?? '—'}</dd>
            <dt>{COPY.homePort}</dt><dd>{c.home_port ?? '—'}</dd>
            <dt>{COPY.firstSeen}</dt><dd>{when(c.created_at)}</dd>
            <dt>{COPY.lastSeen}</dt><dd>{when(c.last_seen_at)}</dd>
            <dt>{COPY.messagesToday}</dt><dd>{c.messages_today}</dd>
            <dt>{COPY.boats}</dt>
            <dd>{detail.boats.length === 0 ? '—' : detail.boats.map((b, i) => (
              <span key={b.id}>{i ? ', ' : ''}{b.name} ({COPY.relation[b.relation]}, {COPY.boatStatus[b.status as keyof typeof COPY.boatStatus] ?? b.status})</span>
            ))}</dd>
          </dl>
          <div class="admin-actions">
            <a class="admin-button" href={detail.export} download>{COPY.exportData}</a>
            <button type="button" class={`admin-button${c.status === 'blocked' ? '' : ' is-danger'}`} disabled={busy} aria-describedby="block-help" onClick={() => void toggle()}>
              {c.status === 'blocked' ? COPY.unblock : COPY.block}
            </button>
          </div>
          <p id="block-help" class="admin-muted">{COPY.blockHelp}</p>
          {error ? <p class="admin-error" role="alert">{error}</p> : null}
          <h2>{COPY.conversation}</h2>
          {detail.messages.length === 0 ? <p>{COPY.noMessages}</p> : (
            <ol class="admin-messages">
              {detail.messages.map((m, i) => (
                <li key={i} class={`is-${m.direction}`}>
                  <span class="admin-who">{m.direction === 'in' ? COPY.fromContact : m.team ? COPY.fromTeam : COPY.fromAdvisor} · {when(m.created_at)}{m.intent ? ` · ${m.intent}` : ''}{m.status !== 'done' && m.status !== 'sent' ? ` · ${m.status}` : ''}</span>
                  <p>{m.body ?? '—'}{m.media ? ` (${COPY.attachments(m.media)})` : ''}</p>
                </li>
              ))}
            </ol>
          )}
        </>
      )}
    </section>
  );
}
