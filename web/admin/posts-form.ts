// The post editor's form logic (TA-S1), plain TypeScript so the Node tests load
// it: which fields changed (only those go in the edit's patch), the username
// lists, and the datetime-local value of a scheduled time.
import {ADMIN_COPY as COPY} from '../advisor/copy.ts';
import type {Post} from './api.ts';

export interface PostForm {caption: string; targets: string[]; collaborators: string; tags: string; schedule: string}

/** "@a, b  c" -> ['a', 'b', 'c']: lower-case usernames without @, deduplicated. */
export const usernames = (text: string): string[] => [...new Set(text.split(/[\s,]+/).map(s => s.trim().replace(/^@/, '').toLowerCase()).filter(Boolean))];

const pad = (n: number): string => String(n).padStart(2, '0');
/** An ISO time as a datetime-local value in the browser's zone ('' for none). */
export function localInput(iso: string | null): string {
  if (!iso) return '';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? '' : `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}
const LOCAL = /^(\d{4})-(\d{2})-(\d{2})T\d{2}:\d{2}(?::\d{2}(?:\.\d{1,3})?)?$/;
/** A datetime-local value (the browser's zone) as ISO; null when empty (clear the schedule); undefined when
 *  unreadable (not YYYY-MM-DDTHH:MM[:SS[.sss]], or no such day): leave the schedule as it is. */
export function fromLocalInput(value: string): string | null | undefined {
  if (!value) return null;
  const m = LOCAL.exec(value), d = new Date(value);
  if (!m || Number.isNaN(d.getTime()) || d.getFullYear() !== Number(m[1]) || d.getMonth() + 1 !== Number(m[2]) || d.getDate() !== Number(m[3])) return undefined;
  return d.toISOString();
}

const same = (a: readonly string[], b: readonly string[]): boolean => a.length === b.length && a.every((x, i) => x === b[i]);

/** The edit patch: only the fields the form changed. Tags keep their position; a new username is tagged at the centre. */
export function postEdits(post: Pick<Post, 'caption' | 'targets' | 'collaborators' | 'user_tags' | 'scheduled_for' | 'kind' | 'allowed_targets'>, form: PostForm): Record<string, unknown> {
  const patch: Record<string, unknown> = {};
  if (post.kind !== 'story' && form.caption !== post.caption) patch.caption = form.caption;
  const targets = post.allowed_targets.filter(t => form.targets.includes(t));
  if (!same(targets, post.allowed_targets.filter(t => post.targets.includes(t)))) patch.targets = targets;
  if (post.kind !== 'story') {
    const collaborators = usernames(form.collaborators);
    if (!same(collaborators, post.collaborators)) patch.collaborators = collaborators;
  }
  if (post.kind === 'photo' || post.kind === 'carousel') {
    const names = usernames(form.tags);
    if (!same(names, post.user_tags.map(t => t.username))) patch.user_tags = names.map(username => post.user_tags.find(t => t.username === username) ?? {username, x: 0.5, y: 0.5});
  }
  const scheduled = fromLocalInput(form.schedule);
  const before = post.scheduled_for ? new Date(post.scheduled_for).toISOString() : null;
  if (scheduled === undefined) { /* unreadable: leave the schedule as it is */ }
  else if (scheduled !== before && !(scheduled && before && localInput(scheduled) === localInput(before))) patch.scheduled_for = scheduled;
  return patch;
}

/** The surfaces a post already went to, by name (TA-S2). */
export function publishedTo(post: Pick<Post, 'kind' | 'ig_media_id' | 'fb_post_id' | 'fb_story_id'>): string {
  const story = post.kind === 'story';
  return [post.ig_media_id ? COPY.targetNames[story ? 'instagram_story' : 'instagram'] : null,
    (story ? post.fb_story_id : post.fb_post_id) ? COPY.targetNames[story ? 'facebook_story' : 'facebook'] : null].filter(Boolean).join(', ');
}
