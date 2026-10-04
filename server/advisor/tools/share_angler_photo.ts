// share_angler_photo (docs/plans/text-advisor/04-advisor-engine.md § Tools, 06 §
// Angler photos; AC-1): an angler agrees (or declines) to SkipperCast sharing
// one of their photos with credit. Yes queues the photo for the team's review
// (publish_state 'queued', a media review with reason angler_photo) and asks
// once how to credit them ("anonymous" is fine); the system sends that question
// itself. Nothing is posted until the team approves it (TA-S1 drafts the post).
import type {AdvisorTool} from './tool.ts';
import {shareActions} from '../intake/anglers.ts';

export const shareAnglerPhoto: AdvisorTool = {
  name: 'share_angler_photo',
  description: "Record whether an angler agrees to SkipperCast sharing their photo with credit. Only after they said yes to sharing that photo; consent false records a no. With yes the system queues it for the team's review and asks how to credit them by itself: add nothing but a short thanks.",
  input_schema: {type: 'object', additionalProperties: false, required: ['media_id', 'consent'], properties: {media_id: {type: 'string'}, consent: {type: 'boolean'}}},
  roles: ['angler'],
  intent: 'photo.share',
  async run(input, ctx) {
    const mediaId = String(input.media_id ?? '');
    const row = /^[\w-]{1,64}$/.test(mediaId) ? await ctx.db.prepare("SELECT id,publish_state FROM advisor_media WHERE id=? AND contact_id=? AND boat_id IS NULL AND kind IN ('image','video')")
      .bind(mediaId, ctx.contact.id).first<{id: string; publish_state: string}>() : null;
    if (!row) return {result: {error: 'no such photo from this person'}};
    if (input.consent !== true) return {result: {shared: false, note: 'Nothing is shared. Say that is fine.'}, actions: [{type: 'share_state', state: null}]};
    if (row.publish_state !== 'private') return {result: {shared: true, already: row.publish_state, note: 'Already with the team. Say thanks.'}};
    const {actions, credit, asked} = await shareActions({db: ctx.db, settings: ctx.settings, contact: ctx.contact, mediaId: row.id, language: ctx.language, now: ctx.now});
    return {result: {shared: true, credit, credit_question_sent: asked, note: 'The confirmation (and the credit question) went out as its own message: add nothing, or one short thanks.'}, actions};
  },
};
