// identify_fish (docs/plans/text-advisor/04-advisor-engine.md § Tools, 06 § Fish
// ID; ID-1, ID-2, ID-3): the fish ID of one of the contact's own stored photos,
// for a photo that came with a question (a media-only photo is answered by the
// engine without the model, intake/anglers.ts). The result carries the band,
// the candidates, the protected-species warning, the rules summary (ID-2: the
// rules table only, stale rows flagged) and `reply`: the deterministic 06
// answer the model should send as it is, adding at most one line for the
// person's question.
import type {AdvisorTool} from './tool.ts';
import {identify, offerShare} from '../answers/fishid.ts';
import {chainFor} from '../intake/reports.ts';
import {SHARE_MAX_AGE_MS} from '../intake/anglers.ts';

export const identifyFish: AdvisorTool = {
  name: 'identify_fish',
  description: "Identify the fish in a photo the person sent: species candidates with confidence, the cues that tell them apart, whether a better photo is needed, the protected-species warning and the current rules for the top candidate. `reply` is the answer in the required wording: send it as it is (you may add one short line for their question); never upgrade the confidence.",
  input_schema: {type: 'object', additionalProperties: false, required: ['media_id'], properties: {media_id: {type: 'string', description: 'The media_id of a photo in this conversation'}}},
  roles: ['angler', 'skipper', 'crew'],
  intent: 'fishid',
  async run(input, ctx) {
    const mediaId = String(input.media_id ?? '');
    const row = /^[\w-]{1,64}$/.test(mediaId) ? await ctx.db.prepare("SELECT id,kind,mime,width,height,r2_key FROM advisor_media WHERE id=? AND contact_id=? AND kind='image' AND publish_state<>'rejected'")
      .bind(mediaId, ctx.contact.id).first<{id: string; kind: string; mime: string; width: number | null; height: number | null; r2_key: string}>() : null;
    if (!row || !ctx.env.ADVISOR_MEDIA) return {result: {error: 'no such photo from this person'}};
    const out = await identify(ctx.env, row, ctx.contact, {vision: chainFor(ctx.env, ctx.deps), language: ctx.language, now: ctx.now, settings: ctx.settings});
    if (!out.ok) return {result: {unavailable: true, reason: out.error === 'too_large' ? 'photo too large: offer the upload link (send_upload_link)' : 'photo reading is unavailable right now'}};
    const a = out.answer;
    const offer = offerShare(a, ctx.contact.role);
    return {
      result: {
        media_id: row.id, band: a.band, confidence_words: {high: "That's a ...", medium: 'Looks like a ..., could be ...', ask: 'Not sure; ask for a side-on shot with the fins spread'},
        candidates: out.id.candidates.map(c => ({species_key: c.species_key, label: c.label, confidence: Math.round(c.confidence * 100) / 100, cues: c.cues})),
        needs_better_photo: a.needs_better_photo, reason: a.reason, must_release: a.protected,
        rules: a.rules, second_rules: a.second_rules, rules_link: a.top?.species_key ? `{{link:rules:${a.top.species_key}}}` : '{{link:rules}}',
        reply: a.text,
        share_offer: offer ? `After the ID, you may ask once whether we can share the photo with credit; if they agree, call share_angler_photo with media_id ${row.id} and consent true (the offer is good for ${SHARE_MAX_AGE_MS / 3600000} hours).` : null,
      },
    };
  },
};
