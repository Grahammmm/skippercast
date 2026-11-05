// Reads private waypoint candidates out of an untrusted GPX 1.0 / 1.1 string. Pure and DOM-free: one forward cursor over sticky whole tokens
// (the approach of web/gpx-check.ts), so it runs in the unbundled account panel and under Node type stripping. It parses nothing it does not need
// to, and fetches, expands and evaluates nothing. It reads syntax and positions only: it does not screen, save, render, log or export anything.

/** Largest accepted input, in UTF-8 bytes (inclusive). This is a decoded-string API; a caller holding a File should check `File.size` first. */
export const MAX_GPX_BYTES = 1_048_576;
/** Most GPX-namespace `wpt` + `rtept` elements in one file (inclusive), rejected ones included. Deliberately not the 100 stored-spot capacity. */
export const MAX_GPX_POINTS = 1_000;
const MAX_DEPTH = 64;
/** The spots route's limits (server/routes/spots.ts NAME_UNITS in UTF-16 units, NOTE_CHARS in code points). */
const NAME_UNITS = 80, NOTE_CHARS = 1000;

export type GpxWaypoint = {name: string; lat: number; lon: number; note: string | null};
export type GpxPointRefusal = {
  /** 1-based source order among GPX `wpt` and `rtept` elements together. */
  index: number;
  element: 'wpt' | 'rtept';
  /** Decoded name cut to 80 units when it could be read safely; otherwise ''. */
  name: string;
  reason: 'route-point-not-imported' | 'invalid-placement' | 'invalid-latitude' | 'invalid-longitude' | 'invalid-waypoint-text';
};
export type GpxErrorCode = 'file-too-large' | 'too-many-points' | 'xml-depth-exceeded' | 'forbidden-declaration' | 'invalid-xml' | 'unsupported-gpx';
export type GpxWaypointResult =
  | {ok: true; waypoints: GpxWaypoint[]; rejected: GpxPointRefusal[]; ignoredTrackPoints: number}
  | {ok: false; error: {code: GpxErrorCode; message: string}};

const MESSAGES: Record<GpxErrorCode, string> = {
  'file-too-large': 'The GPX text is larger than the 1 MiB limit.',
  'too-many-points': 'The GPX file has more than 1,000 waypoints and route points.',
  'xml-depth-exceeded': 'The GPX file nests elements deeper than 64 levels.',
  'forbidden-declaration': 'The GPX file has a DOCTYPE, entity or other declaration, which is not read.',
  'invalid-xml': 'The GPX file is not well-formed XML.',
  'unsupported-gpx': 'The file is not a supported GPX 1.0 or 1.1 document.',
};
class Fatal extends Error { code: GpxErrorCode; constructor(code: GpxErrorCode) { super(code); this.code = code; } }
const fail = (code: GpxErrorCode): never => { throw new Fatal(code); };

const GPX_NAMESPACES = new Map([['http://www.topografix.com/GPX/1/0', '1.0'], ['http://www.topografix.com/GPX/1/1', '1.1']]);
const XML_NAMESPACE = 'http://www.w3.org/XML/1998/namespace';
const BASE_NAMESPACES = new Map([['', ''], ['xml', XML_NAMESPACE]]);

const NAME = '[A-Za-z_\\u0080-\\uFFFF][\\w.\\-\\u0080-\\uFFFF]*';
const qualified = new RegExp(`^(?:(${NAME}):)?(${NAME})$`), prefixName = new RegExp(`^${NAME}$`);
const declaration = /<\?xml[ \t\r\n]+version[ \t\r\n]*=[ \t\r\n]*(?:"([^"]*)"|'([^']*)')(?:[ \t\r\n]+encoding[ \t\r\n]*=[ \t\r\n]*(?:"([A-Za-z][\w.-]*)"|'([A-Za-z][\w.-]*)'))?(?:[ \t\r\n]+standalone[ \t\r\n]*=[ \t\r\n]*(?:"(?:yes|no)"|'(?:yes|no)'))?[ \t\r\n]*\?>/y;
const head = /<([^\s<>/=!?"'&]+)/y, close = /<\/([^\s<>/=!?"'&]+)[ \t\r\n]*>/y;
/** One whole quoted attribute (readAttributes' token, with XML whitespace and no raw `<` in the value), and the tag's end. */
const attribute = /[ \t\r\n]+([^\s=<>"'/&]+)[ \t\r\n]*=[ \t\r\n]*(?:"([^"<]*)"|'([^'<]*)')/y, tagEnd = /[ \t\r\n]*(\/?)>/y;
const ENTITIES: Record<string, string> = {amp: '&', lt: '<', gt: '>', quot: '"', apos: "'"};
const reference = /&(?:(amp|lt|gt|quot|apos)|#([0-9]+)|#x([0-9A-Fa-f]+));/y;
const xmlCharacter = (n: number): boolean => n === 9 || n === 10 || n === 13 || (n >= 0x20 && n <= 0xd7ff) || (n >= 0xe000 && n <= 0xfffd) || (n >= 0x10000 && n <= 0x10ffff);
/** XML 1.0 forbidden controls, 0xFFFE/0xFFFF and any unpaired UTF-16 surrogate, anywhere in the input. */
const illegal = /[\u0000-\u0008\u000b\u000c\u000e-\u001f\ufffe\uffff]|[\ud800-\udbff](?![\udc00-\udfff])|(?<![\ud800-\udbff])[\udc00-\udfff]/;
const decimal = /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$/;

/** Decodes character data once, left to right. Only the five XML entities and legal numeric references exist; anything else is fatal. */
function decode(s: string): string {
  if (!s.includes('&')) return s;
  let out = '', i = 0;
  for (;;) {
    const at = s.indexOf('&', i);
    if (at < 0) return out + s.slice(i);
    out += s.slice(i, at);
    reference.lastIndex = at;
    const m = reference.exec(s);
    if (!m) return fail('invalid-xml');
    i = at + m[0].length;
    if (m[1]) { out += ENTITIES[m[1]]; continue; }
    const digits = (m[2] ?? m[3])!.replace(/^0+/, ''), n = digits.length > 8 ? Infinity : parseInt(digits || '0', m[2] === undefined ? 16 : 10);
    if (!xmlCharacter(n)) fail('invalid-xml');
    out += String.fromCodePoint(n);
  }
}

/** Trimmed text cut to 80 UTF-16 units; a pair the cut would split loses its high half. */
function boundName(s: string): string {
  const cut = s.slice(0, NAME_UNITS), last = cut.charCodeAt(cut.length - 1);
  return last >= 0xd800 && last <= 0xdbff ? cut.slice(0, -1) : cut;
}
function boundNote(s: string): string {
  if (s.length <= NOTE_CHARS) return s;
  let end = 0;
  for (let n = 0; n < NOTE_CHARS && end < s.length; n++) end += s.codePointAt(end)! > 0xffff ? 2 : 1;
  return s.slice(0, end);
}
/** XML decimal latitude/longitude text, inclusive range; anything else (empty, exponent, hex, NaN, Infinity, out of range) is null. */
function coordinate(value: string | undefined, limit: number): number | null {
  const text = value?.replace(/^[ \t\r\n]+|[ \t\r\n]+$/g, '') ?? '';
  if (!decimal.test(text)) return null;
  const n = Number(text);
  return Number.isFinite(n) && Math.abs(n) <= limit ? n + 0 : null; // + 0 turns -0 into 0
}

type Field = {count: number; text: string; markup: boolean};
type Point = {index: number; element: 'wpt' | 'rtept'; placed: boolean; lat?: string; lon?: string; fields: {name?: Field; desc?: Field; cmt?: Field}};
type Frame = {qname: string; uri: string; namespaces: Map<string, string>; point?: Point; field?: Field};

/**
 * Reads the `<wpt>` elements of a GPX 1.0 or 1.1 document into private waypoint candidates. Success means only that syntax and positions were read.
 *
 * - A GPX `wpt` directly under the `gpx` root is a candidate; a GPX `wpt` anywhere else is refused as `invalid-placement`. Elements of other
 *   namespaces that happen to be called `wpt`, `rtept` or `trkpt` are extensions, never candidates.
 * - `rtept` is never imported: route vertices describe travel, not a fishing mark. Each is listed as `route-point-not-imported` (and counts toward the cap).
 *   Track points are validated as XML, counted in `ignoredTrackPoints` and never become candidates.
 * - Name: the direct GPX `name` child, trimmed, cut to 80 UTF-16 units without splitting a surrogate pair ('' when absent). Note: trimmed non-empty
 *   `desc`, else `cmt`, else null, cut to 1,000 code points (the spots route's limits). Notes are kept because the target store is private; they are literal
 *   untrusted text. Child markup or a repeated name/desc/cmt refuses the point as `invalid-waypoint-text`.
 * - lat/lon: one unqualified attribute each, XML decimal form, finite, latitude in [-90, 90] and longitude in [-180, 180] inclusive (the spots route
 *   itself excludes the endpoints, so a downstream save must handle them). Invalid ones are listed in `rejected`, never coerced or skipped.
 * - Fatal, with no partial candidates: input over {@link MAX_GPX_BYTES} UTF-8 bytes, over {@link MAX_GPX_POINTS} candidates, nesting over 64, any DOCTYPE
 *   or other `<!...>` declaration (so no entity is ever defined or expanded), malformed or truncated XML, unknown entities, illegal characters, and a
 *   root that is not exactly GPX 1.0 or 1.1. Messages are fixed text and never echo file contents.
 */
export function readGpxWaypoints(xml: string): GpxWaypointResult {
  try {
    return read(xml);
  } catch (e) {
    if (e instanceof Fatal) return {ok: false, error: {code: e.code, message: MESSAGES[e.code]}};
    throw e;
  }
}

function read(input: string): GpxWaypointResult {
  if (typeof input !== 'string') return fail('invalid-xml');
  if (input.length > MAX_GPX_BYTES || new TextEncoder().encode(input).length > MAX_GPX_BYTES) fail('file-too-large');
  if (illegal.test(input)) fail('invalid-xml');
  const s = input.startsWith('\ufeff') ? input.slice(1) : input;
  let pos = 0;
  if (s.startsWith('<?xml')) {
    declaration.lastIndex = 0;
    const d = declaration.exec(s);
    if (!d) fail('invalid-xml');
    if ((d![1] ?? d![2]) !== '1.0' || (d![3] ?? d![4] ?? 'utf-8').toLowerCase() !== 'utf-8') fail('unsupported-gpx');
    pos = d![0].length;
  }

  const stack: Frame[] = [], waypoints: GpxWaypoint[] = [], rejected: GpxPointRefusal[] = [];
  let rootUri: string | null = null, rootDone = false, points = 0, ignoredTrackPoints = 0;

  const finish = (p: Point): void => {
    const text = (f?: Field): string | null => !f ? '' : f.markup || f.count > 1 ? null : f.text.trim();
    const name = text(p.fields.name), desc = text(p.fields.desc), cmt = text(p.fields.cmt), lat = coordinate(p.lat, 90), lon = coordinate(p.lon, 180);
    const reason = p.element === 'rtept' ? 'route-point-not-imported' : !p.placed ? 'invalid-placement' : lat === null ? 'invalid-latitude'
      : lon === null ? 'invalid-longitude' : name === null || desc === null || cmt === null ? 'invalid-waypoint-text' : null;
    const bounded = name === null ? '' : boundName(name);
    if (reason) rejected.push({index: p.index, element: p.element, name: bounded, reason});
    else waypoints.push({name: bounded, lat: lat!, lon: lon!, note: desc ? boundNote(desc) : cmt ? boundNote(cmt!) : null});
  };

  while (pos < s.length) {
    const top = stack.at(-1);
    if (s.charCodeAt(pos) !== 60) { // character data
      let end = s.indexOf('<', pos);
      if (end < 0) end = s.length;
      const raw = s.slice(pos, end);
      if (raw.includes(']]>')) fail('invalid-xml');
      const text = decode(raw);
      if (!top) { if (/[^ \t\r\n]/.test(raw)) fail('invalid-xml'); } else if (top.field) top.field.text += text;
      pos = end;
    } else if (s.startsWith('<!--', pos)) {
      const end = s.indexOf('-->', pos + 4);
      if (end < 0) fail('invalid-xml');
      const body = s.slice(pos + 4, end);
      if (body.includes('--') || body.endsWith('-')) fail('invalid-xml');
      pos = end + 3;
    } else if (s.startsWith('<![CDATA[', pos)) {
      const end = s.indexOf(']]>', pos + 9);
      if (!top || end < 0) fail('invalid-xml');
      if (top!.field) top!.field.text += s.slice(pos + 9, end);
      pos = end + 3;
    } else if (s.startsWith('<!', pos)) {
      fail('forbidden-declaration');
    } else if (s.startsWith('<?', pos)) {
      fail('invalid-xml');
    } else if (s.startsWith('</', pos)) {
      close.lastIndex = pos;
      const m = close.exec(s);
      if (!m || !top || top.qname !== m[1]) fail('invalid-xml');
      pos = close.lastIndex;
      stack.pop();
      if (top!.point) finish(top!.point);
      if (!stack.length) rootDone = true;
    } else { // start tag
      head.lastIndex = pos;
      const h = head.exec(s), q = h && qualified.exec(h[1]!);
      if (!h || !q) return fail('invalid-xml');
      const list: [string, string][] = [], seen = new Set<string>();
      let at = head.lastIndex;
      for (let a: RegExpExecArray | null; (attribute.lastIndex = at, a = attribute.exec(s)); at = attribute.lastIndex) {
        if (seen.has(a[1]!)) fail('invalid-xml');
        seen.add(a[1]!);
        list.push([a[1]!, decode(a[2] ?? a[3] ?? '')]);
      }
      tagEnd.lastIndex = at;
      const e = tagEnd.exec(s);
      if (!e) fail('invalid-xml');
      pos = tagEnd.lastIndex;
      if (!top && rootDone) fail('invalid-xml');
      if (stack.length >= MAX_DEPTH) fail('xml-depth-exceeded');

      // Scoped namespaces: declarations on this element apply to it and its descendants; unqualified attributes stay in no namespace.
      let namespaces = top ? top.namespaces : BASE_NAMESPACES;
      for (const [key, value] of list) {
        if (key !== 'xmlns' && !key.startsWith('xmlns:')) continue;
        const prefix = key === 'xmlns' ? '' : key.slice(6);
        if (prefix && (!prefixName.test(prefix) || prefix === 'xmlns' || !value || (prefix === 'xml' && value !== XML_NAMESPACE))) fail('invalid-xml');
        if (namespaces === (top ? top.namespaces : BASE_NAMESPACES)) namespaces = new Map(namespaces);
        namespaces.set(prefix, value);
      }
      const uri = namespaces.get(q![1] ?? '');
      if (uri === undefined) return fail('invalid-xml');
      const plain = new Map<string, string>(), expanded = new Set<string>();
      for (const [key, value] of list) {
        if (key === 'xmlns' || key.startsWith('xmlns:')) continue;
        const k = qualified.exec(key);
        if (!k) fail('invalid-xml');
        const auri = k![1] === undefined ? '' : namespaces.get(k![1]);
        if (auri === undefined || expanded.has(`${auri}\0${k![2]}`)) fail('invalid-xml');
        expanded.add(`${auri}\0${k![2]}`);
        if (auri === '' && k![1] === undefined) plain.set(k![2]!, value);
      }

      const local = q![2]!, frame: Frame = {qname: h[1]!, uri, namespaces};
      if (!top) {
        if (local !== 'gpx' || !GPX_NAMESPACES.has(uri) || plain.get('version') !== GPX_NAMESPACES.get(uri)) fail('unsupported-gpx');
        rootUri = uri;
      } else {
        if (top.field) top.field.markup = true;
        if (uri === rootUri) {
          if (local === 'wpt' || local === 'rtept') {
            if (++points > MAX_GPX_POINTS) fail('too-many-points');
            frame.point = {index: points, element: local, placed: stack.length === 1, lat: plain.get('lat'), lon: plain.get('lon'), fields: {}};
          } else if (local === 'trkpt') ignoredTrackPoints++;
          else if (top.point && (local === 'name' || local === 'desc' || local === 'cmt')) {
            const f = top.point.fields[local];
            if (f) f.count++; else frame.field = top.point.fields[local] = {count: 1, text: '', markup: false};
            frame.field ??= f;
          }
        }
      }
      if (e![1]) { if (frame.point) finish(frame.point); if (!top) rootDone = true; } else stack.push(frame);
    }
  }
  if (stack.length || rootUri === null) fail('invalid-xml');
  rejected.sort((a, b) => a.index - b.index);
  return {ok: true, waypoints, rejected, ignoredTrackPoints};
}
