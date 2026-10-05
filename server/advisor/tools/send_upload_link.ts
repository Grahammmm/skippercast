// send_upload_link (04 § Tools, 03 § Uploads): a 24-hour upload link, sent as
// its own text so the model never handles the URL.
import type {AdvisorTool, ToolContext, ToolOutput} from './tool.ts';
import {deriveKeys} from '../contacts.ts';
import {mintUploadToken, uploadLink} from '../media.ts';
import {t} from '../strings.ts';

/** The upload link text for this contact, or the "can't right now" text without ADVISOR_PHONE_KEY. */
export async function uploadLinkText(ctx: Pick<ToolContext, 'env' | 'contact' | 'language' | 'settings' | 'now'>): Promise<{text: string; ok: boolean}> {
  if (!ctx.env.ADVISOR_PHONE_KEY) return {text: t(ctx.language, 'upload_unavailable'), ok: false};
  const token = await mintUploadToken(await deriveKeys(ctx.env.ADVISOR_PHONE_KEY), ctx.contact.id, ctx.now);
  return {text: t(ctx.language, 'upload_link', {link: uploadLink(ctx.settings.publicBase, token)}), ok: true};
}

export const sendUploadLink: AdvisorTool = {
  name: 'send_upload_link',
  description: 'Text the person a 24-hour link where they can upload full-size photos or videos (useful on SMS, which shrinks photos, and for videos). The link goes out as its own message; do not repeat or invent a URL.',
  input_schema: {type: 'object', additionalProperties: false, properties: {}},
  roles: ['angler', 'skipper', 'crew'],
  intent: 'upload_link',
  async run(_input, ctx): Promise<ToolOutput> {
    const {text, ok} = await uploadLinkText(ctx);
    return {result: ok ? {sent: true, note: 'the link was sent as its own message'} : {sent: false, reason: 'not available right now'}, actions: [{type: 'send_text', text}]};
  },
};
