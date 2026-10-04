// Text Advisor media intake (docs/plans/text-advisor/02-data-model.md
// § advisor_media and § R2, 07 § EXIF and derived images, TA-C4).
//
//   provider attachment (or an upload) -> read with a 300 MB cap -> sniff the
//   real type from magic bytes -> strip JPEG/PNG metadata without decoding ->
//   sha256 -> link to an identical object of the same contact, or put
//   advisor/media/<contact_id>/<media_id>.<ext> in ADVISOR_MEDIA -> fill the row.
//
// Nothing the provider claims is trusted: the stored mime comes from the bytes,
// an unrecognised file (HTML, SVG, scripts, anything else) is never stored and
// its row becomes kind 'unknown', publish_state 'rejected'. A JPEG or PNG whose
// structure cannot be walked is rejected too, so no original that might still
// carry GPS data reaches the bucket (02: "no original with GPS data is ever
// stored"). HEIC, GIF, WebP, video and audio are stored as received with
// exif_stripped 0; /media never serves those originals (routes/advisor.ts).
//
// Files up to 24 MB are read into memory. A larger file (video, audio, or an
// image format that is stored as received) goes to R2 as a multipart upload in
// 10 MB parts while an incremental SHA-256 runs over it, so a 300 MB video
// never sits in the Worker's 128 MB of memory; its duplicate check happens
// after the upload, and a duplicate's new object is deleted again. A JPEG or
// PNG over 24 MB is rejected: stripping needs the whole file.
//
// The one EXIF value kept is a JPEG's Orientation (1-8): an iPhone stores the
// pixels unrotated and relies on it. It is read before APP1 is dropped and kept
// on the row (advisor_media.orientation) and the R2 object (custom metadata
// `orientation`), never in the stored bytes; the media job applies it to
// public.jpg, thumb.jpg and story.jpg.
import {advisorLog} from './log.ts';
import {hex, randomId} from './ids.ts';
// TA-M1: the advisor-media job is dispatched through the watchdog's GitHub client.
import {dispatchWorkflow} from '../watchdog.ts';
import type {Env} from '../env.ts';

export const MAX_MEDIA_BYTES = 300 * 1024 * 1024;   // 02 § R2 and 03 § uploads
export const BUFFER_LIMIT = 24 * 1024 * 1024;       // above this a file goes to R2 in parts
export const PART_BYTES = 10 * 1024 * 1024;         // R2 multipart parts (all but the last must be equal and >= 5 MiB)
const SNIFF_BYTES = 64;

export type MediaKind = 'image' | 'video' | 'audio';
export interface Sniffed {mime: string; ext: string; kind: MediaKind}

const ascii = (b: Uint8Array, at: number, n: number): string => { let s = ''; for (let i = at; i < at + n && i < b.length; i++) s += String.fromCharCode(b[i]!); return s; };
const u16 = (b: Uint8Array, at: number): number => (b[at]! << 8) | b[at + 1]!;
const u32 = (b: Uint8Array, at: number): number => ((b[at]! << 24) >>> 0) + (b[at + 1]! << 16) + (b[at + 2]! << 8) + b[at + 3]!;

const HEIC_BRANDS = new Set(['heic', 'heix', 'hevc', 'heim', 'heis', 'hevm', 'hevs']);
const HEIF_BRANDS = new Set(['mif1', 'msf1']);
const AUDIO_BRANDS = new Set(['M4A ', 'M4B ', 'M4P ', 'F4A ']);
// ISO-BMFF image formats that are neither HEIC nor a video: not accepted.
const OTHER_IMAGE_BRANDS = new Set(['avif', 'avis', 'jxl ', 'crx ']);

/**
 * The file's real type from its first bytes, or null (rejected). Accepts JPEG,
 * PNG, GIF, WebP, HEIC/HEIF (ftyp brands heic, heix, hevc, mif1 and their
 * sequence variants), QuickTime ('qt  ' brand or a bare moov box) and other
 * ISO-BMFF video as MP4, M4A, ADTS AAC, AMR and CAF audio. Anything else,
 * including HTML or SVG with an image extension, is null.
 */
export function sniffMime(bytes: Uint8Array): Sniffed | null {
  const b = bytes;
  if (b.length < 4) return null;
  if (b[0] === 0xff && b[1] === 0xd8 && b[2] === 0xff) return {mime: 'image/jpeg', ext: 'jpg', kind: 'image'};
  if (b.length >= 8 && ascii(b, 0, 8) === '\x89PNG\r\n\x1a\n') return {mime: 'image/png', ext: 'png', kind: 'image'};
  if (b.length >= 6 && (ascii(b, 0, 6) === 'GIF87a' || ascii(b, 0, 6) === 'GIF89a')) return {mime: 'image/gif', ext: 'gif', kind: 'image'};
  if (b.length >= 12 && ascii(b, 0, 4) === 'RIFF' && ascii(b, 8, 4) === 'WEBP') return {mime: 'image/webp', ext: 'webp', kind: 'image'};
  if (b.length >= 12 && ascii(b, 4, 4) === 'ftyp') {
    // An ftyp box is small (a brand list); a text file with "ftyp" at offset 4 has a huge "size".
    const size = u32(b, 0), brand = ascii(b, 8, 4);
    if (size < 16 || size > 4096 || !/^[\x20-\x7e]{4}$/.test(brand)) return null;
    if (HEIC_BRANDS.has(brand)) return {mime: 'image/heic', ext: 'heic', kind: 'image'};
    if (HEIF_BRANDS.has(brand)) return {mime: 'image/heif', ext: 'heif', kind: 'image'};
    if (AUDIO_BRANDS.has(brand)) return {mime: 'audio/mp4', ext: 'm4a', kind: 'audio'};
    if (OTHER_IMAGE_BRANDS.has(brand)) return null;
    if (brand === 'qt  ') return {mime: 'video/quicktime', ext: 'mov', kind: 'video'};
    return {mime: 'video/mp4', ext: 'mp4', kind: 'video'};
  }
  // Old QuickTime files start with a moov/mdat/wide/free box; the first size byte of a text file is printable.
  if (b.length >= 8 && b[0]! < 0x20 && ['moov', 'mdat', 'wide', 'free'].includes(ascii(b, 4, 4)) && u32(b, 0) >= 8) return {mime: 'video/quicktime', ext: 'mov', kind: 'video'};
  if (ascii(b, 0, 4) === 'caff') return {mime: 'audio/x-caf', ext: 'caf', kind: 'audio'};
  if (b.length >= 6 && ascii(b, 0, 6) === '#!AMR\n') return {mime: 'audio/amr', ext: 'amr', kind: 'audio'};
  // ADTS: 12 sync bits, then MPEG id, layer 00 (MP3 frames have a non-zero layer).
  if (b[0] === 0xff && (b[1]! & 0xf6) === 0xf0) return {mime: 'audio/aac', ext: 'aac', kind: 'audio'};
  return null;
}

/** `orientation`: the JPEG's EXIF Orientation (1-8) read before APP1 was dropped; 1 when absent or unreadable, and for PNG. */
export interface Stripped {bytes: Uint8Array; stripped: boolean; width: number | null; height: number | null; orientation: number}

const concat = (parts: Uint8Array[]): Uint8Array => {
  const out = new Uint8Array(parts.reduce((n, p) => n + p.length, 0));
  let at = 0; for (const p of parts) { out.set(p, at); at += p.length; }
  return out;
};
const ICC = 'ICC_PROFILE\0';
const isSof = (m: number): boolean => m >= 0xc0 && m <= 0xcf && m !== 0xc4 && m !== 0xc8 && m !== 0xcc;
const ORIENTATION_TAG = 0x0112;
const SHORT = 3;

/**
 * The Orientation tag (0x0112) of IFD0 in one APP1 segment, `at` the first
 * payload byte and `end` the segment's end: "Exif\0\0", a TIFF header in
 * either byte order ("II" or "MM", 42, the IFD0 offset), then IFD0's 12-byte
 * entries. 1-8, or 1 when the payload is not EXIF, has no tag, or is malformed
 * anywhere (it never reads past `end` and never throws). No other field is read.
 */
export function exifOrientation(b: Uint8Array, at: number, end: number): number {
  if (end > b.length || end - at < 6 + 8 || ascii(b, at, 6) !== 'Exif\0\0') return 1;
  const tiff = at + 6, order = ascii(b, tiff, 2);
  if (order !== 'II' && order !== 'MM') return 1;
  const le = order === 'II';
  const r16 = (p: number): number => le ? b[p]! | (b[p + 1]! << 8) : u16(b, p);
  const r32 = (p: number): number => le ? (b[p]! | (b[p + 1]! << 8) | (b[p + 2]! << 16) | (b[p + 3]! << 24)) >>> 0 : u32(b, p);
  if (r16(tiff + 2) !== 42) return 1;
  const ifd = tiff + r32(tiff + 4);
  if (ifd < tiff + 8 || ifd + 2 > end) return 1;
  const entries = r16(ifd);
  for (let k = 0; k < entries; k++) {
    const e = ifd + 2 + 12 * k;
    if (e + 12 > end) return 1;
    if (r16(e) !== ORIENTATION_TAG) continue;
    if (r16(e + 2) !== SHORT || r32(e + 4) < 1) return 1;
    const value = r16(e + 8);                     // a SHORT sits left-justified in the 4-byte value field
    return value >= 1 && value <= 8 ? value : 1;
  }
  return 1;
}

/**
 * A JPEG without metadata, by a marker walk from SOI (no decoding). Kept: SOI,
 * APP0 (JFIF/JFXX), APP2 segments whose payload starts "ICC_PROFILE\0" (so
 * Display P3 photos keep their colours), DQT, DHT, DAC, SOF*, DRI, SOS with its
 * entropy-coded data, any later tables and scans of a progressive JPEG, and
 * EOI. Dropped: every other APPn (EXIF, GPS, XMP, MPF, maker notes) and COM,
 * and anything after EOI (an iPhone's MPF secondary images sit there).
 * Width and height come from the SOF header. Before the first EXIF APP1 is
 * dropped its Orientation tag is read (exifOrientation) and returned as
 * `orientation`, so the upright view survives without keeping any EXIF.
 * A file that is not a JPEG, or is truncated anywhere, comes back unchanged
 * with stripped false; it never throws.
 */
export function stripJpegMetadata(bytes: Uint8Array): Stripped {
  const unchanged: Stripped = {bytes, stripped: false, width: null, height: null, orientation: 1};
  const b = bytes, n = b.length;
  if (n < 4 || b[0] !== 0xff || b[1] !== 0xd8) return unchanged;
  const parts: Uint8Array[] = [b.subarray(0, 2)];
  let i = 2, width: number | null = null, height: number | null = null, orientation: number | null = null;
  for (;;) {
    if (i >= n || b[i] !== 0xff) return unchanged;
    while (i < n && b[i] === 0xff) i++;          // fill bytes before a marker
    if (i >= n) return unchanged;
    const marker = b[i]!, start = i - 1;
    i++;
    if (marker === 0xd9) { parts.push(Uint8Array.of(0xff, 0xd9)); break; }          // EOI: stop, drop any trailer
    if (marker === 0x01 || (marker >= 0xd0 && marker <= 0xd7)) { parts.push(Uint8Array.of(0xff, marker)); continue; }
    if (i + 2 > n) return unchanged;
    const length = u16(b, i);
    if (length < 2 || i + length > n) return unchanged;
    const segment = b.subarray(start, i + length), payload = i + 2;
    i += length;
    if (marker === 0xda) {
      // SOS: keep the header and the entropy-coded data up to the next real marker.
      let j = i;
      for (;;) {
        if (j + 1 >= n) return unchanged;           // scan data never ended: truncated
        if (b[j] === 0xff) {
          let k = j + 1;
          while (k < n && b[k] === 0xff) k++;
          if (k >= n) return unchanged;
          const next = b[k]!;
          if (next === 0x00 || (next >= 0xd0 && next <= 0xd7)) { j = k + 1; continue; }   // stuffed byte or restart marker
          break;
        }
        j++;
      }
      parts.push(b.subarray(start, j));
      i = j;
      continue;
    }
    if (isSof(marker)) {
      if (length < 7) return unchanged;
      height = u16(b, payload + 1); width = u16(b, payload + 3);
      parts.push(segment); continue;
    }
    if (marker === 0xe0) { parts.push(segment); continue; }
    if (marker === 0xe2 && length >= 2 + ICC.length && ascii(b, payload, ICC.length) === ICC) { parts.push(segment); continue; }
    if (marker === 0xe1 && orientation === null && length >= 2 + 6 && ascii(b, payload, 6) === 'Exif\0\0') orientation = exifOrientation(b, payload, i);
    if ((marker >= 0xe1 && marker <= 0xef) || marker === 0xfe) continue;              // other APPn (EXIF too, once read), COM
    parts.push(segment);                                                              // DQT, DHT, DAC, DRI, DNL, ...
  }
  if (width === null) return unchanged;           // no frame header: not an image we can vouch for
  return {bytes: concat(parts), stripped: true, width, height, orientation: orientation ?? 1};
}

const PNG_DROP = new Set(['eXIf', 'tEXt', 'iTXt', 'zTXt', 'tIME']);

/**
 * A PNG without its text, EXIF and time chunks (eXIf, tEXt, iTXt, zTXt, tIME).
 * Every other chunk is copied byte for byte with its CRC; nothing after IEND is
 * kept. Width and height come from IHDR. Not a PNG, or truncated: unchanged
 * with stripped false; it never throws.
 */
export function stripPngMetadata(bytes: Uint8Array): Stripped {
  const unchanged: Stripped = {bytes, stripped: false, width: null, height: null, orientation: 1};
  const b = bytes, n = b.length;
  if (n < 8 || ascii(b, 0, 8) !== '\x89PNG\r\n\x1a\n') return unchanged;
  const parts: Uint8Array[] = [b.subarray(0, 8)];
  let i = 8, width: number | null = null, height: number | null = null, ended = false;
  while (i < n) {
    if (i + 12 > n) return unchanged;
    const length = u32(b, i), type = ascii(b, i + 4, 4), end = i + 12 + length;
    if (length > 0x7fffffff || end > n || !/^[A-Za-z]{4}$/.test(type)) return unchanged;
    if (type === 'IHDR') { if (length < 8) return unchanged; width = u32(b, i + 8); height = u32(b, i + 12); }
    if (!PNG_DROP.has(type)) parts.push(b.subarray(i, end));
    i = end;
    if (type === 'IEND') { ended = true; break; }
  }
  if (!ended || width === null) return unchanged;
  return {bytes: concat(parts), stripped: true, width, height, orientation: 1};
}

// ---- incremental SHA-256 (for streamed uploads; WebCrypto digests only whole buffers) ----

const K = new Uint32Array([
  0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5, 0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3,
  0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174, 0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
  0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967, 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13,
  0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85, 0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
  0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3, 0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208,
  0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2]);

/** SHA-256 fed in chunks: update(bytes) any number of times, then digest() once (lowercase hex). */
export class Sha256 {
  private h = new Uint32Array([0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19]);
  private block = new Uint8Array(64);
  private filled = 0;
  private total = 0;
  private w = new Uint32Array(64);

  update(data: Uint8Array): this {
    let at = 0;
    this.total += data.length;
    if (this.filled) {
      const take = Math.min(64 - this.filled, data.length);
      this.block.set(data.subarray(0, take), this.filled); this.filled += take; at = take;
      if (this.filled < 64) return this;
      this.compress(this.block, 0); this.filled = 0;
    }
    for (; at + 64 <= data.length; at += 64) this.compress(data, at);
    if (at < data.length) { this.block.set(data.subarray(at), 0); this.filled = data.length - at; }
    return this;
  }

  digest(): string {
    const bits = this.total * 8, tail = new Uint8Array(((this.filled + 9 + 63) >> 6) << 6);
    tail.set(this.block.subarray(0, this.filled)); tail[this.filled] = 0x80;
    const view = new DataView(tail.buffer);
    view.setUint32(tail.length - 8, Math.floor(bits / 0x100000000)); view.setUint32(tail.length - 4, bits >>> 0);
    for (let at = 0; at < tail.length; at += 64) this.compress(tail, at);
    const out = new Uint8Array(32), dv = new DataView(out.buffer);
    for (let i = 0; i < 8; i++) dv.setUint32(i * 4, this.h[i]!);
    return hex(out.buffer);
  }

  private compress(d: Uint8Array, at: number): void {
    const w = this.w, h = this.h;
    for (let t = 0; t < 16; t++) w[t] = (d[at + 4 * t]! << 24) | (d[at + 4 * t + 1]! << 16) | (d[at + 4 * t + 2]! << 8) | d[at + 4 * t + 3]!;
    for (let t = 16; t < 64; t++) {
      const a = w[t - 15]!, b = w[t - 2]!;
      const s0 = ((a >>> 7) | (a << 25)) ^ ((a >>> 18) | (a << 14)) ^ (a >>> 3);
      const s1 = ((b >>> 17) | (b << 15)) ^ ((b >>> 19) | (b << 13)) ^ (b >>> 10);
      w[t] = (w[t - 16]! + s0 + w[t - 7]! + s1) | 0;
    }
    let a = h[0]!, b = h[1]!, c = h[2]!, e0 = h[3]!, e = h[4]!, f = h[5]!, g = h[6]!, hh = h[7]!;
    for (let t = 0; t < 64; t++) {
      const S1 = ((e >>> 6) | (e << 26)) ^ ((e >>> 11) | (e << 21)) ^ ((e >>> 25) | (e << 7));
      const t1 = (hh + S1 + ((e & f) ^ (~e & g)) + K[t]! + w[t]!) | 0;
      const S0 = ((a >>> 2) | (a << 30)) ^ ((a >>> 13) | (a << 19)) ^ ((a >>> 22) | (a << 10));
      const t2 = (S0 + ((a & b) ^ (a & c) ^ (b & c))) | 0;
      hh = g; g = f; f = e; e = (e0 + t1) | 0; e0 = c; c = b; b = a; a = (t1 + t2) | 0;
    }
    h[0] = (h[0]! + a) | 0; h[1] = (h[1]! + b) | 0; h[2] = (h[2]! + c) | 0; h[3] = (h[3]! + e0) | 0;
    h[4] = (h[4]! + e) | 0; h[5] = (h[5]! + f) | 0; h[6] = (h[6]! + g) | 0; h[7] = (h[7]! + hh) | 0;
  }
}

// ---- intake ---------------------------------------------------------------------

/** The download failed (network, timeout, a non-2xx answer, the stream broke): retryable. */
export class MediaFetchError extends Error {
  constructor(message: string) { super(message); this.name = 'MediaFetchError'; }
}

export interface IngestInput {
  mediaId?: string;                // the placeholder advisor_media row; omitted: a new row (uploads)
  contactId: string;
  messageId: string | null;
  boatId: string | null;
  providerRef: string | null;
  fetchBytes: () => Promise<Response>;
  claimedMime: string | null;
  name: string | null;
}
export type IngestStatus = 'stored' | 'linked' | 'rejected';
export interface IngestResult {
  id: string; status: IngestStatus; reason?: string;
  mime: string | null; bytes: number; width: number | null; height: number | null; r2Key: string; sha256: string; exifStripped: boolean;
  /** A JPEG's EXIF Orientation (1-8), kept on the row and the R2 object; null for any other format. */
  orientation: number | null;
}

export const mediaKey = (contactId: string, mediaId: string, ext: string): string => `advisor/media/${contactId}/${mediaId}.${ext}`;
export const derivedKey = (mediaId: string): string => `advisor/derived/${mediaId}/public.jpg`;
const ID = /^[\w-]{1,64}$/;

/** Read the first `want` bytes (or all of a shorter stream). The returned reader continues after them. */
async function readHead(reader: ReadableStreamDefaultReader<Uint8Array>, want: number): Promise<{head: Uint8Array; done: boolean}> {
  const parts: Uint8Array[] = []; let size = 0;
  while (size < want) {
    const {done, value} = await reader.read();
    if (done) return {head: concat(parts), done: true};
    if (value?.length) { parts.push(value); size += value.length; }
  }
  return {head: concat(parts), done: false};
}

/** The stream after `head` in memory, up to `limit` bytes; past that, the bytes read so far and the reader for the rest. */
async function readUpTo(reader: ReadableStreamDefaultReader<Uint8Array>, head: Uint8Array, limit: number): Promise<{all: Uint8Array} | {partial: Uint8Array[]; size: number}> {
  const parts = [head]; let size = head.length;
  for (;;) {
    const {done, value} = await reader.read();
    if (done) return {all: concat(parts)};
    if (!value?.length) continue;
    parts.push(value); size += value.length;
    if (size > limit) return {partial: parts, size};
  }
}

const nowIso = (now: number | Date): string => new Date(now).toISOString();

async function ensureRow(db: D1Database, id: string, input: IngestInput, at: string): Promise<void> {
  await db.prepare(`INSERT INTO advisor_media(id,contact_id,message_id,boat_id,kind,mime,bytes,r2_key,sha256,publish_state,provider_ref,created_at)
    VALUES(?,?,?,?,?,?,0,'','','private',?,?) ON CONFLICT(id) DO NOTHING`)
    .bind(id, input.contactId, input.messageId, input.boatId, 'image', (input.claimedMime ?? 'application/octet-stream').slice(0, 100), input.providerRef, at).run();
}

/** Mark a media row rejected: kind 'unknown', publish_state 'rejected', nothing stored. Logs counts only. */
export async function rejectMedia(db: D1Database, mediaId: string, reason: string, bytes = 0): Promise<IngestResult> {
  await db.prepare("UPDATE advisor_media SET kind='unknown',publish_state='rejected',mime='application/octet-stream',bytes=? WHERE id=?").bind(bytes, mediaId).run();
  advisorLog('warn', 'advisor_media_rejected', {reason, bytes, count: 1});
  return {id: mediaId, status: 'rejected', reason, mime: null, bytes, width: null, height: null, r2Key: '', sha256: '', exifStripped: false, orientation: null};
}

interface Fill {mime: string; kind: MediaKind; bytes: number; width: number | null; height: number | null; r2Key: string; sha256: string; exifStripped: boolean; orientation: number | null}
async function fillRow(db: D1Database, mediaId: string, f: Fill): Promise<void> {
  await db.prepare('UPDATE advisor_media SET mime=?,kind=?,bytes=?,width=COALESCE(?,width),height=COALESCE(?,height),r2_key=?,sha256=?,exif_stripped=?,orientation=? WHERE id=?')
    .bind(f.mime, f.kind, f.bytes, f.width, f.height, f.r2Key, f.sha256, f.exifStripped ? 1 : 0, f.orientation, mediaId).run();
}
interface Twin {r2_key: string; width: number | null; height: number | null; exif_stripped: number}
/** An already stored object of this contact with the same bytes, if any. */
async function duplicateOf(db: D1Database, contactId: string, mediaId: string, sha: string): Promise<Twin | null> {
  return db.prepare("SELECT r2_key,width,height,exif_stripped FROM advisor_media WHERE contact_id=? AND sha256=? AND r2_key<>'' AND id<>? ORDER BY created_at LIMIT 1")
    .bind(contactId, sha, mediaId).first<Twin>();
}

const fetchFailure = (error: unknown): boolean => ['TypeError', 'TimeoutError', 'AbortError'].includes((error as Error)?.name);

/**
 * Download (or read an upload), sniff, strip, hash, dedupe and store one media
 * item, filling its advisor_media row (02 § advisor_media); a row is created
 * when `mediaId` is omitted or does not exist yet. Throws MediaFetchError when
 * the bytes could not be fetched (the caller may retry) and an ordinary Error
 * when storage is unavailable. Returns 'rejected' for a file over 300 MB, an
 * unrecognised type, or a JPEG/PNG that cannot be walked or is over 24 MB.
 * `now` stamps created_at of a new row.
 */
export async function ingestMedia(env: Env, input: IngestInput, now: number | Date = Date.now()): Promise<IngestResult> {
  const db = env.DB, bucket = env.ADVISOR_MEDIA;
  if (!db || !bucket) throw Error('media storage unavailable');
  const id = input.mediaId ?? randomId();
  if (!ID.test(id) || !ID.test(input.contactId)) throw Error('invalid media or contact id');
  await ensureRow(db, id, input, nowIso(now));

  let response: Response;
  try { response = await input.fetchBytes(); }
  catch (error) { throw new MediaFetchError(`fetch failed: ${(error as Error)?.name === 'TimeoutError' ? 'timeout' : 'network'}`); }
  if (!response.ok || !response.body) { await response.body?.cancel().catch(() => {}); throw new MediaFetchError(`fetch failed: http-${response.status}`); }
  const declared = Number(response.headers.get('content-length'));
  if (declared > MAX_MEDIA_BYTES) { await response.body.cancel().catch(() => {}); return rejectMedia(db, id, 'too-large', declared); }

  const reader = response.body.getReader();
  try {
    const {head} = await readHead(reader, SNIFF_BYTES);
    const sniffed = sniffMime(head);
    if (!sniffed) { await reader.cancel().catch(() => {}); return rejectMedia(db, id, 'unsupported', head.length); }
    if (input.claimedMime && input.claimedMime.split(';')[0]!.trim().toLowerCase() !== sniffed.mime) advisorLog('info', 'advisor_media_mime_mismatch', {sniffed: sniffed.mime, count: 1});
    const strippable = sniffed.mime === 'image/jpeg' || sniffed.mime === 'image/png';

    const read = await readUpTo(reader, head, BUFFER_LIMIT);
    if ('partial' in read) {
      if (strippable) { await reader.cancel().catch(() => {}); return rejectMedia(db, id, 'too-large', read.size); }
      return await multipartToBucket(env, id, input, sniffed, reader, read.partial);
    }
    const all = read.all;
    let stored = all, width: number | null = null, height: number | null = null, exifStripped = false, orientation: number | null = null;
    if (strippable) {
      const jpeg = sniffed.mime === 'image/jpeg', result = jpeg ? stripJpegMetadata(all) : stripPngMetadata(all);
      if (!result.stripped) return rejectMedia(db, id, 'strip-failed', all.length);
      ({width, height} = result); stored = result.bytes; exifStripped = true;
      if (jpeg) orientation = result.orientation;
    }
    const sha = hex(await crypto.subtle.digest('SHA-256', stored));
    return await store(env, id, input, sniffed, {bytes: stored.length, width, height, sha, exifStripped, orientation},
      key => bucket.put(key, stored, {httpMetadata: {contentType: sniffed.mime}, ...(orientation !== null ? {customMetadata: {orientation: String(orientation)}} : {})}).then(() => {}));
  } catch (error) {
    await reader.cancel().catch(() => {});
    if (fetchFailure(error)) throw new MediaFetchError('fetch failed: stream');
    throw error;
  }
}

interface Measured {bytes: number; width: number | null; height: number | null; sha: string; exifStripped: boolean; orientation: number | null}

/**
 * TA-M1: an image vision cannot read as stored (over 4.5 MB, HEIC), or a JPEG
 * stored sideways (orientation 2-8), has the media job started for its upright public.jpg.
 */
async function deriveIfNeeded(env: Env, row: {kind: string; mime: string; bytes: number; orientation: number | null}): Promise<void> {
  if (needsDerivedForVision(row) || (row.kind === 'image' && (row.orientation ?? 1) !== 1)) await requestMediaJob(env);
}

/** Link to the contact's identical object, or put a new one; then fill the row. */
async function store(env: Env, id: string, input: IngestInput, sniffed: Sniffed, m: Measured, put: (key: string) => Promise<void>): Promise<IngestResult> {
  const db = env.DB!;
  // orientation is this row's own (two originals that differ only in EXIF strip to the same bytes).
  const base = {mime: sniffed.mime, kind: sniffed.kind, bytes: m.bytes, width: m.width, height: m.height, sha256: m.sha, exifStripped: m.exifStripped, orientation: m.orientation};
  const twin = await duplicateOf(db, input.contactId, id, m.sha);
  if (twin) {
    const linked = {...base, r2Key: twin.r2_key, width: twin.width ?? m.width, height: twin.height ?? m.height, exifStripped: twin.exif_stripped === 1};
    await fillRow(db, id, linked);
    advisorLog('info', 'advisor_media_linked', {kind: sniffed.kind, bytes: m.bytes});
    await deriveIfNeeded(env, {kind: sniffed.kind, mime: sniffed.mime, bytes: m.bytes, orientation: m.orientation});
    return {id, status: 'linked', ...linked};
  }
  const key = mediaKey(input.contactId, id, sniffed.ext);
  await put(key);
  await fillRow(db, id, {...base, r2Key: key});
  advisorLog('info', 'advisor_media_stored', {kind: sniffed.kind, bytes: m.bytes, stripped: m.exifStripped});
  await deriveIfNeeded(env, {kind: sniffed.kind, mime: sniffed.mime, bytes: m.bytes, orientation: m.orientation});
  return {id, status: 'stored', ...base, r2Key: key};
}

/**
 * A file over BUFFER_LIMIT that is stored as received: an R2 multipart upload
 * in PART_BYTES parts, hashed as it goes, capped at 300 MB (aborted past it).
 * Deduplicated after the upload: a duplicate's new object is deleted.
 */
async function multipartToBucket(env: Env, id: string, input: IngestInput, sniffed: Sniffed, reader: ReadableStreamDefaultReader<Uint8Array>, first: Uint8Array[]): Promise<IngestResult> {
  const db = env.DB!, bucket = env.ADVISOR_MEDIA!, hash = new Sha256();
  const key = mediaKey(input.contactId, id, sniffed.ext);
  const upload = await bucket.createMultipartUpload(key, {httpMetadata: {contentType: sniffed.mime}});
  const parts: R2UploadedPart[] = [];
  let pending: Uint8Array[] = [], pendingSize = 0, size = 0;
  const flush = async (all: boolean): Promise<void> => {
    let buffer = concat(pending);
    while (buffer.length >= PART_BYTES || (all && buffer.length)) {
      const chunk = buffer.subarray(0, Math.min(PART_BYTES, buffer.length));
      parts.push(await upload.uploadPart(parts.length + 1, chunk.slice()));
      buffer = buffer.subarray(chunk.length);
    }
    pending = buffer.length ? [buffer.slice()] : []; pendingSize = buffer.length;
  };
  const take = async (chunk: Uint8Array): Promise<void> => {
    size += chunk.length;
    if (size > MAX_MEDIA_BYTES) throw Error('too-large');
    hash.update(chunk); pending.push(chunk); pendingSize += chunk.length;
    if (pendingSize >= PART_BYTES) await flush(false);
  };
  try {
    for (const chunk of first) await take(chunk);
    for (;;) {
      const {done, value} = await reader.read();
      if (done) break;
      if (value?.length) await take(value);
    }
    await flush(true);
    await upload.complete(parts);
  } catch (error) {
    await upload.abort().catch(() => {});
    await reader.cancel().catch(() => {});
    if ((error as Error)?.message === 'too-large') return rejectMedia(db, id, 'too-large', size);
    throw error;
  }
  const sha = hash.digest();
  const twin = await duplicateOf(db, input.contactId, id, sha);
  if (twin) await bucket.delete(key);
  return store(env, id, input, sniffed, {bytes: size, width: null, height: null, sha, exifStripped: false, orientation: null}, async () => {});
}

// ---- the consumer's step: download every placeholder of an inbound message --------

export interface PendingMediaRow {id: string; contact_id: string; message_id: string | null; boat_id: string | null; mime: string; provider_ref: string}
export type FetchByRef = (ref: string, channel: string, env: Env) => Promise<Response>;
export interface InboundMediaOutcome {stored: number; linked: number; rejected: number; failed: number; retry: boolean; error: string | null}

/**
 * Ingest every placeholder media row of one inbound message (provider_ref set,
 * r2_key '' and not already rejected) before the handler runs (01 § request
 * flow step 5). A download failure asks for a retry while `attempt` is within
 * `retries` extra attempts (rows already stored stay stored, so the retry only
 * fetches what failed); after that the failed rows are rejected ('fetch-failed')
 * and the handler runs without them.
 */
export async function ingestInboundMedia(env: Env, message: {id: string; channel: string}, fetchByRef: FetchByRef, opts: {attempt: number; retries: number; now: number}): Promise<InboundMediaOutcome> {
  const out: InboundMediaOutcome = {stored: 0, linked: 0, rejected: 0, failed: 0, retry: false, error: null};
  if (!env.ADVISOR_MEDIA) {
    // A deployment without ENABLE_ADVISOR has no bucket: leave the placeholders, never retry for it.
    advisorLog('warn', 'advisor_media_no_bucket', {count: 1});
    return {...out, error: 'media-unavailable'};
  }
  const rows = (await env.DB!.prepare("SELECT id,contact_id,message_id,boat_id,mime,provider_ref FROM advisor_media WHERE message_id=? AND provider_ref IS NOT NULL AND r2_key='' AND publish_state<>'rejected' ORDER BY created_at,id")
    .bind(message.id).all<PendingMediaRow>()).results;
  const failed: PendingMediaRow[] = [];
  for (const row of rows) {
    try {
      const result = await ingestMedia(env, {mediaId: row.id, contactId: row.contact_id, messageId: row.message_id, boatId: row.boat_id, providerRef: row.provider_ref,
        fetchBytes: () => fetchByRef(row.provider_ref, message.channel, env), claimedMime: row.mime, name: null}, opts.now);
      out[result.status === 'rejected' ? 'rejected' : result.status]++;
    } catch (error) {
      if (!(error instanceof MediaFetchError)) throw error;
      failed.push(row);
    }
  }
  if (!failed.length) return out;
  out.failed = failed.length;
  advisorLog('warn', 'advisor_media_fetch_failed', {count: failed.length, attempt: opts.attempt});
  if (opts.attempt <= opts.retries) { out.retry = true; return out; }
  for (const row of failed) await rejectMedia(env.DB!, row.id, 'fetch-failed');
  out.rejected += failed.length; out.error = 'fetch-failed';
  return out;
}

// ---- upload links (03 § Uploads for compressed channels) ------------------------

export const UPLOAD_TOKEN_TTL_MS = 24 * 3600000;
const encoder = new TextEncoder(), decoder = new TextDecoder();
const b64url = (bytes: Uint8Array): string => { let s = ''; for (const b of bytes) s += String.fromCharCode(b); return btoa(s).replaceAll('+', '-').replaceAll('/', '_').replace(/=+$/, ''); };
function fromB64url(text: string): Uint8Array | null {
  if (!/^[\w-]{1,400}$/.test(text) || text.length % 4 === 1) return null;
  try { return Uint8Array.from(atob(text.replaceAll('-', '+').replaceAll('_', '/') + '='.repeat((4 - text.length % 4) % 4)), c => c.charCodeAt(0)); } catch { return null; }
}

/**
 * A 24-hour upload link token for a contact: base64url("<contact_id>|<expiry
 * epoch seconds>|<hex HMAC-SHA256(uploadKey, contact_id|expiry)>"). Stateless:
 * verifyUploadToken recomputes the HMAC.
 */
export async function mintUploadToken(keys: {uploadKey: CryptoKey}, contactId: string, now: number | Date = Date.now()): Promise<string> {
  if (!ID.test(contactId)) throw Error('invalid contact id');
  const expiry = Math.floor((new Date(now).getTime() + UPLOAD_TOKEN_TTL_MS) / 1000), signed = `${contactId}|${expiry}`;
  const mac = hex(await crypto.subtle.sign('HMAC', keys.uploadKey, encoder.encode(signed)));
  return b64url(encoder.encode(`${signed}|${mac}`));
}

/** The contact id a token was minted for, or null when it is malformed, tampered with or expired. */
export async function verifyUploadToken(keys: {uploadKey: CryptoKey}, token: string, now: number | Date = Date.now()): Promise<string | null> {
  const raw = typeof token === 'string' ? fromB64url(token) : null;
  if (!raw) return null;
  const parts = decoder.decode(raw).split('|');
  if (parts.length !== 3) return null;
  const [contactId, expiry, mac] = parts as [string, string, string];
  if (!ID.test(contactId) || !/^\d{1,12}$/.test(expiry) || !/^[0-9a-f]{64}$/.test(mac)) return null;
  const macBytes = Uint8Array.from(mac.match(/../g)!, h => parseInt(h, 16));
  if (!await crypto.subtle.verify('HMAC', keys.uploadKey, macBytes, encoder.encode(`${contactId}|${expiry}`))) return null;
  if (Number(expiry) * 1000 <= new Date(now).getTime()) return null;
  return contactId;
}

// ---- TA-M1: the advisor-media runner job (09 § Derived images and graphics) ----------
//
//   media becomes pending (an image over 4.5 MB, a HEIC or a sideways JPEG
//   stored, a photo queued or approved; or a graphic requested) -> requestMediaJob dispatches
//   .github/workflows/advisor-media.yml (at most once a minute; the cron again
//   every tick while anything is pending, at most once per 15 minutes) -> the job
//   asks GET /api/advisor/jobs/media for mediaJobWork, writes
//   advisor/derived/<id>/{public,thumb,story}.jpg (or a graphic's out_key) with
//   Pillow, and POSTs /api/advisor/jobs/media-done -> mediaJobDone stamps
//   derived_at (and derived_error when it gave up), or the graphic's state.
//
// Videos (00 principle 7): every stored video is stripped by the same job
// (ffmpeg stream copy without container metadata or location atoms) to
// advisor/derived/<id>/video.mp4 before it can be approved, posted or served.
//
// The Worker never decodes an image: everything here is bookkeeping.

/** The derived files of one media item (02 § R2). */
export const derivedKeys = (mediaId: string): {public: string; thumb: string; story: string} =>
  ({public: derivedKey(mediaId), thumb: `advisor/derived/${mediaId}/thumb.jpg`, story: `advisor/derived/${mediaId}/story.jpg`});
/** A video's copy with its container metadata removed (no location atoms): the only video file /media serves. */
export const derivedVideoKey = (mediaId: string): string => `advisor/derived/${mediaId}/video.mp4`;
export const MEDIA_JOB_WORKFLOW = 'advisor-media.yml';
/** job_state key holding the time of the last dispatch (ISO), the throttle's claim. */
export const MEDIA_JOB_KEY = 'advisor.media.dispatched_at';
export const DISPATCH_EVERY_MS = 60 * 1000;            // on demand: at most once a minute
// The cron re-dispatches at most once per 15 minutes; ticks are 15 minutes apart give or take
// a few seconds, so the cap is a little under that or every other tick would be skipped.
export const CRON_DISPATCH_EVERY_MS = 14.5 * 60 * 1000;
/** Images over this are not sent to a vision provider (= vision THRESHOLDS.maxImageBytes; a test checks). */
export const VISION_MAX_BYTES = 4.5 * 1024 * 1024;
export const HEIF_MIMES = ['image/heic', 'image/heif'] as const;
export const GRAPHIC_PREFIX = 'advisor.graphic.';
export const GRAPHIC_KINDS = ['daily', 'story', 'roundup'] as const;
export type GraphicKind = typeof GRAPHIC_KINDS[number];
/** A graphic later tasks ask for (TA-S4 daily and roundup, TA-S5 stories): job_state advisor.graphic.<id>. */
export interface GraphicRequest {kind: GraphicKind; media_ids?: string[]; data: Record<string, unknown>; out_key: string}
export interface GraphicState extends GraphicRequest {
  status: 'pending' | 'done' | 'failed'; requested_at: string;
  done_at?: string; keys?: {public: string; slides?: string[]}; width?: number; height?: number; error?: string;
}
const GRAPHIC_KEY = /^advisor\/posts\/[\w-]{1,64}\/[\w-]{1,64}\.jpg$/;
const MAX_GRAPHIC_DATA = 16 * 1024;
const MAX_GRAPHIC_MEDIA = 10;
export const WORK_LIMIT = {media: 25, graphics: 10, videos: 5};
const HEIF_SQL = HEIF_MIMES.map(m => `'${m}'`).join(',');

/**
 * Media the job still has to derive: stored images (not rejected) without
 * derived_at that a provider cannot take as stored (over 4.5 MB, or HEIC/HEIF),
 * that are stored sideways (a JPEG whose EXIF orientation was 2-8: only
 * public.jpg is upright), or that are headed for review or publication (queued,
 * approved, posted: thumb.jpg for the admin queue, public.jpg for pages and
 * Meta, story.jpg). Other private everyday photos are left alone.
 */
const PENDING_MEDIA = `kind='image' AND r2_key<>'' AND publish_state<>'rejected' AND derived_at IS NULL
  AND (bytes>? OR mime IN (${HEIF_SQL}) OR orientation>1 OR publish_state IN ('queued','approved','posted'))`;

/**
 * Videos the job still has to strip (00 principle 7: a video never leaks a
 * position): every stored video that is not rejected and has no derived_at,
 * private ones too, so a video is stripped before anyone reviews or approves it.
 * The job copies the streams without the container's metadata (ffmpeg
 * -map_metadata -1, no location atoms) to advisor/derived/<id>/video.mp4.
 */
const PENDING_VIDEO = `kind='video' AND r2_key<>'' AND publish_state<>'rejected' AND derived_at IS NULL`;

/** `orientation`: the EXIF value read at intake (1-8, null when not a JPEG); the job applies it, since the stored original has no EXIF. */
export interface MediaWorkItem {id: string; r2_key: string; mime: string; sha256: string; bytes: number; orientation: number | null; keys: {public: string; thumb: string; story: string}}
export interface GraphicWorkItem {id: string; kind: GraphicKind; out_key: string; data: Record<string, unknown>; media: {id: string; r2_key: string; mime: string; orientation: number | null; public_key: string}[]}
export interface VideoWorkItem {id: string; r2_key: string; mime: string; sha256: string; bytes: number; keys: {video: string}}
export interface MediaWork {media: MediaWorkItem[]; graphics: GraphicWorkItem[]; videos: VideoWorkItem[]}

const nowMs = (now: number | Date): number => new Date(now).getTime();

/** True when the job has something to do (media or graphics), for the cron. */
export async function mediaJobPending(db: D1Database): Promise<number> {
  const media = await db.prepare(`SELECT COUNT(*) AS n FROM advisor_media WHERE ${PENDING_MEDIA}`).bind(VISION_MAX_BYTES).first<{n: number}>();
  const graphics = await db.prepare("SELECT COUNT(*) AS n FROM job_state WHERE key LIKE 'advisor.graphic.%' AND json_valid(value) AND json_extract(value,'$.status')='pending'").first<{n: number}>();
  const videos = await db.prepare(`SELECT COUNT(*) AS n FROM advisor_media WHERE ${PENDING_VIDEO}`).first<{n: number}>();
  return (media?.n ?? 0) + (graphics?.n ?? 0) + (videos?.n ?? 0);
}

/** One page of work for the job, oldest first: GET /api/advisor/jobs/media. */
export async function mediaJobWork(db: D1Database, limit: {media: number; graphics: number; videos?: number} = WORK_LIMIT): Promise<MediaWork> {
  const rows = (await db.prepare(`SELECT id,r2_key,mime,sha256,bytes,orientation FROM advisor_media WHERE ${PENDING_MEDIA} ORDER BY created_at,id LIMIT ?`)
    .bind(VISION_MAX_BYTES, limit.media).all<{id: string; r2_key: string; mime: string; sha256: string; bytes: number; orientation: number | null}>()).results;
  const media = rows.map(r => ({...r, keys: derivedKeys(r.id)}));
  const states = (await db.prepare("SELECT key,value FROM job_state WHERE key LIKE 'advisor.graphic.%' AND json_valid(value) AND json_extract(value,'$.status')='pending' ORDER BY updated_at,key LIMIT ?")
    .bind(limit.graphics).all<{key: string; value: string}>()).results;
  const graphics: GraphicWorkItem[] = [];
  for (const {key, value} of states) {
    const id = key.slice(GRAPHIC_PREFIX.length), state = JSON.parse(value) as GraphicState;
    const ids = (state.media_ids ?? []).filter(m => ID.test(m)).slice(0, MAX_GRAPHIC_MEDIA);
    const found = ids.length ? (await db.prepare(`SELECT id,r2_key,mime,orientation FROM advisor_media WHERE id IN (${ids.map(() => '?').join(',')}) AND kind='image' AND r2_key<>'' AND publish_state<>'rejected'`)
      .bind(...ids).all<{id: string; r2_key: string; mime: string; orientation: number | null}>()).results : [];
    const byId = new Map(found.map(m => [m.id, m]));
    graphics.push({id, kind: state.kind, out_key: state.out_key, data: state.data ?? {},
      media: ids.flatMap(m => { const row = byId.get(m); return row ? [{...row, public_key: derivedKey(m)}] : []; })});
  }
  const videos = (await db.prepare(`SELECT id,r2_key,mime,sha256,bytes FROM advisor_media WHERE ${PENDING_VIDEO} ORDER BY created_at,id LIMIT ?`)
    .bind(limit.videos ?? WORK_LIMIT.videos).all<{id: string; r2_key: string; mime: string; sha256: string; bytes: number}>()).results
    .map(r => ({...r, keys: {video: derivedVideoKey(r.id)}}));
  return {media, graphics, videos};
}

/**
 * Why a video cannot be approved or published yet, or null when its stripped
 * copy exists (derived_at set, no derived_error). The admin card shows it.
 */
export function videoHold(row: {kind: string; derived_at: string | null; derived_error: string | null}): string | null {
  if (row.kind !== 'video') return null;
  if (row.derived_error === 'no-ffmpeg') return 'this video still carries its camera metadata: the media runner has no ffmpeg (docs/operations/runners.md), so its location data could not be removed';
  if (row.derived_error) return `this video still carries its camera metadata: removing it failed (${row.derived_error.slice(0, 80)})`;
  if (!row.derived_at) return 'this video is waiting for the media job to remove its location metadata (within 15 minutes)';
  return null;
}

export type DispatchOutcome = 'dispatched' | 'throttled' | 'no-token' | 'no-db' | `failed-${number}` | 'error';
export interface DispatchDeps {dispatch?: (env: Env, file: string) => Promise<number>; everyMs?: number}

/**
 * Dispatch advisor-media.yml unless it was dispatched within `everyMs`
 * (default one minute): the claim is an UPSERT-with-WHERE on job_state
 * MEDIA_JOB_KEY, so concurrent callers dispatch once. A failed dispatch keeps
 * the claim (no hammering GitHub); the cron tries again. Never throws.
 */
export async function requestMediaJob(env: Env, now: number | Date = Date.now(), deps: DispatchDeps = {}): Promise<DispatchOutcome> {
  if (!env.GITHUB_TOKEN) return 'no-token';
  if (!env.DB) return 'no-db';
  try {
    const at = nowMs(now), cutoff = new Date(at - (deps.everyMs ?? DISPATCH_EVERY_MS)).toISOString(), stamp = new Date(at).toISOString();
    const claim = await env.DB.prepare('INSERT INTO job_state(key,value,updated_at) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at WHERE job_state.value<=?')
      .bind(MEDIA_JOB_KEY, stamp, stamp, cutoff).run();
    if (!claim.meta.changes) return 'throttled';
    const status = await (deps.dispatch ?? dispatchWorkflow)(env, MEDIA_JOB_WORKFLOW);
    if (status !== 204) { advisorLog('warn', 'advisor_media_dispatch_failed', {status}); return `failed-${status}`; }
    advisorLog('info', 'advisor_media_dispatched', {count: 1});
    return 'dispatched';
  } catch (error) {
    advisorLog('warn', 'advisor_media_dispatch_failed', {reason: String((error as Error)?.message).slice(0, 200)});
    return 'error';
  }
}

/** True when this media row needs public.jpg before a vision provider can read it (over 4.5 MB, or HEIC/HEIF). */
export const needsDerivedForVision = (row: {kind: string; mime: string; bytes: number}): boolean =>
  row.kind === 'image' && (row.bytes > VISION_MAX_BYTES || (HEIF_MIMES as readonly string[]).includes(row.mime));

/**
 * The media of one inbound message (media_json ids) still waiting for the job's
 * public.jpg so vision can read it: stored images over 4.5 MB or HEIC/HEIF
 * without derived_at. The consumer re-queues the message while this is > 0.
 */
export async function awaitingDerived(db: D1Database, mediaJson: string | null): Promise<number> {
  let ids: string[] = [];
  try { const parsed = mediaJson ? JSON.parse(mediaJson) : []; if (Array.isArray(parsed)) ids = parsed.filter((m): m is string => typeof m === 'string' && ID.test(m)).slice(0, 10); } catch { return 0; }
  if (!ids.length) return 0;
  const row = await db.prepare(`SELECT COUNT(*) AS n FROM advisor_media WHERE id IN (${ids.map(() => '?').join(',')}) AND kind='image' AND r2_key<>'' AND publish_state<>'rejected'
    AND derived_at IS NULL AND (bytes>? OR mime IN (${HEIF_SQL}))`).bind(...ids, VISION_MAX_BYTES).first<{n: number}>();
  return row?.n ?? 0;
}

/**
 * Ask the job for a graphic (later tasks: the daily post, Stories, the weekly
 * roundup). Writes job_state advisor.graphic.<id> as pending (a rerun with the
 * same id renders again) and dispatches the job. `out_key` must be
 * advisor/posts/<post_id>/<name>.jpg; `data` is the template's input (at most
 * 16 KB of JSON); `media_ids` (at most 10) are photos the layout uses.
 */
export async function requestGraphic(env: Env, id: string, request: GraphicRequest, now: number | Date = Date.now(), deps: DispatchDeps = {}): Promise<DispatchOutcome> {
  if (!env.DB) throw Error('storage unavailable');
  if (!ID.test(id)) throw Error('invalid graphic id');
  if (!(GRAPHIC_KINDS as readonly string[]).includes(request.kind)) throw Error('invalid graphic kind');
  if (!GRAPHIC_KEY.test(request.out_key)) throw Error('invalid graphic out_key');
  const mediaIds = request.media_ids ?? [];
  if (!Array.isArray(mediaIds) || mediaIds.length > MAX_GRAPHIC_MEDIA || !mediaIds.every(m => typeof m === 'string' && ID.test(m))) throw Error('invalid graphic media_ids');
  const data = JSON.stringify(request.data ?? {});
  if (!request.data || typeof request.data !== 'object' || Array.isArray(request.data) || data.length > MAX_GRAPHIC_DATA) throw Error('invalid graphic data');
  const at = new Date(nowMs(now)).toISOString();
  const state: GraphicState = {kind: request.kind, ...(mediaIds.length ? {media_ids: mediaIds} : {}), data: request.data, out_key: request.out_key, status: 'pending', requested_at: at};
  await env.DB.prepare('INSERT INTO job_state(key,value,updated_at) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at')
    .bind(GRAPHIC_PREFIX + id, JSON.stringify(state), at).run();
  return requestMediaJob(env, now, deps);
}

/** A graphic's state (pending, done with its keys, or failed), or null. */
export async function graphicState(db: D1Database, id: string): Promise<GraphicState | null> {
  if (!ID.test(id)) return null;
  const row = await db.prepare('SELECT value FROM job_state WHERE key=?').bind(GRAPHIC_PREFIX + id).first<{value: string}>();
  try { return row ? JSON.parse(row.value) as GraphicState : null; } catch { return null; }
}

export interface MediaDoneInput {media_id?: unknown; graphic_id?: unknown; keys?: unknown; width?: unknown; height?: unknown; source_width?: unknown; source_height?: unknown; error?: unknown}
export type MediaDoneResult = {ok: true; kind: 'media' | 'graphic'; status: 'done' | 'failed'} | {ok: false; error: 'not-found' | 'invalid'};

const dim = (v: unknown): number | null => typeof v === 'number' && Number.isInteger(v) && v > 0 && v <= 20000 ? v : null;
const ERROR_TEXT = /^[\w .:,;()/'-]{1,200}$/;

/**
 * POST /api/advisor/jobs/media-done: the job finished one item. For a video,
 * `keys` must be exactly {video: advisor/derived/<id>/video.mp4} (width and
 * height optional); an `error` ('no-ffmpeg' when the runner lacks it) gives the
 * video up, which holds its approval. For an image,
 * `keys` must be exactly its derivedKeys (story optional) and width/height the
 * public.jpg's; derived_at is stamped, and the original's width/height filled
 * from source_width/source_height when intake could not read them (HEIC). With
 * `error` (a short reason) the item is marked given up: derived_at and
 * derived_error are set, so it is not pending any more and a waiting message
 * falls back to the upload link. For a graphic, keys.public must be its out_key
 * (roundup slides beside it); the job_state value becomes done or failed.
 */
export async function mediaJobDone(env: Env, input: MediaDoneInput, now: number | Date = Date.now()): Promise<MediaDoneResult> {
  const db = env.DB!, at = new Date(nowMs(now)).toISOString();
  const error = input.error === undefined || input.error === null ? null : typeof input.error === 'string' && ERROR_TEXT.test(input.error) ? input.error : undefined;
  if (error === undefined) return {ok: false, error: 'invalid'};
  const keys = input.keys && typeof input.keys === 'object' && !Array.isArray(input.keys) ? input.keys as Record<string, unknown> : null;
  const width = dim(input.width), height = dim(input.height);
  if (typeof input.media_id === 'string' && input.graphic_id === undefined) {
    const id = input.media_id;
    if (!ID.test(id)) return {ok: false, error: 'invalid'};
    const found = await db.prepare("SELECT kind FROM advisor_media WHERE id=? AND kind IN ('image','video')").bind(id).first<{kind: string}>();
    if (!found) return {ok: false, error: 'not-found'};
    const video = found.kind === 'video';
    if (!error) {
      if (video) {
        // The stripped copy: exactly its key; its size when ffprobe read one.
        if (!keys || keys.video !== derivedVideoKey(id) || Object.keys(keys).length !== 1
          || (input.width !== undefined && width === null) || (input.height !== undefined && height === null)) return {ok: false, error: 'invalid'};
      } else {
        const expected = derivedKeys(id);
        if (!keys || keys.public !== expected.public || keys.thumb !== expected.thumb || (keys.story !== undefined && keys.story !== expected.story)
          || Object.keys(keys).some(k => !['public', 'thumb', 'story'].includes(k)) || width === null || height === null) return {ok: false, error: 'invalid'};
      }
    }
    const r = video
      ? await db.prepare(`UPDATE advisor_media SET derived_at=?,derived_error=?,width=COALESCE(width,?),height=COALESCE(height,?) WHERE id=? AND kind='video'`)
        .bind(at, error, error ? null : width, error ? null : height, id).run()
      : await db.prepare(`UPDATE advisor_media SET derived_at=?,derived_error=?,width=COALESCE(width,?),height=COALESCE(height,?) WHERE id=? AND kind='image'`)
        .bind(at, error, error ? null : dim(input.source_width), error ? null : dim(input.source_height), id).run();
    if (!r.meta.changes) return {ok: false, error: 'not-found'};
    advisorLog(error ? 'warn' : 'info', error ? (video ? 'advisor_video_strip_failed' : 'advisor_media_derive_failed') : (video ? 'advisor_video_stripped' : 'advisor_media_derived'), {count: 1, ...(error ? {reason: error} : {})});
    return {ok: true, kind: 'media', status: error ? 'failed' : 'done'};
  }
  if (typeof input.graphic_id === 'string' && input.media_id === undefined) {
    const id = input.graphic_id;
    if (!ID.test(id)) return {ok: false, error: 'invalid'};
    const state = await graphicState(db, id);
    if (!state) return {ok: false, error: 'not-found'};
    let next: GraphicState;
    if (error) next = {...state, status: 'failed', done_at: at, error};
    else {
      const stem = state.out_key.slice(0, -'.jpg'.length);
      const slides = keys?.slides;
      const slidesOk = slides === undefined || (Array.isArray(slides) && slides.length <= MAX_GRAPHIC_MEDIA && slides.every(s => typeof s === 'string' && s.startsWith(stem + '-') && GRAPHIC_KEY.test(s)));
      if (!keys || keys.public !== state.out_key || !slidesOk || Object.keys(keys).some(k => !['public', 'slides'].includes(k)) || width === null || height === null) return {ok: false, error: 'invalid'};
      next = {...state, status: 'done', done_at: at, keys: {public: state.out_key, ...(Array.isArray(slides) && slides.length ? {slides: slides as string[]} : {})}, width, height};
      delete next.error;
    }
    await db.prepare('UPDATE job_state SET value=?,updated_at=? WHERE key=?').bind(JSON.stringify(next), at, GRAPHIC_PREFIX + id).run();
    advisorLog(error ? 'warn' : 'info', error ? 'advisor_graphic_failed' : 'advisor_graphic_rendered', {kind: state.kind, ...(error ? {reason: error} : {})});
    return {ok: true, kind: 'graphic', status: error ? 'failed' : 'done'};
  }
  return {ok: false, error: 'invalid'};
}
