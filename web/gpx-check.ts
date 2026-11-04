// Delivery-time checks for our GPX 1.1 exporter; no DOM or navigation claims.
import {placeRefused, screenPlace, type PlaceVerdict} from '../dist/geo-screen.js';

/** BF-closures-everywhere: with a `screen` (null while it is not loaded), every waypoint and track point carries a verdict and one that is inside, near or not checked fails the file. Without one only the structure is checked. */
export function checkGpx(xml: string, expected: {waypoints: number}, screen?: unknown): {ok: true; screen: PlaceVerdict[]} | {ok: false; problems: string[]; screen: PlaceVerdict[]} {
  const problems: string[] = [], fail = (s: string): void => { if (!problems.includes(s)) problems.push(s); };
  if (!/^<\?xml\s+[^?]*\?>/.test(xml)) fail('Missing XML declaration');
  if (/[\u0000-\u0008\u000b\u000c\u000e-\u001f\ufffe\uffff]/u.test(xml)) fail('XML-forbidden control character');
  const stack: string[] = [], names = new Set<string>();
  let roots = 0, count = 0, cursor = 0, waypoint = false, waypointName = false;
  const decode = (s: string): string => s.replace(/&(amp|lt|gt|quot|apos|#\d+|#x[\da-f]+);/gi, (all, e: string) => {
    if (e.startsWith('#')) { const n = e[1] === 'x' ? parseInt(e.slice(2), 16) : Number(e.slice(1)); return n > 0 && n <= 0x10ffff ? String.fromCodePoint(n) : all; }
    return ({amp: '&', lt: '<', gt: '>', quot: '"', apos: "'"} as Record<string, string>)[e] ?? all;
  });
  for (const m of xml.matchAll(/<[^>]*>/g)) {
    const text = xml.slice(cursor, m.index), tag = m[0]; cursor = m.index + tag.length;
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
    if (name === 'wpt' || name === 'trkpt') {
      for (const [key, limit] of [['lat', 90], ['lon', 180]] as const) {
        const a = new RegExp(`\\b${key}\\s*=\\s*(["'])(.*?)\\1`).exec(attrs), v = a?.[2];
        if (!v?.trim() || !Number.isFinite(Number(v)) || Math.abs(Number(v)) > limit) fail(`Invalid ${name} ${key}`);
      }
      if (name === 'wpt') { count++; waypoint = true; waypointName = false; }
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
  const verdicts = [...xml.matchAll(/<(?:wpt|trkpt)\b[^>]*>/g)].map(m => {
    const num = (k: string) => Number(new RegExp(`\\b${k}\\s*=\\s*(["'])(.*?)\\1`).exec(m[0])?.[2]);
    return screenPlace(screen ?? null, {latitude: num('lat'), longitude: num('lon')});
  });
  if (screen !== undefined && verdicts.some(placeRefused)) fail(verdicts.some(v => !v.screened) ? 'Protected areas not checked' : `Inside or near ${verdicts.find(v => placeRefused(v) && v.screened)?.name ?? 'a protected area'}`);
  return problems.length ? {ok: false, problems, screen: verdicts} : {ok: true, screen: verdicts};
}
