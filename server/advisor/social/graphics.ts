// Posts whose pictures are generated graphics (docs/plans/text-advisor/09-social.md
// § Daily post and roundup, § Stories, § Media that Meta fetches; TA-S4, TA-S5):
// the daily "what's biting" card, the weekly roundup carousel (a cover and one
// slide per photo) and a Story card without a photo (the morning conditions).
//
// The graphic of a post is the media job's graphic request with the post's own
// id (media.ts requestGraphic, job_state advisor.graphic.<post id>), written to
// advisor/posts/<post id>/<name>.jpg; roundup slides sit beside it as
// <name>-<n>.jpg. Meta fetches them at /media/post/<post id>/<name>
// (routes/advisor.ts) and the admin previews them at
// /api/admin/posts/<post id>/graphics/<name> (routes/admin.ts).
import {graphicState} from '../media.ts';
import type {GraphicState} from '../media.ts';

/** The file each graphic post kind renders (the out_key's last part). */
export const GRAPHIC_FILE = {daily: 'daily.jpg', roundup: 'roundup.jpg', story: 'story.jpg'} as const;
export const GRAPHIC_NAME = /^[\w-]{1,64}\.jpg$/;
/** Post statuses whose graphics Meta may fetch: approved, and while or after publishing. */
export const GRAPHIC_PUBLIC_STATUSES: readonly string[] = ['approved', 'publishing', 'posted', 'partial'];

const ids = (json: string | null): unknown[] => { try { const v = JSON.parse(json ?? '[]'); return Array.isArray(v) ? v : []; } catch { return []; } };

/** True for a post published from its graphics: a daily post, a roundup, or a Story with no photo of its own. */
export const usesGraphic = (post: {kind: string; media_json: string | null}): boolean =>
  post.kind === 'daily' || post.kind === 'roundup' || (post.kind === 'story' && ids(post.media_json).length === 0);

/** The graphic's R2 key for a post: advisor/posts/<post id>/<name>. */
export const graphicKey = (postId: string, name: string): string => `advisor/posts/${postId}/${name}`;

/** The rendered images of a done graphic, in order (the cover or card first, then roundup slides); [] otherwise. */
export function graphicKeys(state: GraphicState | null): string[] {
  if (!state || state.status !== 'done' || !state.keys?.public) return [];
  return [state.keys.public, ...(state.keys.slides ?? [])];
}

/** A key's file name (the /media/post/<id>/<name> part). */
export const graphicName = (key: string): string => key.slice(key.lastIndexOf('/') + 1);

/** The public URL Meta fetches for one of a post's graphics. */
export const graphicUrl = (base: string, postId: string, name: string): string => `${base}/media/post/${postId}/${name}`;

/** The admin's preview URL of one of a post's graphics (admins only). */
export const adminGraphicUrl = (postId: string, name: string): string => `/api/admin/posts/${encodeURIComponent(postId)}/graphics/${encodeURIComponent(name)}`;

/**
 * Why a graphic post is not ready, or null: the graphic was never requested,
 * failed, or (unless `pendingOk`) is still being rendered.
 */
export async function graphicHold(db: D1Database, postId: string, opts: {pendingOk?: boolean} = {}): Promise<string | null> {
  const state = await graphicState(db, postId);
  if (!state) return 'the graphic of this post was never requested';
  if (state.status === 'failed') return `the graphic could not be made (${String(state.error ?? 'unknown').slice(0, 80)})`;
  if (state.status === 'pending') return opts.pendingOk ? null : 'the graphic is still being made (the media job runs within 15 minutes)';
  return graphicKeys(state).length ? null : 'the graphic could not be made (no image)';
}

/** The names of a post's rendered graphics that may be served (the done state's keys under the post's prefix). */
export async function servableGraphic(db: D1Database, postId: string, name: string): Promise<string | null> {
  if (!GRAPHIC_NAME.test(name)) return null;
  const key = graphicKey(postId, name);
  return graphicKeys(await graphicState(db, postId)).includes(key) ? key : null;
}
