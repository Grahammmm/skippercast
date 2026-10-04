// The admin Posts view (08 § Admin, Posts; 09 § Drafts; TA-S1): every social
// post newest change first, filtered by status and kind, 50 a page. A draft is
// decided here exactly as in the queue (its `post` review: approve, the post
// editor, reject); other posts are shown read-only. The week calendar, per-post
// stats and "post now" come with TA-S2, TA-S4 and TA-S7.
import {useEffect, useState} from 'preact/hooks';
import {ADMIN_COPY as COPY} from '../advisor/copy.ts';
import {POST_KINDS, POST_STATUSES, getPosts} from './api.ts';
import type {DecisionResult, Post, QueueItem} from './api.ts';
import {PostDetail} from './post-card.tsx';
import {ReviewCard} from './queue.tsx';

/** A draft with an open review as the queue item its card decides. */
export const draftItem = (post: Post): QueueItem => ({id: post.review_id!, kind: 'post', ref_id: post.id, reason: 'social_draft', status: 'open', note: null,
  opened_at: post.created_at, decided_at: null, detail: {post}});

export function PostsView() {
  const [status, setStatus] = useState('draft');
  const [kind, setKind] = useState('');
  const [posts, setPosts] = useState<Post[]>([]);
  const [next, setNext] = useState<string | null>(null);
  const [state, setState] = useState<'loading' | 'ready' | 'failed'>('loading');
  const [notice, setNotice] = useState('');

  async function load(cursor: string | null = null): Promise<void> {
    if (!cursor) setState('loading');
    try {
      const page = await getPosts(status, kind, cursor);
      setPosts(all => (cursor ? [...all, ...page.posts] : page.posts));
      setNext(page.next);
      setState('ready');
    } catch { setState('failed'); }
  }
  useEffect(() => { void load(); }, [status, kind]);

  function decided(result: DecisionResult): void {
    setNotice(result.repeated ? COPY.alreadyDecided(COPY.statuses[result.review.status].toLowerCase()) : COPY.decided(COPY.statuses[result.review.status].toLowerCase()));
    void load();
    requestAnimationFrame(() => document.getElementById('posts-heading')?.focus());
  }

  return (
    <section class="admin-view" aria-labelledby="posts-heading">
      <h1 id="posts-heading" tabIndex={-1}>{COPY.postsHeading}</h1>
      <p class="admin-hint">{COPY.postsHelp}</p>
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
