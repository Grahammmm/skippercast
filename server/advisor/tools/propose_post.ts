// propose_post (docs/plans/text-advisor/04-advisor-engine.md § Tools, 05 § Catch
// and action photos, 09 § Drafts; TA-S1): a skipper or crew member asks for one
// of their photos or videos to go on SkipperCast's feed. The tool checks the
// photo is theirs and the boat's, that the boat has active photo consent and is
// not rejected, and returns the actions: a private photo is queued for the feed
// (media_queue, which also makes the draft; a person in it opens the has_person
// photo review), a photo already queued gets its draft (post_draft). The hint
// (their words about the photo, at most 200 characters) goes to the caption
// line as a fact, never as an instruction. The team approves every post.
import type {AdvisorTool} from './tool.ts';
import {contactBoat} from '../intake/reports.ts';
import {consentActive} from '../intake/skippers.ts';
import {postIdForMedia} from '../social/drafts.ts';
import {decideHold} from '../vision/index.ts';
import type {Action} from '../types.ts';

export const proposePost: AdvisorTool = {
  name: 'propose_post',
  description: "Draft a social post from a skipper's catch or action photo (or video) for the team to review. Only for a photo they sent and asked to post. The team approves every post; after calling it say in one short line that it is queued for review.",
  input_schema: {type: 'object', additionalProperties: false, required: ['media_id'], properties: {media_id: {type: 'string'}, hint: {type: 'string', maxLength: 200}}},
  roles: ['skipper', 'crew'],
  intent: 'post.draft',
  async run(input, ctx) {
    const boat = await contactBoat(ctx.db, ctx.contact);
    if (!boat) return {result: {drafted: false, reason: 'this contact is not linked to a boat'}};
    const id = String(input.media_id ?? '');
    const row = /^[\w-]{1,64}$/.test(id) ? await ctx.db.prepare("SELECT id,boat_id,kind,publish_state,classification_json FROM advisor_media WHERE id=? AND contact_id=? AND kind IN ('image','video')")
      .bind(id, ctx.contact.id).first<{id: string; boat_id: string | null; kind: string; publish_state: string; classification_json: string | null}>() : null;
    if (!row || row.boat_id !== boat.id) return {result: {drafted: false, reason: 'no photo or video with that id from this contact for this boat'}};
    if (row.publish_state === 'rejected') return {result: {drafted: false, reason: 'the team did not approve this photo'}};
    if (boat.status === 'rejected') return {result: {drafted: false, reason: 'the boat is not on SkipperCast'}};
    if (!consentActive(boat)) return {result: {drafted: false, reason: boat.relation === 'owner'
      ? 'no photo consent: they can reply "post my photos" to allow SkipperCast to post their photos'
      : 'no photo consent: the boat owner can text "post my photos" to allow it'}};
    const post = await ctx.db.prepare('SELECT status FROM advisor_posts WHERE id=?').bind(await postIdForMedia(row.id)).first<{status: string}>();
    if (post) return {result: {drafted: false, already: post.status, note: post.status === 'draft' ? 'It is already waiting for the team. Say so in one line.' : `This photo's post is ${post.status}.`}};
    const hint = typeof input.hint === 'string' ? input.hint.replace(/\s+/g, ' ').trim().slice(0, 200) : '';
    const actions: Action[] = [];
    if (row.publish_state === 'private') {
      actions.push({type: 'media_queue', mediaId: row.id, ...(hint ? {hint} : {})});
      // 05 § catch photos: a person in the photo holds it for a photo review first (the draft waits for that).
      try {
        const c = JSON.parse(row.classification_json ?? 'null')?.classify;
        if (c && typeof c === 'object' && decideHold(c)) actions.push({type: 'review_open', kind: 'media', refId: row.id, reason: c.nsfw ? 'nsfw' : 'has_person'});
      } catch { /* not classified: the team sees the photo in the draft */ }
    } else {
      actions.push({type: 'post_draft', mediaId: row.id, ...(hint ? {hint} : {})});
    }
    return {result: {drafted: true, note: 'Queued for the team to review before it goes on the SkipperCast feed. Say so in one short line; do not promise when it posts.'}, actions};
  },
};
