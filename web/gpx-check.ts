// Delivery-time checks for our GPX 1.1 exporter; no DOM or navigation claims.
import {placeRefused, screenPlace, type PlaceVerdict} from '../dist/geo-screen.js';

/** Walks an opening tag's attribute string as whole quoted tokens (whitespace-separated, single or double quotes), so an attribute name is
 * compared in full and text inside another attribute's value is never read as an attribute. `ok` is false if anything is left unconsumed. */
function readAttributes(attrs: string): {ok: boolean; list: [string, string][]} {
  const list: [string, string][] = [], token = /\s+([^\s=<>"'/]+)\s*=\s*(?:"([^"]*)"|'([^']*)')/y;
  let at = 0;
  for (let m: RegExpExecArray | null; (token.lastIndex = at, m = token.exec(attrs)); at = token.lastIndex) list.push([m[1]!, m[2] ?? m[3] ?? '']);
  return {ok: !attrs.slice(at).trim(), list};
}

const ENTITIES: Record<string, string> = {amp: '&', lt: '<', gt: '>', quot: '"', apos: "'"};
/** One reference at the sticky position: a named XML entity, or decimal `#digits` / hexadecimal `#xhex`, each ending in `;`. */
const reference = /&(?:(amp|lt|gt|quot|apos)|#([0-9]+)|#x([0-9A-Fa-f]+));/y;
/** XML 1.0 Char production: a numeric reference must resolve to one of these code points. */
const xmlCharacter = (n: number): boolean => n === 9 || n === 10 || n === 13 || (n >= 0x20 && n <= 0xd7ff) || (n >= 0xe000 && n <= 0xfffd) || (n >= 0x10000 && n <= 0x10ffff);

/** With a `screen` (null while not loaded), fishable waypoints inside, near or unchecked fail the file.
 * Tracks remain structurally checked: fishing geometry is gated by buildExport, while AVOID outlines and depth contours are references, not fishable places.
 * Without a screen only the structure is checked. */
export function checkGpx(xml: string, expected: {waypoints: number}, screen?: unknown): {ok: true; screen: PlaceVerdict[]} | {ok: false; problems: string[]; screen: PlaceVerdict[]} {
  const problems: string[] = [], fail = (s: string): void => { if (!problems.includes(s)) problems.push(s); };
  if (!/^<\?xml\s+[^?]*\?>/.test(xml)) fail('Missing XML declaration');
  if (/[\u0000-\u0008\u000b\u000c\u000e-\u001f\ufffe\uffff]/u.test(xml)) fail('XML-forbidden control character');
  const stack: string[] = [], names = new Set<string>();
  const coordinates: {latitude: number; longitude: number}[] = [];
  let roots = 0, count = 0, cursor = 0, waypoint = false, waypointName = false;
  /** Decodes character data once, left to right; invalid references are reported through `fail` and decode to nothing. */
  const decode = (s: string): string => {
    let out = '';
    for (let i = 0; i < s.length;) {
      if (s[i] !== '&') { out += s[i++]; continue; }
      reference.lastIndex = i;
      const m = reference.exec(s);
      if (!m) { fail('Malformed XML entity reference'); i++; continue; }
      i += m[0].length;
      if (m[1]) { out += ENTITIES[m[1]]; continue; }
      const digits = (m[2] ?? m[3])!.replace(/^0+/, ''), n = digits.length > 8 ? Infinity : parseInt(digits || '0', m[2] === undefined ? 16 : 10);
      if (xmlCharacter(n)) out += String.fromCodePoint(n); else fail('XML-forbidden character reference');
    }
    return out;
  };
  for (const m of xml.matchAll(/<[^>]*>/g)) {
    const text = xml.slice(cursor, m.index), tag = m[0]; cursor = m.index + tag.length;
    decode(text);
    if (text.includes('<') || (!stack.length && text.trim())) fail('Malformed XML structure');
    if (tag.startsWith('<?')) { if (m.index !== 0) fail('Malformed XML declaration'); continue; }
    const parsed = /^<(\/?)([a-z][\w:-]*)([^<>]*?)(\/?)>$/i.exec(tag);
    if (!parsed) { fail('Malformed XML tag'); continue; }
    const [, closing, name, attrs = '', self] = parsed;
    if (closing) {
      if (attrs.trim() || self || stack.pop() !== name) fail(`Unbalanced ${name} tag`);
      if (name === 'wpt') { if (!waypointName) fail('Waypoint name missing'); waypoint = false; }
      continue;
    }
    if (!stack.length) {
      roots++;
      if (name !== 'gpx' || !/\bversion\s*=\s*(["'])1\.1\1/.test(attrs) || !/\bxmlns\s*=\s*(["'])http:\/\/www\.topografix\.com\/GPX\/1\/1\1/.test(attrs)) fail('Expected GPX 1.1 root');
    }
    for (const [, value] of readAttributes(attrs).list) decode(value);
    if (name === 'wpt' || name === 'trkpt') {
      const read = readAttributes(attrs), pair: number[] = [];
      if (!read.ok) fail(`Malformed ${name} attributes`);
      for (const [key, limit] of [['lat', 90], ['lon', 180]] as const) {
        const found = read.list.filter(([k]) => k === key), v = found[0]?.[1], n = Number(v);
        const valid = found.length === 1 && !!v?.trim() && Number.isFinite(n) && Math.abs(n) <= limit;
        if (!valid) fail(`Invalid ${name} ${key}`);
        pair.push(valid && read.ok ? n : NaN);
      }
      if (name === 'wpt') { count++; waypoint = true; waypointName = false; coordinates.push({latitude: pair[0]!, longitude: pair[1]!}); }
    }
    if (name === 'name') {
      const end = xml.indexOf('</name>', cursor), value = decode(xml.slice(cursor, end)).trim();
      if (self || end < 0 || !value || xml.slice(cursor, end).includes('<')) fail('Empty or malformed name');
      if (waypoint && stack.at(-1) === 'wpt') {
        waypointName = true;
        if (names.has(value.toLowerCase())) fail('Duplicate waypoint name');
        names.add(value.toLowerCase());
      }
    }
    if (!self) stack.push(name!);
  }
  if (stack.length) fail(`Unbalanced ${stack.at(-1)} tag`);
  if (roots !== 1 || !/<\/gpx>\s*$/.test(xml) || xml.slice(cursor).trim()) fail('Missing or invalid GPX root close');
  if (count !== expected.waypoints) fail('Waypoint count mismatch');
  // The screen sees exactly the pair the structural pass validated; an invalid pair is NaN, which is never screened clear.
  const verdicts = coordinates.map(c => screenPlace(screen ?? null, c));
  if (screen !== undefined && verdicts.some(placeRefused)) fail(verdicts.some(v => !v.screened) ? 'Protected areas not checked' : `Inside or near ${verdicts.find(v => placeRefused(v) && v.screened)?.name ?? 'a protected area'}`);
  return problems.length ? {ok: false, problems, screen: verdicts} : {ok: true, screen: verdicts};
}
