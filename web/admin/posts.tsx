// The admin Posts view (08 § Admin, Posts; 09 § Drafts; TA-S1): every social
// post newest change first, filtered by status and kind, 50 a page. A draft is
// decided here exactly as in the queue (its `post` review: approve, the post
// editor, reject). An approved post can be posted now or given a time, and a
// partly posted or failed one retried (TA-S2, PostActions); the others are
// read-only. TA-S4: the week calendar above the list (WeekCalendar: every slot
// of the content calendar with the posts in it, empty slots marked, and the
// other scheduled or posted posts). Per-post stats come with TA-S7.
import {useEffect, useRef, useState} from 'preact/hooks';
import {ADMIN_COPY as COPY} from '../advisor/copy.ts';
import {POST_KINDS, POST_STATUSES, getCalendar, getPosts} from './api.ts';
import type {CalendarWeek, DecisionResult, Post, QueueItem, WeekPost} from './api.ts';
import {PostActions, PostDetail} from './post-card.tsx';
import {ReviewCard} from './queue.tsx';

/** A draft with an open review as the queue item its card decides. */
export const draftItem = (post: Post): QueueItem => ({id: post.review_id!, kind: 'post', ref_id: post.id, reason: 'social_draft', status: 'open', note: null,
  opened_at: post.created_at, decided_at: null, detail: {post}});

const addDays = (date: string, days: number): string => new Date(Date.parse(`${date}T12:00:00Z`) + days * 86400000).toISOString().slice(0, 10);
const timeIn = (iso: string, tz: string): string => new Intl.DateTimeFormat('en-US', {timeZone: tz, hour: '2-digit', minute: '2-digit', hourCycle: 'h23'}).format(new Date(iso));
const dayLabel = (date: string): string => new Intl.DateTimeFormat('en-US', {weekday: 'short', month: 'short', day: 'numeric', timeZone: 'UTC'}).format(new Date(`${date}T12:00:00Z`));
const postLine = (p: WeekPost): string => `${COPY.postKinds[p.kind] ?? p.kind} · ${COPY.postStatuses[p.status] ?? p.status}${p.boat ? ` · ${p.boat}` : ''}`;

/** The week grid (TA-S4): one column per day, its slots in time order with their posts, empty ones marked, then unslotted posts. */
export function WeekCalendar({refresh}: {refresh: unknown}) {
  const [start, setStart] = useState<string | null>(null);
  const [week, setWeek] = useState<CalendarWeek | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let live = true;
    getCalendar(start).then(w => { if (live) { setWeek(w); setFailed(false); } }).catch(() => { if (live) setFailed(true); });
    return () => { live = false; };
  }, [start, refresh]);
  if (failed) return <p class="admin-error" role="alert">{COPY.calendarFailed}</p>;
  if (!week) return <p>{COPY.loading}</p>;
  const empty = week.days.reduce((n, d) => n + d.slots.filter(s => s.empty && !s.past).length, 0);
  return (
    <section class="admin-calendar" aria-labelledby="calendar-heading">
      <h2 id="calendar-heading">{COPY.calendarHeading}: {COPY.calendarRange(dayLabel(week.start), dayLabel(week.end))}</h2>
      <p class="admin-hint">{COPY.calendarHelp}</p>
      <div class="admin-actions is-tight">
        <button type="button" class="admin-button" onClick={() => setStart(addDays(week.start, -7))}>{COPY.calendarPrev}</button>
        <button type="button" class="admin-button" onClick={() => setStart(null)}>{COPY.calendarThisWeek}</button>
        <button type="button" class="admin-button" onClick={() => setStart(addDays(week.start, 7))}>{COPY.calendarNext}</button>
      </div>
      <p class="admin-notice" role="status">{COPY.calendarEmptyCount(empty)}</p>
      <ol class="admin-week">
        {week.days.map(day => (
          <li key={day.date} class="admin-day">
            <h3>{dayLabel(day.date)}</h3>
            {day.slots.length || day.others.length ? (
              <ul>
                {day.slots.map(s => (
                  <li key={`${s.slot}-${s.at}`} class={`admin-slot${s.empty ? ' is-empty' : ''}${s.past ? ' is-past' : ''}`}>
                    <span class="admin-slot-time">{s.time}</span> <strong>{COPY.postKinds[s.kind] ?? s.kind}</strong>
                    {s.posts.map(p => <span key={p.id} class="admin-slot-post">{postLine(p)}</span>)}
                    {s.empty ? <span class="admin-slot-post admin-muted">{COPY.calendarEmpty}{s.capacity > 1 ? ` (${s.posts.length}/${s.capacity})` : ''}</span> : null}
                  </li>
                ))}
                {day.others.map(p => (
                  <li key={p.id} class="admin-slot is-other">
                    <span class="admin-slot-time">{timeIn(p.at, week.tz)}</span> <strong>{COPY.calendarOther}</strong>
                    <span class="admin-slot-post">{postLine(p)}</span>
                  </li>
                ))}
              </ul>
            ) : <p class="admin-muted">{COPY.calendarNothing}</p>}
          </li>
        ))}
      </ol>
    </section>
  );
}

interface PostsPage {key: string; posts: Post[]; next: string | null; state: 'loading' | 'ready' | 'failed'}
const NO_POSTS: Post[] = [];

export function PostsView() {
  const [status, setStatus] = useState('draft');
  const [kind, setKind] = useState('');
  const key = `${status}\u0000${kind}`;
  const [page, setPage] = useState<PostsPage>({key, posts: NO_POSTS, next: null, state: 'loading'});
  const [notice, setNotice] = useState('');
  // Request ownership: the rendered filter scope, a generation bumped on every scope change and a sequence bumped on every load, so only
  // the newest request of the current scope may publish (a late old-filter response, even draft -> approved -> draft, is refused).
  const own = useRef({key, gen: 0, seq: 0, live: true});
  if (own.current.key !== key) { own.current.key = key; own.current.gen += 1; own.current.seq += 1; }
  // Data of another scope is never shown or used for a cursor: until this scope's first page arrives it is loading.
  const {posts, next, state} = page.key === key ? page : {posts: NO_POSTS, next: null, state: 'loading' as const};

  async function load(cursor: string | null = null): Promise<void> {
    const o = own.current;
    if (!o.live || o.key !== key) return;
    const {gen} = o;
    const seq = ++o.seq;
    const current = (): boolean => o.live && o.gen === gen && o.seq === seq;
    const here = (p: PostsPage): PostsPage => (p.key === key ? p : {key, posts: NO_POSTS, next: null, state: 'loading'});
    if (!cursor) setPage(p => ({...here(p), state: 'loading'}));
    try {
      const result = await getPosts(status, kind, cursor);
      if (current()) setPage(p => ({key, posts: cursor ? [...here(p).posts, ...result.posts] : result.posts, next: result.next, state: 'ready'}));
    } catch { if (current()) setPage(p => ({...here(p), state: 'failed'})); }
  }
  useEffect(() => { own.current.live = true; return () => { own.current.live = false; }; }, []);
  useEffect(() => { void load(); }, [status, kind]);

  function decided(result: DecisionResult): void {
    if (!own.current.live || own.current.key !== key) return;
    setNotice(result.repeated ? COPY.alreadyDecided(COPY.statuses[result.review.status].toLowerCase()) : COPY.decided(COPY.statuses[result.review.status].toLowerCase()));
    void load();
    requestAnimationFrame(() => document.getElementById('posts-heading')?.focus());
  }

  function changed(post: Post, message: string): void {
    if (!own.current.live || own.current.key !== key) return;
    setPage(p => (p.key === key ? {...p, posts: p.posts.map(x => (x.id === post.id ? post : x))} : p));
    setNotice(message);
  }

  return (
    <section class="admin-view" aria-labelledby="posts-heading">
      <h1 id="posts-heading" tabIndex={-1}>{COPY.postsHeading}</h1>
      <p class="admin-hint">{COPY.postsHelp}</p>
      <WeekCalendar refresh={posts} />
      <div class="admin-filters">
        <label>
          <span>{COPY.statusLabel}</span>
          <select value={status} onChange={e => setStatus((e.currentTarget as HTMLSelectElement).value)}>
            {POST_STATUSES.map(s => <option key={s} value={s}>{COPY.postStatuses[s] ?? s}</option>)}
          </select>
        </label>
        <label>
          <span>{COPY.postKindLabel}</span>
          <select value={kind} onChange={e => setKind((e.currentTarget as HTMLSelectElement).value)}>
            <option value="">{COPY.allKinds}</option>
            {POST_KINDS.map(k => <option key={k} value={k}>{COPY.postKinds[k] ?? k}</option>)}
          </select>
        </label>
      </div>
      <p class="admin-notice" role="status">{notice}</p>
      {state === 'loading' ? <p>{COPY.loading}</p> : state === 'failed' ? <p class="admin-error" role="alert">{COPY.loadFailed}</p> : posts.length === 0 ? <p>{COPY.postsNone}</p> : (
        <ol class="admin-queue">
          {posts.map(post => (
            <li key={post.id}>
              {post.status === 'draft' && post.review_id ? <ReviewCard item={draftItem(post)} onDecided={decided} /> : (
                <article class="admin-card is-post" aria-labelledby={`post-${post.id}-title`}>
                  <header class="admin-card-head">
                    <h2 id={`post-${post.id}-title`}>{COPY.postKinds[post.kind] ?? post.kind} <span class="admin-reason">{COPY.postStatuses[post.status] ?? post.status}</span></h2>
                    <p class="admin-meta">{post.boat?.name ?? COPY.angler}</p>
                  </header>
                  <PostDetail post={post} />
                  <PostActions post={post} onChanged={changed} />
                </article>
              )}
            </li>
          ))}
        </ol>
      )}
      {next && state === 'ready' ? <button type="button" class="admin-button" onClick={() => void load(next)}>{COPY.more}</button> : null}
    </section>
  );
}
