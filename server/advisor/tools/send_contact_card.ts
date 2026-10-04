// send_contact_card (04 § Tools, FC-3): the contact card as a file on
// iMessage, a link to /contact.vcf everywhere else (SMS, web).
import type {AdvisorTool, ToolContext} from './tool.ts';
import type {Action} from '../types.ts';
import {contactCard} from '../pages/contact-card.ts';
import {t} from '../strings.ts';

const toBase64 = (text: string): string => { let s = ''; for (const b of new TextEncoder().encode(text)) s += String.fromCharCode(b); return btoa(s); };

/** The action that delivers the card, or null when ADVISOR_NUMBER is not set. */
export function contactCardAction(ctx: Pick<ToolContext, 'contact' | 'language' | 'settings'>): Action | null {
  const {settings, contact, language} = ctx;
  if (!settings.number) return null;
  const link = `${settings.publicBase}/contact.vcf`;
  if (contact.channel !== 'imessage') return {type: 'send_text', text: t(language, 'contact_card_link', {link})};
  return {type: 'send_file', name: 'SkipperCast.vcf', mime: 'text/vcard', inlineBytes: toBase64(contactCard({number: settings.number, publicBase: settings.publicBase})),
    caption: t(language, 'contact_card_file'), fallbackUrl: link};
}

export const sendContactCard: AdvisorTool = {
  name: 'send_contact_card',
  description: "Send the person SkipperCast's contact card so they can save the number. It goes out as its own message.",
  input_schema: {type: 'object', additionalProperties: false, properties: {}},
  roles: ['angler', 'skipper', 'crew'],
  intent: 'contact_card',
  async run(_input, ctx) {
    const action = contactCardAction(ctx);
    return action ? {result: {sent: true}, actions: [action]} : {result: {sent: false, reason: 'not available right now'}};
  },
};
