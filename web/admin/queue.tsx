// The admin Queue view (08 § Admin, Queue; TA-W2): one list of review items,
// newest first, filterable by kind and status. Each card renders by kind and
// offers approve / edit / reject; with a card focused, a, r and e do the same.
// TA-S1: a social draft (kind post) shows its photos, caption and surfaces
// (post-card.tsx); edit opens the post editor, whose save is the edit decision
// (which also approves). ReviewCard is exported for the Posts view.
import {useEffect, useRef, useState} from 'preact/hooks';
import {ADMIN_COPY as COPY} from '../advisor/copy.ts';
import {ApiError, KINDS, STATUSES, contactHref, decide, getQueue, when} from './api.ts';
import type {Count, DecisionBody, DecisionResult, QueueItem} from './api.ts';
import {decisionsFor, shortcutFor} from './keys.ts';
import {rulesHref} from './route.ts';
import {PostDetail, PostEditor} from './post-card.tsx';
import type {Post} from './api.ts';

const cardId = (id: string): string => `review-${id}`;

export function Queue() {
  const [status, setStatus] = useState('open');
  const [kind, setKind] = useState('');
  const [items, setItems] = useState<QueueItem[]>([]);
  const [next, setNext] = useState<string | null>(null);
  const [state, setState] = useState<'loading' | 'ready' | 'failed'>('loading');
  const [notice, setNotice] = useState('');

  async function load(cursor: string | null = null): Promise<void> {
    if (!cursor) setState('loading');
    try {
      const page = await getQueue(status, kind, cursor);
      setItems(all => (cursor ? [...all, ...page.items] : page.items));
      setNext(page.next);
      setState('ready');
    } catch { setState('failed'); }
  }
  useEffect(() => { void load(); }, [status, kind]);

  function decided(item: QueueItem, result: DecisionResult): void {
    const index = items.findIndex(i => i.id === item.id);
    const stays = status === 'all' || result.review.status === status;
    const rest = stays ? items.map(i => (i.id === item.id ? {...i, ...result.review, detail: i.detail} : i)) : items.filter(i => i.id !== item.id);
    setItems(rest);
    const word = COPY.statuses[result.review.status];
    const parts = [result.repeated ? COPY.alreadyDecided(word.toLowerCase()) : COPY.decided(word.toLowerCase())];
    if (result.sends) parts.push(COPY.sentTexts(result.sends));
    if (result.held) parts.push(COPY.heldTexts);
    setNotice(parts.join(' '));
    const following = stays ? item : rest[Math.min(index, rest.length - 1)];
    requestAnimationFrame(() => document.getElementById(following ? cardId(following.id) : 'queue-heading')?.focus());
  }

  return (
    <section class="admin-view" aria-labelledby="queue-heading">
      <h1 id="queue-heading" tabIndex={-1}>{COPY.queueHeading}</h1>
      <div class="admin-filters">
        <label>
          <span>{COPY.kindLabel}</span>
          <select value={kind} onChange={e => setKind((e.currentTarget as HTMLSelectElement).value)}>
            <option value="">{COPY.allKinds}</option>
            {KINDS.map(k => <option key={k} value={k}>{COPY.kinds[k]}</option>)}
          </select>
        </label>
        <label>
          <span>{COPY.statusLabel}</span>
          <select value={status} onChange={e => setStatus((e.currentTarget as HTMLSelectElement).value)}>
            {STATUSES.map(s => <option key={s} value={s}>{COPY.statuses[s]}</option>)}
          </select>
        </label>
      </div>
      <p class="admin-hint">{COPY.shortcuts}</p>
      <p class="admin-notice" role="status">{notice}</p>
      {state === 'loading' ? <p>{COPY.loading}</p> : state === 'failed' ? <p class="admin-error" role="alert">{COPY.loadFailed}</p> : items.length === 0 ? <p>{COPY.empty}</p> : (
        <ol class="admin-queue">
          {items.map(item => <li key={item.id}><ReviewCard item={item} onDecided={result => decided(item, result)} /></li>)}
        </ol>
      )}
      {next && state === 'ready' ? <button type="button" class="admin-button" onClick={() => void load(next)}>{COPY.more}</button> : null}
    </section>
  );
}

export function ReviewCard({item, onDecided}: {item: QueueItem; onDecided: (result: DecisionResult) => void}) {
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [note, setNote] = useState('');
  const card = useRef<HTMLElement>(null);
  const open = item.status === 'open';
  const offered = open ? decisionsFor(item.kind, item.reason) : [];

  async function submit(body: DecisionBody): Promise<void> {
    if (busy) return;
    setBusy(true); setError('');
    try {
      const result = await decide(item.id, note.trim() ? {...body, note: note.trim()} : body);
      setEditing(false);
      onDecided(result);
    } catch (e) { setError(e instanceof ApiError && e.status !== 500 ? e.message : COPY.decisionFailed); }
    finally { setBusy(false); }
  }

  function onKey(event: KeyboardEvent): void {
    const decision = shortcutFor(event);
    if (!decision || !offered.includes(decision) || editing || busy) return;
    event.preventDefault();
    if (decision === 'edit') setEditing(true);
    else void submit({decision});
  }

  const headingId = `${cardId(item.id)}-title`;
  const approveLabel = item.kind === 'skipper' && item.reason === 'new_skipper' ? COPY.verify : item.kind === 'conversation' || item.kind === 'rule' ? COPY.done : COPY.approve;
  return (
    <article id={cardId(item.id)} ref={card} class={`admin-card is-${item.kind}`} tabIndex={0} aria-labelledby={headingId} onKeyDown={onKey}>
      <header class="admin-card-head">
        <h2 id={headingId}>{COPY.kinds[item.kind]} <span class="admin-reason">{item.reason}</span></h2>
        <p class="admin-meta">{COPY.opened(when(item.opened_at))}{item.status !== 'open' ? ` · ${COPY.statuses[item.status]}` : ''}</p>
      </header>
      {item.detail ? <Detail item={item} /> : <p class="admin-muted">{COPY.missing}</p>}
      {item.note ? <p class="admin-muted">{item.note}</p> : null}
      {editing ? (item.kind === 'post' && item.detail?.post
        ? <PostEditor post={item.detail.post as Post} idBase={cardId(item.id)} busy={busy} onSubmit={submit} onCancel={() => { setEditing(false); card.current?.focus(); }} />
        : <Editor item={item} busy={busy} onSubmit={submit} onCancel={() => { setEditing(false); card.current?.focus(); }} />) : null}
      {offered.length && !editing ? (
        <div class="admin-actions">
          <label class="admin-note">
            <span>{COPY.noteLabel}</span>
            <input type="text" maxLength={280} value={note} onInput={e => setNote((e.currentTarget as HTMLInputElement).value)} />
          </label>
          {offered.includes('approve') ? <button type="button" class="admin-button is-primary" disabled={busy} onClick={() => void submit({decision: 'approve'})}>{approveLabel}</button> : null}
          {offered.includes('edit') ? <button type="button" class="admin-button" disabled={busy} onClick={() => setEditing(true)}>{item.kind === 'conversation' ? COPY.replyLabel : COPY.edit}</button> : null}
          {offered.includes('reject') ? <button type="button" class="admin-button is-danger" disabled={busy} onClick={() => void submit({decision: 'reject'})}>{item.kind === 'conversation' ? COPY.dismiss : COPY.reject}</button> : null}
        </div>
      ) : null}
      {error ? <p class="admin-error" role="alert">{error}</p> : null}
    </article>
  );
}

function Field({label, value}: {label: string; value: unknown}) {
  if (value === null || value === undefined || value === '') return null;
  return <><dt>{label}</dt><dd>{String(value)}</dd></>;
}

function Detail({item}: {item: QueueItem}) {
  const d = item.detail!;
  switch (item.kind) {
    case 'media': return <MediaDetail media={d.media} />;
    case 'report': return <ReportDetail report={d.report} />;
    case 'post': return <PostDetail post={d.post as Post} />;
    case 'skipper': return <SkipperDetail detail={d} />;
    case 'conversation': return (
      <>
        {d.contact?.id ? <p><a href={contactHref(d.contact.id)}>{COPY.openContact}</a></p> : null}
        <Messages messages={d.messages ?? []} heading={COPY.lastMessages} />
      </>
    );
    case 'rule': return d.summary ? <RuleChangeDetail summary={d.summary} /> : (
      <dl class="admin-fields">
        <Field label={COPY.rule} value={`${d.rule?.species_label ?? ''} (${d.rule?.jurisdiction ?? ''})`} />
        <Field label={COPY.reviewed} value={d.rule?.reviewed_at} />
        {d.rule?.source_url ? <><dt>{COPY.source}</dt><dd><a href={d.rule.source_url} target="_blank" rel="noopener noreferrer">{d.rule.source_name || d.rule.source_url}</a></dd></> : null}
        {d.rule?.jurisdiction ? <><dt>{COPY.rulesHeading}</dt><dd><a href={rulesHref(d.rule.jurisdiction)}>{COPY.reviewRules}</a></dd></> : null}
      </dl>
    );
    default: return null;
  }
}

/** A CDFW change-watch finding (TA-A4, admin/rules.ts): the changed pages with their fingerprints, the rows now in review, and the way to the Rules view. */
function RuleChangeDetail({summary}: {summary: Record<string, any>}) {
  const short = (hash: string | null): string => (hash ? hash.slice(0, 12) : '—');
  return (
    <div>
      <dl class="admin-fields">
        <Field label={COPY.jurisdiction} value={summary.jurisdiction} />
        <Field label={COPY.reviewed} value={summary.checked_at ? COPY.checkedFeed(when(summary.checked_at)) : null} />
        <Field label={COPY.rulesHeading} value={COPY.rulesInReview(summary.rules?.review ?? 0, summary.rules?.active ?? 0)} />
      </dl>
      <h3>{COPY.changedPages}</h3>
      <ul class="admin-crew">
        {(summary.sources ?? []).map((s: {id: string; name: string | null; url: string | null; content_sha256: string | null; approved_sha256: string | null}) => (
          <li key={s.id}>
            {s.url ? <a href={s.url} target="_blank" rel="noopener noreferrer">{s.name || s.id}</a> : (s.name || s.id)}
            <span class="admin-muted"> · {COPY.pageHash(short(s.content_sha256), short(s.approved_sha256))}</span>
          </li>
        ))}
      </ul>
      <p><a class="admin-button is-primary" href={rulesHref(summary.jurisdiction)}>{COPY.reviewRules}</a></p>
    </div>
  );
}

function MediaDetail({media}: {media: Record<string, any>}) {
  const labels = (media.labels ?? {}) as Record<string, unknown>;
  return (
    <div class="admin-media">
      {media.thumb ? <img src={media.thumb} alt={COPY.photoAlt} class="admin-thumb" loading="lazy" /> : <p class="admin-muted">{COPY.noPhoto}</p>}
      <div>
        <label class="admin-check">
          <input type="checkbox" checked={media.has_person === true} disabled />
          <span>{COPY.personBox}</span>
        </label>
        <dl class="admin-fields">
          <Field label={COPY.boat} value={media.boat?.name} />
          <Field label={COPY.credit} value={media.credit} />
          <Field label={COPY.publishState} value={media.publish_state} />
          <dt>{COPY.labels}</dt>
          <dd>{Object.entries(labels).filter(([k]) => k !== 'fish').map(([k, v]) => `${k}: ${typeof v === 'number' ? v.toFixed(2) : String(v)}`).join(' · ') || '—'}</dd>
        </dl>
        {media.original ? <a href={media.original} target="_blank" rel="noopener noreferrer">{COPY.openOriginal}</a> : null}
      </div>
    </div>
  );
}

function ReportDetail({report}: {report: Record<string, any>}) {
  return (
    <div>
      <dl class="admin-fields">
        <Field label={COPY.boat} value={`${report.boat?.name ?? ''}${report.boat?.status !== 'verified' ? ` (${COPY.unverifiedBoat})` : ''}`} />
        <Field label={COPY.port} value={report.port} />
        <Field label={COPY.date} value={report.report_date} />
        <Field label={COPY.trip} value={report.trip_type} />
        <Field label={COPY.anglers} value={report.anglers} />
        <Field label={COPY.notes} value={report.notes} />
        <Field label={COPY.publishState} value={`${report.status} · ${COPY.version(report.version)}`} />
      </dl>
      <table class="admin-counts">
        <thead><tr><th scope="col">{COPY.species}</th><th scope="col">{COPY.kept}</th><th scope="col">{COPY.released}</th></tr></thead>
        <tbody>{(report.counts as Count[]).map((c, i) => <tr key={i}><th scope="row">{c.label}{c.uncertain ? ' ?' : ''}</th><td>{c.kept ?? '—'}</td><td>{c.released ?? '—'}</td></tr>)}</tbody>
      </table>
    </div>
  );
}

function SkipperDetail({detail}: {detail: Record<string, any>}) {
  const b = detail.boat ?? {}, c = detail.contact;
  const consent = b.consent_photos_at && !(b.consent_revoked_at && b.consent_revoked_at >= b.consent_photos_at);
  return (
    <div>
      <dl class="admin-fields">
        <Field label={COPY.boat} value={b.name} />
        <Field label={COPY.port} value={b.port} />
        <Field label={COPY.landing} value={b.landing} />
        <Field label={COPY.instagram} value={b.instagram ? `@${b.instagram}` : null} />
        <Field label={COPY.booking} value={b.booking_url} />
        <Field label={COPY.publicPhone} value={b.phone_public} />
        <Field label={COPY.consent} value={consent ? COPY.consentGiven : COPY.consentNone} />
        <Field label={COPY.channel} value={c?.channel} />
        <Field label={COPY.language} value={c?.language} />
        <Field label={COPY.publishState} value={b.status} />
      </dl>
      {c?.id ? <p><a href={contactHref(c.id)}>{COPY.openContact}</a> · <a href="#skippers">{COPY.views.skippers}</a></p> : null}
      {(detail.messages ?? []).length ? (
        <>
          <h3>{COPY.firstMessages}</h3>
          <ol class="admin-messages">{(detail.messages as string[]).map((m, i) => <li key={i} class="is-in"><p>{m}</p></li>)}</ol>
        </>
      ) : null}
    </div>
  );
}

function Messages({messages, heading}: {messages: {direction: 'in' | 'out'; body: string | null; created_at: string; team: boolean}[]; heading: string}) {
  return (
    <>
      <h3>{heading}</h3>
      <ol class="admin-messages">
        {messages.map((m, i) => (
          <li key={i} class={`is-${m.direction}`}>
            <span class="admin-who">{m.direction === 'in' ? COPY.fromContact : m.team ? COPY.fromTeam : COPY.fromAdvisor} · {when(m.created_at)}</span>
            <p>{m.body ?? '—'}</p>
          </li>
        ))}
      </ol>
    </>
  );
}

function Editor({item, busy, onSubmit, onCancel}: {item: QueueItem; busy: boolean; onSubmit: (body: DecisionBody) => Promise<void>; onCancel: () => void}) {
  const first = useRef<HTMLInputElement & HTMLTextAreaElement>(null);
  useEffect(() => { first.current?.focus(); }, []);
  const media = item.detail?.media, report = item.detail?.report;
  const [credit, setCredit] = useState<string>(media?.credit ?? '');
  const [reply, setReply] = useState('');
  const [fields, setFields] = useState(() => ({report_date: report?.report_date ?? '', trip_type: report?.trip_type ?? '', anglers: report?.anglers == null ? '' : String(report.anglers),
    notes: report?.notes ?? '', counts: ((report?.counts ?? []) as Count[]).map(c => ({...c}))}));
  const num = (v: string): number | null => (v.trim() === '' ? null : Math.max(0, Math.round(Number(v))));
  const setCount = (i: number, key: 'kept' | 'released', value: string): void =>
    setFields(f => ({...f, counts: f.counts.map((c, j) => (j === i ? {...c, [key]: num(value)} : c))}));

  function save(event: Event): void {
    event.preventDefault();
    if (item.kind === 'media') void onSubmit({decision: 'edit', patch: {credit}});
    else if (item.kind === 'conversation') { if (reply.trim()) void onSubmit({decision: 'approve', reply: reply.trim()}); }
    else if (item.kind === 'report') void onSubmit({decision: 'edit', patch: {report_date: fields.report_date, trip_type: fields.trip_type || null, anglers: num(fields.anglers),
      notes: fields.notes || null, counts: fields.counts.map(({uncertain: _u, ...c}) => c)}});
  }
  const id = (name: string): string => `${cardId(item.id)}-${name}`;
  return (
    <form class="admin-editor" onSubmit={save}>
      {item.kind === 'media' ? (
        <label for={id('credit')}>{COPY.credit}<input id={id('credit')} ref={first} type="text" maxLength={80} value={credit} onInput={e => setCredit((e.currentTarget as HTMLInputElement).value)} /></label>
      ) : item.kind === 'conversation' ? (
        <label for={id('reply')}>{COPY.replyLabel}<textarea id={id('reply')} ref={first} rows={3} maxLength={1000} value={reply} onInput={e => setReply((e.currentTarget as HTMLTextAreaElement).value)} /></label>
      ) : (
        <>
          <div class="admin-editor-row">
            <label for={id('date')}>{COPY.date}<input id={id('date')} ref={first} type="date" value={fields.report_date} onInput={e => setFields(f => ({...f, report_date: (e.currentTarget as HTMLInputElement).value}))} /></label>
            <label for={id('trip')}>{COPY.trip}<input id={id('trip')} type="text" maxLength={30} value={fields.trip_type} onInput={e => setFields(f => ({...f, trip_type: (e.currentTarget as HTMLInputElement).value}))} /></label>
            <label for={id('anglers')}>{COPY.anglers}<input id={id('anglers')} type="number" min={0} inputMode="numeric" value={fields.anglers} onInput={e => setFields(f => ({...f, anglers: (e.currentTarget as HTMLInputElement).value}))} /></label>
          </div>
          <table class="admin-counts">
            <thead><tr><th scope="col">{COPY.species}</th><th scope="col">{COPY.kept}</th><th scope="col">{COPY.released}</th></tr></thead>
            <tbody>
              {fields.counts.map((c, i) => (
                <tr key={i}>
                  <th scope="row">{c.label}</th>
                  <td><input type="number" min={0} inputMode="numeric" aria-label={`${c.label} ${COPY.kept}`} value={c.kept ?? ''} onInput={e => setCount(i, 'kept', (e.currentTarget as HTMLInputElement).value)} /></td>
                  <td><input type="number" min={0} inputMode="numeric" aria-label={`${c.label} ${COPY.released}`} value={c.released ?? ''} onInput={e => setCount(i, 'released', (e.currentTarget as HTMLInputElement).value)} /></td>
                </tr>
              ))}
            </tbody>
          </table>
          <label for={id('notes')}>{COPY.notes}<input id={id('notes')} type="text" maxLength={280} value={fields.notes} onInput={e => setFields(f => ({...f, notes: (e.currentTarget as HTMLInputElement).value}))} /></label>
        </>
      )}
      <div class="admin-actions">
        <button type="submit" class="admin-button is-primary" disabled={busy}>{item.kind === 'conversation' ? COPY.sendReply : COPY.save}</button>
        <button type="button" class="admin-button" onClick={onCancel}>{COPY.cancel}</button>
      </div>
    </form>
  );
}

