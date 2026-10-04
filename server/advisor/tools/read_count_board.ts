// read_count_board (04 § Tools, 05 § Count-board photo → report, SC-1): the model
// asks for a skipper's count-board photo to be read, usually one sent with a
// caption (a media-only board is read by the Stage 2 flow without the model).
// Vision reads it (07), draftFromBoard makes the draft and the system texts the
// confirmation itself, the same text and report row as the deterministic path.
import type {AdvisorTool} from './tool.ts';
import {chainFor, contactBoat, draftActions, draftFromBoard, imageOf} from '../intake/reports.ts';
import {MediaTooLarge, decideReadingUsable} from '../vision/index.ts';

export const readCountBoard: AdvisorTool = {
  name: 'read_count_board',
  description: "Read a skipper's count-board photo (by its media_id from the conversation) into a draft report. The system texts the draft and asks them to confirm; after calling it reply with one short line at most and do not repeat the counts.",
  input_schema: {type: 'object', additionalProperties: false, required: ['media_id'], properties: {media_id: {type: 'string'}}},
  roles: ['skipper', 'crew'],
  intent: 'report.count_board',
  async run(input, ctx) {
    const boat = await contactBoat(ctx.db, ctx.contact);
    if (!boat) return {result: {read: false, reason: 'this contact is not linked to a boat'}};
    const id = String(input.media_id ?? '');
    const row = /^[\w-]{1,64}$/.test(id) ? await ctx.db.prepare("SELECT id,mime,width,height,r2_key,kind,orientation FROM advisor_media WHERE id=? AND contact_id=? AND publish_state<>'rejected'")
      .bind(id, ctx.contact.id).first<{id: string; mime: string; width: number | null; height: number | null; r2_key: string; kind: string; orientation: number | null}>() : null;
    if (!row || row.kind !== 'image' || !row.r2_key || !ctx.env.ADVISOR_MEDIA) return {result: {read: false, reason: 'no readable photo with that id from this contact'}};
    let reading;
    try {
      reading = await chainFor(ctx.env, ctx.deps).readCountBoard(imageOf(ctx.env, row));
    } catch (error) {
      return {result: {read: false, reason: error instanceof MediaTooLarge ? 'the photo is too large; offer send_upload_link' : 'photo reading is unavailable; ask them to text the numbers'}};
    }
    if (!decideReadingUsable(reading)) return {result: {read: false, reason: 'unreadable; ask for a clearer shot or the numbers as text'}};
    const draft = await draftActions({db: ctx.db, settings: ctx.settings, contact: ctx.contact, boat, messageId: ctx.message.id, language: ctx.language, now: ctx.now,
      fields: draftFromBoard(reading, ctx.contact, boat, ctx.now), source: 'count-board', mediaId: row.id});
    return {result: {read: true, report_id: draft.reportId, updated_existing: draft.edited, note: 'The system has texted the draft and the confirmation question. Add one short line at most.'}, actions: draft.actions};
  },
};
