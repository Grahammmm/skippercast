// A social post in the admin (08 § Admin, Queue and Posts; 09 § Drafts; TA-S1):
// PostDetail shows the photos, the caption with its counts against Instagram's
// limits, the surfaces, collaborators, tags, schedule and what holds approval;
// PostEditor edits the caption, the surfaces (checkboxes), collaborators, tags
// and the schedule, and saves them as the review's edit decision (which also
// approves). Used by the queue's `post` card and the Posts view.
import {useEffect, useRef, useState} from 'preact/hooks';
import {ADMIN_COPY as COPY} from '../advisor/copy.ts';
import {when} from './api.ts';
import type {DecisionBody, Post} from './api.ts';
import {postEdits, localInput} from './posts-form.ts';

export function PostDetail({post}: {post: Post}) {
  return (
    <div class="admin-media">
      <div class="admin-post-photos">
        {post.media.length ? post.media.map(m => (m.thumb
          ? <img key={m.id} src={m.thumb} alt={COPY.postPhotoAlt} class="admin-thumb" loading="lazy" />
          : <p key={m.id} class="admin-muted">{COPY.noPhoto}</p>)) : <p class="admin-muted">{COPY.noPhoto}</p>}
      </div>
      <div>
        {post.hold ? <p class="admin-hold"><strong>{COPY.hold}:</strong> {post.hold}</p> : null}
        <dl class="admin-fields">
          <dt>{COPY.postKindLabel}</dt><dd>{COPY.postKinds[post.kind] ?? post.kind}</dd>
          <dt>{COPY.publishState}</dt><dd>{COPY.postStatuses[post.status] ?? post.status}{post.approved_at ? ` · ${COPY.approvedBy(when(post.approved_at))}` : ''}</dd>
          <dt>{COPY.boat}</dt><dd>{post.boat ? `${post.boat.name}${post.boat.status !== 'verified' ? ` (${COPY.unverifiedBoat})` : ''}` : COPY.angler}</dd>
          <dt>{COPY.targets}</dt><dd>{post.targets.map(t => COPY.targetNames[t] ?? t).join(', ') || '—'}</dd>
          {post.collaborators.length ? <><dt>{COPY.collaborators}</dt><dd>{post.collaborators.map(c => `@${c}`).join(', ')}</dd></> : null}
          {post.user_tags.length ? <><dt>{COPY.userTags}</dt><dd>{post.user_tags.map(t => `@${t.username}`).join(', ')}</dd></> : null}
          <dt>{COPY.scheduledFor}</dt><dd>{post.scheduled_for ? when(post.scheduled_for) : COPY.notScheduled}</dd>
          {post.error ? <><dt>{COPY.postError}</dt><dd>{post.error}</dd></> : null}
          {post.media.some(m => m.has_person) ? <><dt>{COPY.personBox}</dt><dd>{post.media.filter(m => m.has_person).map(m => m.publish_state).join(', ')}</dd></> : null}
        </dl>
        <h3>{COPY.caption}</h3>
        {post.caption ? <p class="admin-caption">{post.caption}</p> : <p class="admin-muted">{COPY.noCaption}</p>}
        {post.caption ? <p class="admin-muted">{COPY.captionCounts(post.caption_stats.length, post.caption_stats.hashtags, post.caption_stats.mentions)}</p> : null}
      </div>
    </div>
  );
}

export function PostEditor({post, idBase, busy, onSubmit, onCancel}: {post: Post; idBase: string; busy: boolean; onSubmit: (body: DecisionBody) => Promise<void>; onCancel: () => void}) {
  const first = useRef<HTMLTextAreaElement>(null);
  useEffect(() => { first.current?.focus(); }, []);
  const [caption, setCaption] = useState(post.caption);
  const [targets, setTargets] = useState<string[]>(post.targets);
  const [collaborators, setCollaborators] = useState(post.collaborators.join(', '));
  const [tags, setTags] = useState(post.user_tags.map(t => t.username).join(', '));
  const [schedule, setSchedule] = useState(localInput(post.scheduled_for));
  const story = post.kind === 'story';
  const id = (name: string): string => `${idBase}-${name}`;
  const counts = {length: Array.from(caption).length, hashtags: (caption.match(/(?:^|[^\p{L}\p{N}_&#])#[\p{L}\p{N}_]+/gu) ?? []).length,
    mentions: (caption.match(/(?:^|[^\p{L}\p{N}_.@])@[A-Za-z0-9._]{1,30}/gu) ?? []).length};

  function save(event: Event): void {
    event.preventDefault();
    const patch = postEdits(post, {caption, targets, collaborators, tags, schedule});
    void onSubmit(Object.keys(patch).length ? {decision: 'edit', patch} : {decision: 'approve'});
  }
  return (
    <form class="admin-editor" onSubmit={save}>
      {story ? <p class="admin-muted">{COPY.noCaption}</p> : (
        <label for={id('caption')}>{COPY.caption}
          <textarea id={id('caption')} ref={first} rows={8} maxLength={2400} value={caption} aria-describedby={id('counts')}
            onInput={e => setCaption((e.currentTarget as HTMLTextAreaElement).value)} />
        </label>
      )}
      {story ? null : <p id={id('counts')} class="admin-muted">{COPY.captionCounts(counts.length, counts.hashtags, counts.mentions)}</p>}
      <fieldset class="admin-targets">
        <legend>{COPY.targets}</legend>
        {post.allowed_targets.map(t => (
          <label key={t} class="admin-check">
            <input type="checkbox" checked={targets.includes(t)} onChange={e => setTargets(all => ((e.currentTarget as HTMLInputElement).checked ? [...all, t] : all.filter(x => x !== t)))} />
            <span>{COPY.targetNames[t] ?? t}</span>
          </label>
        ))}
      </fieldset>
      {story ? null : (
        <label for={id('collab')}>{COPY.collaborators}
          <input id={id('collab')} type="text" maxLength={120} value={collaborators} onInput={e => setCollaborators((e.currentTarget as HTMLInputElement).value)} />
        </label>
      )}
      {post.kind === 'photo' || post.kind === 'carousel' ? (
        <label for={id('tags')}>{COPY.userTags}
          <input id={id('tags')} type="text" maxLength={400} value={tags} onInput={e => setTags((e.currentTarget as HTMLInputElement).value)} />
        </label>
      ) : null}
      <label for={id('schedule')}>{COPY.scheduledFor}
        <input id={id('schedule')} type="datetime-local" value={schedule} onInput={e => setSchedule((e.currentTarget as HTMLInputElement).value)} />
      </label>
      <div class="admin-actions">
        <button type="submit" class="admin-button is-primary" disabled={busy || !targets.length}>{COPY.saveApprove}</button>
        <button type="button" class="admin-button" onClick={onCancel}>{COPY.cancel}</button>
      </div>
    </form>
  );
}
