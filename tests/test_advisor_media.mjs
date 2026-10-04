// Text Advisor media intake (server/advisor/media.ts, TA-C4): magic-byte
// sniffing, JPEG/PNG metadata stripping (checked by re-walking the output),
// ingest with sha256 dedupe into a fake R2, the large-file multipart path, the
// upload-link token, the /u and /api/advisor/upload routes, /media serving and
// the consumer's download-before-handler step with its retries. JPEG and PNG
// bytes are built here; no binary fixtures. Offline, against the real migrations.
import test from 'node:test';
import assert from 'node:assert/strict';
import {createHash, createHmac, hkdfSync} from 'node:crypto';
import {readFileSync} from 'node:fs';
import {crc32} from 'node:zlib';
import {advisorDatabase, sqliteUnavailable} from './_advisor_d1.mjs';
import {memoryBucket} from './_advisor_r2.mjs';

const read = p => JSON.parse(readFileSync(new URL(p, import.meta.url)));
globalThis.REGIONS = {'morro-bay': read('../regions/morro-bay/region.json')};
globalThis.DEPLOYMENT = read('../deployments/production.json');
globalThis.SHELLS = {'/': '/index.0123456789.html', '/upload.html': '/upload.0123456789.html'};
globalThis.BUILD_ID = 'build-test';
const {default: worker} = await import('../server/index.ts');
const media = await import('../server/advisor/media.ts');
const {sniffMime, stripJpegMetadata, stripPngMetadata, exifOrientation, ingestMedia, mintUploadToken, verifyUploadToken, MediaFetchError, Sha256, BUFFER_LIMIT, PART_BYTES, UPLOAD_TOKEN_TTL_MS} = media;
const {deriveKeys, phoneHash} = await import('../server/advisor/contacts.ts');
const {consumeAdvisor, ADVISOR_QUEUE_NAME, MEDIA_RETRIES} = await import('../server/advisor/consumer.ts');
const {createBlueBubbles} = await import('../server/advisor/channels/bluebubbles.ts');
const {fetchMediaByRef, adapterForMedia, ADAPTERS} = await import('../server/advisor/channels/index.ts');
const {firstFile, boundaryOf} = await import('../server/advisor/multipart.ts');
const {UPLOAD_COPY} = await import('../web/advisor/copy.ts');

const dbTest = (name, fn) => test(name, {skip: sqliteUnavailable || false}, fn);
const KEY = Buffer.alloc(32, 9).toString('base64');
const T0 = Date.parse('2026-10-03T15:00:00Z');
const ON = {TEXT_ADVISOR_ENABLED: 'true', ADVISOR_PHONE_KEY: KEY};
const ORIGIN = 'https://skippercast.com';
const quiet = async fn => { const saved = {log: console.log, warn: console.warn, error: console.error}, lines = []; console.log = console.warn = console.error = (...a) => lines.push(a.join(' ')); try { return {value: await fn(), lines}; } finally { Object.assign(console, saved); } };
const bytes = (...parts) => new Uint8Array(parts.flatMap(p => typeof p === 'string' ? [...Buffer.from(p, 'latin1')] : Array.isArray(p) ? p : [...p]));
const sha = b => createHash('sha256').update(b).digest('hex');

// ---- JPEG and PNG builders -----------------------------------------------------

const seg = (marker, payload) => { const p = bytes(payload); return bytes([0xff, marker, (p.length + 2) >> 8, (p.length + 2) & 255], p); };
const SOF0 = seg(0xc0, [8, 0x01, 0xe0, 0x02, 0x80, 1, 1, 0x11, 0]);   // 640 x 480
const SCAN = bytes([0x12, 0x34, 0xff, 0x00, 0x56, 0xff, 0xd0, 0x78, 0x9a]);  // a stuffed 0xFF00 and an RST0 inside the scan
/** SOI, APP0, APP1 (EXIF+GPS), APP2 ICC, APP2 MPF, APP13, COM, DQT, SOF0, DHT, SOS + data, EOI, then a trailer. */
function jpeg() {
  return bytes([0xff, 0xd8],
    seg(0xe0, bytes('JFIF\0', [1, 1, 0, 0, 1, 0, 1, 0, 0])),
    seg(0xe1, bytes('Exif\0\0', 'MM\0*GPSLatitude=35.3658N')),
    seg(0xe2, bytes('ICC_PROFILE\0', [1, 1], 'display-p3-profile')),
    seg(0xe2, bytes('MPF\0', 'secondary-image-index')),
    seg(0xed, bytes('Photoshop 3.0\0', '8BIM-iptc')),
    seg(0xfe, bytes('camera owner: someone')),
    seg(0xdb, bytes([0], new Array(64).fill(1))),
    SOF0,
    seg(0xc4, bytes([0], new Array(16).fill(0), [])),
    seg(0xda, [1, 1, 0x00, 0, 63, 0]), SCAN,
    [0xff, 0xd9], 'TRAILER-MPF-IMAGE');
}
/** Marker walk of a JPEG for the assertions: the segment markers in order; throws if the structure is invalid. */
function walk(b) {
  assert.deepEqual([b[0], b[1]], [0xff, 0xd8], 'starts with SOI');
  const markers = ['SOI']; let i = 2;
  for (;;) {
    assert.equal(b[i], 0xff, `marker at ${i}`);
    const m = b[i + 1]; i += 2;
    if (m === 0xd9) { markers.push('EOI'); assert.equal(i, b.length, 'nothing after EOI'); return markers; }
    const len = (b[i] << 8) | b[i + 1];
    assert.ok(i + len <= b.length, 'segment fits');
    const name = m === 0xe2 ? `APP2:${Buffer.from(b.subarray(i + 2, i + 13)).toString('latin1')}` : m >= 0xe0 && m <= 0xef ? `APP${m - 0xe0}` : ({0xfe: 'COM', 0xdb: 'DQT', 0xc0: 'SOF0', 0xc4: 'DHT', 0xda: 'SOS'})[m] ?? m.toString(16);
    markers.push(name); i += len;
    if (m === 0xda) { while (!(b[i] === 0xff && b[i + 1] !== 0 && !(b[i + 1] >= 0xd0 && b[i + 1] <= 0xd7))) i++; }
  }
}

const chunk = (type, data = []) => { const d = bytes(data), t = Buffer.from(type, 'latin1'), len = Buffer.alloc(4), crc = Buffer.alloc(4); len.writeUInt32BE(d.length); crc.writeUInt32BE(crc32(Buffer.concat([t, d]))); return bytes(len, t, d, crc); };
const IHDR = (() => { const d = Buffer.alloc(13); d.writeUInt32BE(320, 0); d.writeUInt32BE(200, 4); d[8] = 8; d[9] = 2; return chunk('IHDR', d); })();
const PNG_SIG = bytes([0x89], 'PNG\r\n', [0x1a], '\n');
function png() {
  return bytes(PNG_SIG, IHDR, chunk('tEXt', 'Comment\0taken at the ramp'), chunk('eXIf', 'MM\0*GPS'), chunk('iTXt', 'XML:com.adobe.xmp\0\0\0\0\0<x/>'),
    chunk('zTXt', 'Raw\0\0xx'), chunk('tIME', [7, 234, 10, 3, 12, 0, 0]), chunk('pHYs', [0, 0, 11, 19, 0, 0, 11, 19, 1]), chunk('IDAT', [1, 2, 3, 4]), chunk('IEND'));
}
function pngChunks(b) {
  const out = []; let i = 8;
  while (i < b.length) {
    const len = Buffer.from(b.subarray(i, i + 4)).readUInt32BE(), type = Buffer.from(b.subarray(i + 4, i + 8)).toString('latin1');
    const crc = Buffer.from(b.subarray(i + 8 + len, i + 12 + len)).readUInt32BE();
    out.push({type, crcOk: crc === crc32(Buffer.from(b.subarray(i + 4, i + 8 + len)))});
    i += 12 + len;
  }
  return out;
}
const ftyp = brand => bytes([0, 0, 0, 24], 'ftyp', brand, [0, 0, 0, 0], brand, 'isom', new Array(40).fill(0));

// ---- sniffing ------------------------------------------------------------------

test('sniffMime accepts the photo, video and audio formats by magic bytes', () => {
  const cases = [
    [jpeg(), 'image/jpeg', 'jpg'], [png(), 'image/png', 'png'], [bytes('GIF89a', new Array(10).fill(0)), 'image/gif', 'gif'],
    [bytes('RIFF', [0, 0, 0, 0], 'WEBPVP8 '), 'image/webp', 'webp'],
    [ftyp('heic'), 'image/heic', 'heic'], [ftyp('heix'), 'image/heic', 'heic'], [ftyp('hevc'), 'image/heic', 'heic'], [ftyp('mif1'), 'image/heif', 'heif'],
    [ftyp('isom'), 'video/mp4', 'mp4'], [ftyp('mp42'), 'video/mp4', 'mp4'], [ftyp('qt  '), 'video/quicktime', 'mov'],
    [bytes([0, 0, 0, 16], 'moov', new Array(20).fill(0)), 'video/quicktime', 'mov'],
    [ftyp('M4A '), 'audio/mp4', 'm4a'], [bytes('caff', [0, 1, 0, 0]), 'audio/x-caf', 'caf'], [bytes('#!AMR\n', [0x3c]), 'audio/amr', 'amr'],
    [bytes([0xff, 0xf1, 0x50, 0x80, 0, 0x1f, 0xfc]), 'audio/aac', 'aac'],
  ];
  for (const [b, mime, ext] of cases) assert.deepEqual([sniffMime(b)?.mime, sniffMime(b)?.ext], [mime, ext], mime + ' ' + ext);
  assert.equal(sniffMime(ftyp('heic')).kind, 'image'); assert.equal(sniffMime(ftyp('isom')).kind, 'video'); assert.equal(sniffMime(ftyp('M4A ')).kind, 'audio');
});

test('sniffMime rejects HTML, SVG and anything else, whatever it claims to be', () => {
  for (const text of ['<!doctype html><html><script>alert(1)</script>', '<html><body>', '<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"/>',
    '<?xml version="1.0"?><svg/>', '   <script>x</script>', '%PDF-1.7', 'PK\u0003\u0004zip', '{"json":true}', '']) assert.equal(sniffMime(bytes(text)), null, JSON.stringify(text));
  assert.equal(sniffMime(ftyp('avif')), null, 'AVIF is not accepted');
  assert.equal(sniffMime(bytes([0xff, 0xfb, 0x90, 0x00])), null, 'an MP3 frame is not AAC');
  assert.equal(sniffMime(bytes([0, 0, 0, 4], 'ftypheic')), null, 'an impossible ftyp size');
  assert.equal(sniffMime(bytes('<!--ftypisom-->', new Array(20).fill(0x20))), null, 'text with ftyp at offset 4');
  assert.equal(sniffMime(bytes('<a>.moov.html', new Array(20).fill(0x20))), null, 'text with moov at offset 4');
});

// ---- stripping -----------------------------------------------------------------

test('stripJpegMetadata keeps SOI, APP0, the ICC APP2, tables, SOF and the scan; drops APP1, other APPn, COM and the trailer', () => {
  const input = jpeg();
  assert.deepEqual(walk(input.subarray(0, input.length - 'TRAILER-MPF-IMAGE'.length)),
    ['SOI', 'APP0', 'APP1', 'APP2:ICC_PROFILE', 'APP2:MPF\0seconda', 'APP13', 'COM', 'DQT', 'SOF0', 'DHT', 'SOS', 'EOI'], 'the input has every segment');
  const out = stripJpegMetadata(input);
  assert.equal(out.stripped, true);
  assert.deepEqual({width: out.width, height: out.height}, {width: 640, height: 480});
  assert.deepEqual(walk(out.bytes), ['SOI', 'APP0', 'APP2:ICC_PROFILE', 'DQT', 'SOF0', 'DHT', 'SOS', 'EOI'], 'the output still walks as a JPEG');
  const text = Buffer.from(out.bytes).toString('latin1');
  for (const gone of ['Exif', 'GPSLatitude', 'MPF', 'Photoshop', 'camera owner', 'TRAILER']) assert.ok(!text.includes(gone), gone);
  assert.ok(text.includes('display-p3-profile') && text.includes('JFIF'));
  assert.ok(Buffer.from(out.bytes).includes(Buffer.from(SCAN)), 'entropy-coded data (stuffed bytes and restart markers) copied unchanged');
  // Idempotent: a stripped file strips to itself.
  assert.deepEqual(stripJpegMetadata(out.bytes).bytes, out.bytes);
});

test('a truncated or malformed JPEG comes back unchanged with stripped false, never a throw', () => {
  const full = jpeg();
  for (const cut of [1, 3, 5, 20, 40, full.indexOf(0xda) + 3, full.length - 'TRAILER-MPF-IMAGE'.length - 4]) {
    const part = full.subarray(0, cut), out = stripJpegMetadata(part);
    assert.equal(out.stripped, false, `cut at ${cut}`); assert.equal(out.bytes, part, 'the same bytes object');
  }
  assert.equal(stripJpegMetadata(bytes([0xff, 0xd8, 0xff, 0xe1, 0x00, 0x01])).stripped, false, 'a segment length under 2');
  assert.equal(stripJpegMetadata(bytes([0xff, 0xd8, 0xff, 0xd9])).stripped, false, 'no frame header');
  assert.equal(stripJpegMetadata(png()).stripped, false, 'not a JPEG');
});

// ---- EXIF orientation (the one EXIF value kept, read before APP1 is dropped) ----------

/**
 * An APP1 EXIF segment: "Exif\0\0", a TIFF header in the given byte order and
 * IFD0 with these [tag, type, count, value] entries (a SHORT value left-justified
 * in its 4-byte field), followed by a GPS-looking string that must not survive.
 */
function exifApp1(order, entries) {
  const le = order === 'II';
  const u16 = v => le ? [v & 255, v >> 8] : [v >> 8, v & 255];
  const u32 = v => le ? [v & 255, (v >> 8) & 255, (v >> 16) & 255, v >>> 24] : [v >>> 24, (v >> 16) & 255, (v >> 8) & 255, v & 255];
  const ifd = [...u16(entries.length), ...entries.flatMap(([tag, type, count, value]) => [...u16(tag), ...u16(type), ...u32(count), ...(type === 3 ? [...u16(value), 0, 0] : u32(value))]), ...u32(0)];
  return seg(0xe1, bytes('Exif\0\0', order, u16(42), u32(8), ifd, 'GPSLatitude=35.3658N'));
}
/** The test JPEG with its APP1 replaced by `app1` (any bytes, or several segments). */
const jpegWith = (...app1) => bytes([0xff, 0xd8], seg(0xe0, bytes('JFIF\0', [1, 1, 0, 0, 1, 0, 1, 0, 0])), ...app1,
  seg(0xdb, bytes([0], new Array(64).fill(1))), SOF0, seg(0xc4, bytes([0], new Array(16).fill(0), [])), seg(0xda, [1, 1, 0x00, 0, 63, 0]), SCAN, [0xff, 0xd9]);
const MAKE = [0x010f, 2, 6, 0x40];         // an ASCII tag before Orientation, its value elsewhere (offset only)

test('stripJpegMetadata reads EXIF Orientation 6 in both byte orders and still drops the APP1', () => {
  for (const order of ['II', 'MM']) {
    const input = jpegWith(exifApp1(order, [MAKE, [0x0112, 3, 1, 6]]));
    const out = stripJpegMetadata(input);
    assert.equal(out.stripped, true, order);
    assert.equal(out.orientation, 6, `${order}: orientation 6`);
    assert.deepEqual(walk(out.bytes), ['SOI', 'APP0', 'DQT', 'SOF0', 'DHT', 'SOS', 'EOI'], `${order}: APP1 removed`);
    const text = Buffer.from(out.bytes).toString('latin1');
    assert.ok(!text.includes('Exif') && !text.includes('GPSLatitude') && !text.includes(order + '\0*') && !text.includes(order + '*\0'), `${order}: no EXIF bytes kept`);
  }
  for (const value of [1, 2, 3, 4, 5, 7, 8]) assert.equal(stripJpegMetadata(jpegWith(exifApp1('MM', [[0x0112, 3, 1, value]]))).orientation, value, `value ${value}`);
  // Only the first EXIF APP1 counts; an XMP APP1 is dropped without being read.
  const xmp = seg(0xe1, bytes('http://ns.adobe.com/xap/1.0/\0', '<x:xmpmeta tiff:Orientation="8"/>'));
  assert.equal(stripJpegMetadata(jpegWith(xmp, exifApp1('II', [[0x0112, 3, 1, 6]]), exifApp1('II', [[0x0112, 3, 1, 3]]))).orientation, 6);
  assert.equal(stripJpegMetadata(jpegWith(xmp)).orientation, 1, 'XMP alone: upright');
  assert.equal(stripJpegMetadata(jpegWith()).orientation, 1, 'no APP1: upright');
  assert.equal(stripPngMetadata(png()).orientation, 1, 'PNG: always 1');
});

test('malformed EXIF gives orientation 1, the file is still stripped, and nothing throws', () => {
  const app1 = payload => seg(0xe1, bytes('Exif\0\0', payload));
  const cases = {
    'the old fixture (no TIFF structure)': seg(0xe1, bytes('Exif\0\0', 'MM\0*GPSLatitude=35.3658N')),
    'empty after the header': app1([]),
    'bad byte order': app1(bytes('XX', [0, 42, 0, 0, 0, 8], [0, 0])),
    'not 42': app1(bytes('MM', [0, 43, 0, 0, 0, 8], [0, 0])),
    'IFD offset past the segment': app1(bytes('MM', [0, 42, 0x7f, 0xff, 0xff, 0xff])),
    'IFD offset inside the header': app1(bytes('MM', [0, 42, 0, 0, 0, 2], [0, 1])),
    'entry count past the segment': app1(bytes('II', [42, 0, 8, 0, 0, 0], [0xff, 0xff], [0x12, 0x01, 3, 0, 1, 0, 0, 0, 6, 0])),
    'orientation 9': exifApp1('MM', [[0x0112, 3, 1, 9]]),
    'orientation 0': exifApp1('II', [[0x0112, 3, 1, 0]]),
    'orientation as a LONG': exifApp1('MM', [[0x0112, 4, 1, 6]]),
    'orientation with count 0': exifApp1('II', [[0x0112, 3, 0, 6]]),
    'truncated entry': app1(bytes('MM', [0, 42, 0, 0, 0, 8], [0, 1], [0x01, 0x12, 0, 3, 0, 0])),
  };
  for (const [name, segment] of Object.entries(cases)) {
    const out = stripJpegMetadata(jpegWith(segment));
    assert.equal(out.stripped, true, name); assert.equal(out.orientation, 1, name);
    assert.deepEqual(walk(out.bytes), ['SOI', 'APP0', 'DQT', 'SOF0', 'DHT', 'SOS', 'EOI'], name);
  }
  assert.equal(stripJpegMetadata(jpeg()).orientation, 1, 'the full fixture');
  // exifOrientation itself never reads outside [at, end).
  const seg6 = exifApp1('II', [[0x0112, 3, 1, 6]]), payload = 4;
  assert.equal(exifOrientation(seg6, payload, seg6.length), 6);
  for (let end = payload; end < seg6.length - 'GPSLatitude=35.3658N'.length - 4; end++) assert.equal(exifOrientation(seg6, payload, end), 1, `cut at ${end}`);
  assert.equal(exifOrientation(seg6, payload, seg6.length + 10), 1, 'end past the buffer');
  // A truncated file with an EXIF APP1 is still unchanged, never a throw.
  const full = jpegWith(exifApp1('MM', [[0x0112, 3, 1, 6]]));
  for (const cut of [8, 20, 30, 50]) assert.equal(stripJpegMetadata(full.subarray(0, cut)).stripped, false, `cut at ${cut}`);
});

test('stripPngMetadata drops eXIf, tEXt, iTXt, zTXt and tIME and leaves every other chunk and CRC untouched', () => {
  const input = png(), out = stripPngMetadata(input);
  assert.equal(out.stripped, true); assert.deepEqual({width: out.width, height: out.height}, {width: 320, height: 200});
  assert.deepEqual(pngChunks(input).map(c => c.type), ['IHDR', 'tEXt', 'eXIf', 'iTXt', 'zTXt', 'tIME', 'pHYs', 'IDAT', 'IEND']);
  const chunks = pngChunks(out.bytes);
  assert.deepEqual(chunks.map(c => c.type), ['IHDR', 'pHYs', 'IDAT', 'IEND']);
  assert.ok(chunks.every(c => c.crcOk), 'every CRC still verifies');
  assert.deepEqual(out.bytes, bytes(PNG_SIG, IHDR, chunk('pHYs', [0, 0, 11, 19, 0, 0, 11, 19, 1]), chunk('IDAT', [1, 2, 3, 4]), chunk('IEND')), 'kept chunks byte for byte');
  for (const cut of [10, 30, input.length - 3]) assert.equal(stripPngMetadata(input.subarray(0, cut)).stripped, false, `cut at ${cut}`);
});

test('the incremental SHA-256 matches node:crypto for any chunking', () => {
  for (const size of [0, 1, 55, 56, 63, 64, 65, 1000, 70000]) {
    const data = new Uint8Array(size).map((_, i) => (i * 31 + 7) & 255);
    for (const step of [1, 7, 64, 1000, size || 1]) {
      const h = new Sha256(); for (let i = 0; i < size; i += step) h.update(data.subarray(i, i + step));
      assert.equal(h.digest(), sha(data), `size ${size} step ${step}`);
    }
  }
});

// ---- ingest --------------------------------------------------------------------

/** A database with one active contact and one inbound message carrying `refs.length` placeholder media rows. */
function setup({refs = ['att-1'], status = 'queued'} = {}) {
  const {sql, db} = advisorDatabase(), at = new Date(T0).toISOString();
  sql.prepare(`INSERT INTO advisor_contacts(id,phone_hash,phone_enc,channel,status,boat_id,last_seen_at,created_at,updated_at) VALUES('c1','h1','ENC-BLOB','imessage','active','b1',?,?,?)`).run(at, at, at);
  const ids = refs.map((_, i) => `m${i + 1}`);
  sql.prepare(`INSERT INTO advisor_messages(id,contact_id,direction,channel,provider_id,body,media_json,status,created_at) VALUES('in1','c1','in','imessage','g1',NULL,?,?,?)`).run(refs.length ? JSON.stringify(ids) : null, status, at);
  for (const [i, ref] of refs.entries())
    sql.prepare(`INSERT INTO advisor_media(id,contact_id,message_id,boat_id,kind,mime,bytes,r2_key,sha256,publish_state,provider_ref,created_at) VALUES(?,'c1','in1','b1','image','image/jpeg',1234,'','','private',?,?)`).run(ids[i], ref, at);
  return {sql, db};
}
const mediaRow = (sql, id) => sql.prepare('SELECT * FROM advisor_media WHERE id=?').get(id);
const body = b => () => Promise.resolve(new Response(b));
const input = (mediaId, b, extra = {}) => ({mediaId, contactId: 'c1', messageId: 'in1', boatId: 'b1', providerRef: 'att', fetchBytes: body(b), claimedMime: 'image/jpeg', name: null, ...extra});

dbTest('ingestMedia strips a JPEG, stores it under advisor/media/<contact>/<media>.jpg and fills the row', async () => {
  const {sql, db} = setup(), bucket = memoryBucket(), env = {DB: db, ADVISOR_MEDIA: bucket};
  const {value: result} = await quiet(() => ingestMedia(env, input('m1', jpeg()), T0));
  const stripped = stripJpegMetadata(jpeg()).bytes;
  assert.equal(result.status, 'stored');
  const row = mediaRow(sql, 'm1');
  assert.deepEqual({kind: row.kind, mime: row.mime, bytes: row.bytes, width: row.width, height: row.height, r2_key: row.r2_key, sha256: row.sha256, exif_stripped: row.exif_stripped, publish_state: row.publish_state},
    {kind: 'image', mime: 'image/jpeg', bytes: stripped.length, width: 640, height: 480, r2_key: 'advisor/media/c1/m1.jpg', sha256: sha(stripped), exif_stripped: 1, publish_state: 'private'});
  const object = bucket.objects.get('advisor/media/c1/m1.jpg');
  assert.deepEqual(object.bytes, stripped, 'the stored bytes are the stripped ones'); assert.equal(object.httpMetadata.contentType, 'image/jpeg');
  assert.ok(!Buffer.from(object.bytes).includes(Buffer.from('GPSLatitude')), 'no GPS in the bucket');
  assert.equal(row.orientation, 1, 'a JPEG without the tag is upright'); assert.deepEqual(object.customMetadata, {orientation: '1'});
});

dbTest('ingestMedia keeps a sideways JPEG\'s orientation on the row and the R2 object, not in the bytes; other formats get null', async () => {
  const {sql, db} = setup({refs: ['a', 'b', 'c']}), bucket = memoryBucket(), env = {DB: db, ADVISOR_MEDIA: bucket};
  const sideways = jpegWith(exifApp1('MM', [MAKE, [0x0112, 3, 1, 6]]));
  const {value: result} = await quiet(() => ingestMedia(env, input('m1', sideways), T0));
  assert.equal(result.orientation, 6);
  assert.equal(mediaRow(sql, 'm1').orientation, 6);
  const object = bucket.objects.get('advisor/media/c1/m1.jpg');
  assert.deepEqual(object.customMetadata, {orientation: '6'});
  assert.deepEqual(walk(object.bytes), ['SOI', 'APP0', 'DQT', 'SOF0', 'DHT', 'SOS', 'EOI'], 'no APP1 stored');
  // The same picture tagged upright strips to the same bytes: linked, with its own orientation.
  const {value: twin} = await quiet(() => ingestMedia(env, input('m2', jpegWith(exifApp1('II', [[0x0112, 3, 1, 1]]))), T0));
  assert.equal(twin.status, 'linked'); assert.equal(mediaRow(sql, 'm2').orientation, 1);
  await quiet(() => ingestMedia(env, input('m3', png(), {claimedMime: 'image/png'}), T0));
  assert.equal(mediaRow(sql, 'm3').orientation, null); assert.deepEqual(bucket.objects.get('advisor/media/c1/m3.png').customMetadata, {});
});

dbTest('the same bytes twice from one contact link to the first object; another contact gets its own copy', async () => {
  const {sql, db} = setup({refs: ['a', 'b']}), bucket = memoryBucket(), env = {DB: db, ADVISOR_MEDIA: bucket};
  await quiet(() => ingestMedia(env, input('m1', png(), {claimedMime: 'image/png'}), T0));
  const {value: second} = await quiet(() => ingestMedia(env, input('m2', png(), {claimedMime: 'image/png'}), T0));
  assert.equal(second.status, 'linked');
  assert.deepEqual(bucket.calls.put, ['advisor/media/c1/m1.png'], 'no second put');
  assert.equal(mediaRow(sql, 'm2').r2_key, 'advisor/media/c1/m1.png'); assert.equal(mediaRow(sql, 'm2').sha256, mediaRow(sql, 'm1').sha256);
  assert.deepEqual([mediaRow(sql, 'm2').width, mediaRow(sql, 'm2').height, mediaRow(sql, 'm2').exif_stripped], [320, 200, 1]);
  const at = new Date(T0).toISOString();
  sql.prepare(`INSERT INTO advisor_contacts(id,phone_hash,channel,last_seen_at,created_at,updated_at) VALUES('c2','h2','sms',?,?,?)`).run(at, at, at);
  await quiet(() => ingestMedia(env, {...input('x1', png()), contactId: 'c2', messageId: null}, T0));
  assert.equal(mediaRow(sql, 'x1').r2_key, 'advisor/media/c2/x1.png', 'dedupe is within a contact only');
});

dbTest('a renamed HTML or SVG file is rejected: kind unknown, publish_state rejected, nothing stored, counts logged', async () => {
  const {sql, db} = setup({refs: ['a', 'b']}), bucket = memoryBucket(), env = {DB: db, ADVISOR_MEDIA: bucket};
  const {value: html, lines} = await quiet(() => ingestMedia(env, input('m1', bytes('<!doctype html><script>steal()</script>')), T0));
  await quiet(() => ingestMedia(env, input('m2', bytes('<svg xmlns="http://www.w3.org/2000/svg"/>'), {claimedMime: 'image/svg+xml'}), T0));
  assert.equal(html.status, 'rejected'); assert.equal(html.reason, 'unsupported');
  for (const id of ['m1', 'm2']) {
    const row = mediaRow(sql, id);
    assert.deepEqual({kind: row.kind, publish_state: row.publish_state, r2_key: row.r2_key, mime: row.mime}, {kind: 'unknown', publish_state: 'rejected', r2_key: '', mime: 'application/octet-stream'}, id);
  }
  assert.equal(bucket.objects.size, 0);
  const logged = lines.join('\n');
  assert.match(logged, /advisor_media_rejected/); assert.ok(!logged.includes('steal'), 'never the content');
});

dbTest('HEIC passes through unstripped; a truncated JPEG and a file over 300 MB are rejected; a failed fetch throws MediaFetchError', async () => {
  const {sql, db} = setup({refs: ['a', 'b', 'c', 'd', 'e']}), bucket = memoryBucket(), env = {DB: db, ADVISOR_MEDIA: bucket};
  const heic = ftyp('heic');
  await quiet(() => ingestMedia(env, input('m1', heic, {claimedMime: 'image/jpeg'}), T0));
  assert.deepEqual([mediaRow(sql, 'm1').mime, mediaRow(sql, 'm1').exif_stripped, mediaRow(sql, 'm1').r2_key], ['image/heic', 0, 'advisor/media/c1/m1.heic'], 'the sniffed type wins over the claim');
  const {value: cut} = await quiet(() => ingestMedia(env, input('m2', jpeg().subarray(0, 40)), T0));
  assert.deepEqual([cut.status, cut.reason, mediaRow(sql, 'm2').publish_state], ['rejected', 'strip-failed', 'rejected'], 'an unwalkable JPEG is never stored with its metadata');
  const big = () => Promise.resolve(new Response(new ReadableStream({start(c) { c.enqueue(ftyp('isom')); }}), {headers: {'content-length': String(301 * 1024 * 1024)}}));
  const {value: tooBig} = await quiet(() => ingestMedia(env, input('m3', null, {fetchBytes: big}), T0));
  assert.deepEqual([tooBig.status, tooBig.reason], ['rejected', 'too-large']);
  await assert.rejects(ingestMedia(env, input('m4', null, {fetchBytes: () => Promise.reject(new TypeError('network down'))}), T0), MediaFetchError);
  await assert.rejects(ingestMedia(env, input('m5', null, {fetchBytes: () => Promise.resolve(new Response('gone', {status: 502}))}), T0), /http-502/);
  assert.equal(mediaRow(sql, 'm4').r2_key, '', 'a failed fetch leaves the placeholder as it was');
  await assert.rejects(ingestMedia({DB: db}, input('m4', jpeg()), T0), /storage unavailable/);
});

dbTest('a large video goes to R2 in multipart parts with the hash computed on the way; an identical one is deleted and linked', async () => {
  const {sql, db} = setup({refs: ['a', 'b']}), bucket = memoryBucket(), env = {DB: db, ADVISOR_MEDIA: bucket};
  const size = BUFFER_LIMIT + PART_BYTES + 12345, video = new Uint8Array(size);
  video.set(ftyp('mp42')); for (let i = 64; i < size; i += 4096) video[i] = i & 255;
  const stream = () => () => Promise.resolve(new Response(new ReadableStream({
    start(c) { for (let i = 0; i < size; i += 1 << 20) c.enqueue(video.slice(i, i + (1 << 20))); c.close(); },
  })));
  const {value: first} = await quiet(() => ingestMedia(env, input('m1', null, {fetchBytes: stream(), claimedMime: 'video/mp4'}), T0));
  assert.equal(first.status, 'stored');
  const [upload] = bucket.calls.multipart;
  assert.equal(upload.key, 'advisor/media/c1/m1.mp4'); assert.ok(upload.completed);
  assert.deepEqual(upload.parts, [PART_BYTES, PART_BYTES, PART_BYTES, size - 3 * PART_BYTES], 'equal parts, then the rest');
  const row = mediaRow(sql, 'm1');
  assert.deepEqual([row.kind, row.mime, row.bytes, row.sha256, row.exif_stripped], ['video', 'video/mp4', size, sha(video), 0]);
  assert.equal(bucket.objects.get('advisor/media/c1/m1.mp4').bytes.length, size);
  const {value: second} = await quiet(() => ingestMedia(env, input('m2', null, {fetchBytes: stream()}), T0));
  assert.equal(second.status, 'linked'); assert.equal(mediaRow(sql, 'm2').r2_key, 'advisor/media/c1/m1.mp4');
  assert.ok(!bucket.objects.has('advisor/media/c1/m2.mp4'), 'the duplicate upload was deleted');
});

// ---- upload tokens -------------------------------------------------------------

test('deriveKeys adds the upload subkey: HKDF-SHA256(master, info "upload")', async () => {
  const keys = await deriveKeys(KEY);
  assert.equal(keys.uploadKey.extractable, false);
  const token = await mintUploadToken(keys, 'c1', T0);
  const [contact, expiry, mac] = Buffer.from(token, 'base64url').toString().split('|');
  const k = Buffer.from(hkdfSync('sha256', Buffer.from(KEY, 'base64'), Buffer.alloc(0), 'upload', 32));
  assert.equal(mac, createHmac('sha256', k).update(`${contact}|${expiry}`).digest('hex'));
  assert.equal(contact, 'c1'); assert.equal(Number(expiry), (T0 + UPLOAD_TOKEN_TTL_MS) / 1000, '24 hours');
});

test('upload tokens round-trip, expire after 24 h and fail when tampered with or signed by another key', async () => {
  const keys = await deriveKeys(KEY), other = await deriveKeys(Buffer.alloc(32, 1).toString('base64'));
  const token = await mintUploadToken(keys, 'c_contact-1', T0);
  assert.match(token, /^[\w-]+$/, 'base64url, safe in a path');
  assert.equal(await verifyUploadToken(keys, token, T0 + 1000), 'c_contact-1');
  assert.equal(await verifyUploadToken(keys, token, T0 + UPLOAD_TOKEN_TTL_MS - 1000), 'c_contact-1');
  assert.equal(await verifyUploadToken(keys, token, T0 + UPLOAD_TOKEN_TTL_MS), null, 'expired');
  assert.equal(await verifyUploadToken(other, token, T0), null, 'another key');
  const [, expiry, mac] = Buffer.from(token, 'base64url').toString().split('|');
  const forge = s => Buffer.from(s).toString('base64url');
  assert.equal(await verifyUploadToken(keys, forge(`c_other|${expiry}|${mac}`), T0), null, 'another contact');
  assert.equal(await verifyUploadToken(keys, forge(`c_contact-1|${Number(expiry) + 86400}|${mac}`), T0), null, 'a longer expiry');
  for (const bad of ['', 'x', '!!!', forge('a|b'), forge('c1|1|zz'), 'a'.repeat(500)]) assert.equal(await verifyUploadToken(keys, bad, T0), null, bad.slice(0, 20));
  await assert.rejects(mintUploadToken(keys, 'bad id!', T0), /contact id/);
});

// ---- routes --------------------------------------------------------------------

const SHELL = '<!doctype html><html><head><title>Send a photo</title><script type="module" src="./assets/upload.0123456789.js"></script></head><body>upload page</body></html>';
const ASSETS = {fetch: async request => new URL(request.url).pathname === '/upload.0123456789' ? new Response(SHELL, {status: 200, headers: {'Content-Type': 'text/html'}}) : new Response('other', {status: 299})};
const queue = () => { const sent = []; return {sent, async send(m) { sent.push(m); }}; };
const call = (path, env, init) => worker.fetch(new Request(ORIGIN + path, init), {ASSETS, ...env});
/** An error body without the per-request id the request-id middleware adds to every JSON error. */
const errorBody = async response => { const {request_id: _id, ...rest} = await response.json(); return rest; };
async function token(contact = 'c1', at = Date.now()) { return mintUploadToken(await deriveKeys(KEY), contact, at); }
function uploadForm(content, name = 'IMG_0001.JPG', type = 'image/jpeg') {
  const form = new FormData(); form.append('note', 'hello'); form.append('file', new File([content], name, {type})); return form;
}

dbTest('GET /u/<token> serves the upload shell for a valid token and the gate 404 body otherwise', async () => {
  const {db} = setup(), env = {...ON, DB: db};
  const good = await call(`/u/${await token()}`, env);
  assert.equal(good.status, 200);
  assert.equal(good.headers.get('Cache-Control'), 'no-store'); assert.equal(good.headers.get('X-Robots-Tag'), 'noindex');
  assert.match(good.headers.get('Content-Security-Policy'), /form-action 'none'/, 'security headers apply to the page');
  const html = await good.text();
  assert.match(html, /upload page/); assert.match(html, /<head><base href="\/">/, 'assets resolve from the site root, not /u/');
  for (const bad of ['nope', await token('c1', Date.now() - UPLOAD_TOKEN_TTL_MS - 1000), await token('ghost')]) {
    const response = await call(`/u/${bad}`, env);
    assert.equal(response.status, 404, bad.slice(0, 12)); assert.deepEqual(await errorBody(response), {error: 'Not found'});
  }
  assert.equal((await call(`/u/${await token()}`, {DB: db, ADVISOR_PHONE_KEY: KEY})).status, 404, 'dark while TEXT_ADVISOR_ENABLED is off');
});

dbTest('POST /api/advisor/upload/<token> stores the file and a synthetic inbound message, then dispatches it like a webhook', async () => {
  const {sql, db} = setup({refs: []}), bucket = memoryBucket(), q = queue(), env = {...ON, DB: db, ADVISOR_MEDIA: bucket, ADVISOR_QUEUE: q};
  const t = await token();
  const {value: response} = await quiet(() => call(`/api/advisor/upload/${t}`, env, {method: 'POST', body: uploadForm(jpeg())}));
  assert.equal(response.status, 200); assert.deepEqual(await response.json(), {ok: true});
  const rows = sql.prepare("SELECT * FROM advisor_messages WHERE direction='in' AND provider_id LIKE 'upload:%'").all();
  assert.equal(rows.length, 1);
  const [message] = rows, [mediaId] = JSON.parse(message.media_json);
  assert.deepEqual({body: message.body, channel: message.channel, provider_id: message.provider_id, status: message.status, contact_id: message.contact_id},
    {body: '', channel: 'imessage', provider_id: `upload:${mediaId}`, status: 'queued', contact_id: 'c1'});
  const row = mediaRow(sql, mediaId);
  assert.deepEqual({message_id: row.message_id, boat_id: row.boat_id, r2_key: row.r2_key, exif_stripped: row.exif_stripped, width: row.width, provider_ref: row.provider_ref},
    {message_id: message.id, boat_id: 'b1', r2_key: `advisor/media/c1/${mediaId}.jpg`, exif_stripped: 1, width: 640, provider_ref: null});
  assert.deepEqual(q.sent, [{message_id: message.id}], 'enqueued exactly like a webhook message');
});

dbTest('the upload route refuses a bad token, a non-file body and an unsupported file without creating a message', async () => {
  const {sql, db} = setup({refs: []}), bucket = memoryBucket(), q = queue(), env = {...ON, DB: db, ADVISOR_MEDIA: bucket, ADVISOR_QUEUE: q};
  const bad = await call('/api/advisor/upload/forged', env, {method: 'POST', body: uploadForm(jpeg())});
  assert.equal(bad.status, 404); assert.deepEqual(await errorBody(bad), {error: 'Not found'});
  const t = await token();
  const {value: html} = await quiet(() => call(`/api/advisor/upload/${t}`, env, {method: 'POST', body: uploadForm('<html><script>x</script>', 'photo.jpg')}));
  assert.equal(html.status, 415);
  const {value: noFile} = await quiet(() => call(`/api/advisor/upload/${t}`, env, {method: 'POST', body: JSON.stringify({a: 1}), headers: {'Content-Type': 'application/json'}}));
  assert.equal(noFile.status, 400);
  const {value: huge} = await quiet(() => call(`/api/advisor/upload/${t}`, env, {method: 'POST', body: 'x', headers: {'Content-Type': 'multipart/form-data; boundary=b', 'Content-Length': String(400 * 1024 * 1024)}}));
  assert.equal(huge.status, 413);
  assert.equal(sql.prepare("SELECT COUNT(*) n FROM advisor_messages WHERE provider_id LIKE 'upload:%'").get().n, 0);
  assert.equal(q.sent.length, 0); assert.equal(bucket.objects.size, 0);
  assert.equal(sql.prepare("SELECT publish_state FROM advisor_media").get().publish_state, 'rejected', 'the refused file is recorded as rejected');
});

test('the multipart reader streams the first file part across arbitrary chunk boundaries', async () => {
  const content = new Uint8Array(70000).map((_, i) => (i * 13) & 255);
  const form = new Request('https://x/', {method: 'POST', body: uploadForm(content, 'clip.mov', 'video/quicktime')});
  const raw = new Uint8Array(await form.arrayBuffer()), type = form.headers.get('content-type');
  assert.ok(boundaryOf(type));
  for (const step of [1, 7, 4096]) {
    const request = new Request('https://x/', {method: 'POST', headers: {'content-type': type}, duplex: 'half',
      body: new ReadableStream({start(c) { for (let i = 0; i < raw.length; i += step) c.enqueue(raw.slice(i, i + step)); c.close(); }})});
    const file = await firstFile(request);
    assert.deepEqual([file.name, file.type], ['clip.mov', 'video/quicktime']);
    assert.deepEqual(new Uint8Array(await new Response(file.body).arrayBuffer()), content, `step ${step}`);
  }
  assert.equal(boundaryOf('application/json'), null);
});

/** A database with media rows in each publish state, and a bucket with their originals. */
function mediaSetup() {
  const {sql, db} = setup({refs: []}), at = new Date(T0).toISOString(), bucket = memoryBucket();
  const add = (id, state, {mime = 'image/jpeg', ext = 'jpg', stripped = 1, data = stripJpegMetadata(jpeg()).bytes} = {}) => {
    const key = `advisor/media/c1/${id}.${ext}`;
    sql.prepare(`INSERT INTO advisor_media(id,contact_id,kind,mime,bytes,r2_key,sha256,exif_stripped,publish_state,created_at) VALUES(?,'c1','image',?,?,?,?,?,?,?)`).run(id, mime, data.length, key, sha(data), stripped, state, at);
    bucket.objects.set(key, {bytes: data, httpMetadata: {contentType: mime}});
  };
  for (const state of ['private', 'queued', 'rejected', 'approved', 'posted']) add(state, state);
  add('heic', 'approved', {mime: 'image/heic', ext: 'heic', stripped: 0, data: ftyp('heic')});
  add('pic', 'approved', {mime: 'image/png', ext: 'png', data: stripPngMetadata(png()).bytes});
  return {sql, db, bucket};
}

dbTest('GET /media/<id>.jpg is 404 until the media is approved or posted, then serves it publicly cacheable and noindex', async () => {
  const {db, bucket} = mediaSetup(), env = {...ON, DB: db, ADVISOR_MEDIA: bucket};
  const missing = await call('/media/nope.jpg', env), missingBody = await errorBody(missing);
  assert.equal(missing.status, 404);
  for (const path of ['/media/private.jpg', '/media/queued.jpg', '/media/rejected.jpg', '/media/heic.jpg', '/media/heic.heic', '/media/approved.png', '/media/approved', '/media/approved.mp4', '/media/..%2Fx.jpg']) {
    const response = await call(path, env);
    assert.equal(response.status, 404, path); assert.deepEqual(await errorBody(response), missingBody, `${path}: same body as a missing id`);
  }
  for (const id of ['approved', 'posted']) {
    const response = await call(`/media/${id}.jpg`, env);
    assert.equal(response.status, 200, id);
    assert.equal(response.headers.get('Content-Type'), 'image/jpeg');
    assert.equal(response.headers.get('Cache-Control'), 'public, max-age=3600');
    assert.equal(response.headers.get('X-Robots-Tag'), 'noindex');
    assert.deepEqual(new Uint8Array(await response.arrayBuffer()), stripJpegMetadata(jpeg()).bytes);
  }
  const pic = await call('/media/pic.png', env);
  assert.equal(pic.status, 200); assert.equal(pic.headers.get('Content-Type'), 'image/png');
  assert.equal((await call('/media/approved.jpg', {DB: db, ADVISOR_MEDIA: bucket})).status, 404, 'dark while the flag is off');
});

dbTest('GET /media prefers the derived public.jpg once the media job has written it', async () => {
  const {db, bucket} = mediaSetup(), env = {...ON, DB: db, ADVISOR_MEDIA: bucket};
  bucket.objects.set('advisor/derived/approved/public.jpg', {bytes: bytes('DERIVED'), httpMetadata: {contentType: 'image/jpeg'}});
  bucket.objects.set('advisor/derived/heic/public.jpg', {bytes: bytes('DERIVED-HEIC'), httpMetadata: {contentType: 'image/jpeg'}});
  assert.equal(await (await call('/media/approved.jpg', env)).text(), 'DERIVED');
  const heic = await call('/media/heic.jpg', env);
  assert.equal(heic.status, 200, 'a HEIC is public only through its derived JPEG');
  assert.equal(heic.headers.get('Content-Type'), 'image/jpeg'); assert.equal(await heic.text(), 'DERIVED-HEIC');
  bucket.objects.set('advisor/derived/private/public.jpg', {bytes: bytes('X'), httpMetadata: {}});
  assert.equal((await call('/media/private.jpg', env)).status, 404, 'a derived file does not make private media public');
});

// ---- the consumer step ---------------------------------------------------------

function batchOf(bodies, attempts = 1) {
  const messages = bodies.map((body, i) => ({id: `q${i}`, body, attempts, timestamp: new Date(T0), outcome: null, delay: undefined,
    ack() { this.outcome = 'ack'; }, retry(o) { this.outcome = 'retry'; this.delay = o?.delaySeconds; }}));
  return {queue: ADVISOR_QUEUE_NAME, messages, ackAll() { for (const m of messages) m.ack(); }, retryAll() { for (const m of messages) m.retry(); }};
}
const silent = {name: 'test', async send() { return {providerId: 'p', status: 'sent'}; }};

dbTest('the consumer downloads, strips and stores every placeholder before the handler runs', async () => {
  const {sql, db} = setup({refs: ['att-1', 'att-2']}), bucket = memoryBucket(), env = {...ON, DB: db, ADVISOR_MEDIA: bucket};
  const fetched = [], seen = [];
  const fetchMediaByRef = async (ref, channel) => { fetched.push([ref, channel]); return new Response(ref === 'att-1' ? jpeg() : png()); };
  const handler = async ({message}) => { seen.push(...JSON.parse(message.media_json).map(id => mediaRow(sql, id).r2_key)); return {actions: [], intent: 'test'}; };
  const batch = batchOf([{message_id: 'in1'}]);
  await quiet(() => consumeAdvisor(batch, env, {channel: silent, handler, fetchMediaByRef, now: () => T0}));
  assert.deepEqual(fetched, [['att-1', 'imessage'], ['att-2', 'imessage']]);
  assert.deepEqual(seen, ['advisor/media/c1/m1.jpg', 'advisor/media/c1/m2.png'], 'the handler sees stored media');
  assert.equal(batch.messages[0].outcome, 'ack');
  const msg = sql.prepare("SELECT status,error FROM advisor_messages WHERE id='in1'").get();
  assert.deepEqual({...msg}, {status: 'done', error: null});
  // A redelivery downloads nothing again.
  sql.prepare("UPDATE advisor_messages SET status='queued' WHERE id='in1'").run();
  await quiet(() => consumeAdvisor(batchOf([{message_id: 'in1'}]), env, {channel: silent, handler, fetchMediaByRef, now: () => T0}));
  assert.equal(fetched.length, 2);
});

dbTest('a failed download retries the message twice, then the handler runs with that media rejected (fetch-failed)', async () => {
  assert.equal(MEDIA_RETRIES, 2);
  const {sql, db} = setup({refs: ['bad', 'good']}), bucket = memoryBucket(), env = {...ON, DB: db, ADVISOR_MEDIA: bucket};
  let calls = 0;
  const handler = async () => { calls++; return {actions: [], intent: 'test'}; };
  const fetchMediaByRef = async ref => { if (ref === 'bad') throw new TypeError('relay unreachable'); return new Response(jpeg()); };
  for (const attempt of [1, 2, 3]) {
    const batch = batchOf([{message_id: 'in1'}], attempt);
    await quiet(() => consumeAdvisor(batch, env, {channel: silent, handler, fetchMediaByRef, now: () => T0}));
    const msg = sql.prepare("SELECT status,error FROM advisor_messages WHERE id='in1'").get();
    if (attempt < 3) {
      assert.equal(batch.messages[0].outcome, 'retry', `attempt ${attempt}`);
      assert.deepEqual({...msg}, {status: 'queued', error: 'media-fetch'});
      assert.equal(calls, 0, 'the handler waits for the media');
      assert.equal(mediaRow(sql, 'm2').r2_key, 'advisor/media/c1/m2.jpg', 'what did download stays stored');
    } else {
      assert.equal(batch.messages[0].outcome, 'ack');
      assert.equal(calls, 1);
      assert.deepEqual({...msg}, {status: 'done', error: 'fetch-failed'});
      assert.deepEqual([mediaRow(sql, 'm1').kind, mediaRow(sql, 'm1').publish_state], ['unknown', 'rejected']);
    }
  }
  assert.deepEqual(bucket.calls.put, ['advisor/media/c1/m2.jpg'], 'the good file was stored once across the retries');
});

test('BlueBubbles fetchMediaByRef downloads the attachment by guid with the password and Access headers; stubs throw', async () => {
  const calls = [];
  const bb = createBlueBubbles({fetcher: async (url, init) => { calls.push({url: new URL(url), init}); return new Response('bytes'); }});
  const env = {BLUEBUBBLES_URL: 'https://relay.example.test', BLUEBUBBLES_PASSWORD: 'pw', CF_ACCESS_CLIENT_ID: 'id', CF_ACCESS_CLIENT_SECRET: 'sec'};
  assert.equal(await (await bb.fetchMediaByRef('at_0_7C2F3D4E-5061', env)).text(), 'bytes');
  assert.equal(calls[0].url.pathname, '/api/v1/attachment/at_0_7C2F3D4E-5061/download');
  await assert.rejects(bb.fetchMediaByRef('../../etc', env), /invalid attachment guid/);
  assert.equal(calls[0].url.searchParams.get('password'), 'pw'); assert.equal(calls[0].init.headers['CF-Access-Client-Id'], 'id');
  await assert.rejects(bb.fetchMediaByRef('x', {}), /not configured/);
  // TA-C3: web chat media are uploaded and stored before the message, so the web adapter has nothing to fetch by reference.
  assert.equal(ADAPTERS.web.fetchMediaByRef, undefined);
  assert.equal(adapterForMedia('imessage', 'guid').name, 'bluebubbles'); assert.equal(adapterForMedia('sms', 'guid').name, 'bluebubbles');
  assert.equal(adapterForMedia('sms', 'https://api.twilio.com/x').name, 'twilio'); assert.equal(adapterForMedia('web', 'x').name, 'web');
  await assert.rejects(fetchMediaByRef('x', 'web', env), /not implemented/);
});

test('upload page strings live in web/advisor/copy.ts', () => {
  for (const value of Object.values(UPLOAD_COPY)) assert.ok(typeof value === 'function' ? value(50).includes('50') : value.length > 3);
  const page = readFileSync(new URL('../dist/upload.html', import.meta.url), 'utf8'), script = readFileSync(new URL('../dist/advisor/upload.js', import.meta.url), 'utf8');
  assert.ok(!/<form\b/i.test(page), "no <form>: CSP form-action 'none'");
  assert.match(script, /from '\.\.\/\.\.\/web\/advisor\/copy\.ts'/);
  assert.match(page, /type="file"/);
});

test('phone hashing is unchanged by the third subkey', async () => {
  const k = Buffer.from(hkdfSync('sha256', Buffer.from(KEY, 'base64'), Buffer.alloc(0), 'hash', 32));
  assert.equal(await phoneHash(await deriveKeys(KEY), '+15555550101'), createHmac('sha256', k).update('+15555550101').digest('hex'));
});
