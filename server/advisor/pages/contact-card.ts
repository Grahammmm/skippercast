// The SkipperCast contact card (GET /contact.vcf; docs/plans/text-advisor/03-channels.md
// § contact card and deep links, FC-3; TA-C6). vCard 3.0 (RFC 2426): CRLF line
// endings and lines folded at 75 octets (RFC 2425 § 5.8.1: a fold is CRLF plus
// one space). The photo is the app icon, inlined as base64 PNG from a module
// generated at commit time (scripts/advisor/make-contact-icon.mjs).
import {CONTACT_ICON_PNG_BASE64} from './icon.ts';

export const VCARD_LINE_OCTETS = 75;
const encoder = new TextEncoder();

/** One content line folded at 75 octets without splitting a UTF-8 character; continuation lines start with a space. */
export function foldLine(line: string, limit = VCARD_LINE_OCTETS): string {
  if (encoder.encode(line).length <= limit) return line;
  const out: string[] = [];
  let current = '', size = 0, max = limit;
  for (const ch of line) {
    const n = encoder.encode(ch).length;
    if (size + n > max) { out.push(current); current = ''; size = 0; max = limit - 1; }
    current += ch; size += n;
  }
  out.push(current);
  return out.join('\r\n ');
}

export interface ContactCardInput {number: string; publicBase: string; photo?: string | null}

/** The vCard text for the advisor's number. `photo` is base64 PNG; default the app icon, null for none. */
export function contactCard({number, publicBase, photo = CONTACT_ICON_PNG_BASE64}: ContactCardInput): string {
  if (!/^\+\d{8,15}$/.test(number)) throw Error('contact card needs an E.164 number');
  if (!/^https:\/\/[^\s,;]+$/.test(publicBase)) throw Error('contact card needs an https base URL');
  const lines = [
    'BEGIN:VCARD',
    'VERSION:3.0',
    'FN:SkipperCast',
    'N:SkipperCast;;;;',
    'ORG:SkipperCast',
    `TEL;TYPE=CELL,VOICE:${number}`,
    `URL:${publicBase}`,
    ...(photo ? [`PHOTO;ENCODING=b;TYPE=PNG:${photo}`] : []),
    'END:VCARD',
  ];
  return lines.map(line => foldLine(line)).join('\r\n') + '\r\n';
}
