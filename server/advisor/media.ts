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
import {advisorLog} from './log.ts';
import {hex, randomId} from './ids.ts';
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

export interface Stripped {bytes: Uint8Array; stripped: boolean; width: number | null; height: number | null}

const concat = (parts: Uint8Array[]): Uint8Array => {
  const out = new Uint8Array(parts.reduce((n, p) => n + p.length, 0));
  let at = 0; for (const p of parts) { out.set(p, at); at += p.length; }
  return out;
};
const ICC = 'ICC_PROFILE\0';
const isSof = (m: number): boolean => m >= 0xc0 && m <= 0xcf && m !== 0xc4 && m !== 0xc8 && m !== 0xcc;

/**
 * A JPEG without metadata, by a marker walk from SOI (no decoding). Kept: SOI,
 * APP0 (JFIF/JFXX), APP2 segments whose payload starts "ICC_PROFILE\0" (so
 * Display P3 photos keep their colours), DQT, DHT, DAC, SOF*, DRI, SOS with its
 * entropy-coded data, any later tables and scans of a progressive JPEG, and
 * EOI. Dropped: every other APPn (EXIF, GPS, XMP, MPF, maker notes) and COM,
 * and anything after EOI (an iPhone's MPF secondary images sit there).
 * Width and height come from the SOF header. A file that is not a JPEG, or is
 * truncated anywhere, comes back unchanged with stripped false; it never throws.
 */
export function stripJpegMetadata(bytes: Uint8Array): Stripped {
  const unchanged: Stripped = {bytes, stripped: false, width: null, height: null};
  const b = bytes, n = b.length;
  if (n < 4 || b[0] !== 0xff || b[1] !== 0xd8) return unchanged;
  const parts: Uint8Array[] = [b.subarray(0, 2)];
  let i = 2, width: number | null = null, height: number | null = null;
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
    if ((marker >= 0xe1 && marker <= 0xef) || marker === 0xfe) continue;              // other APPn, COM
    parts.push(segment);                                                              // DQT, DHT, DAC, DRI, DNL, ...
  }
  if (width === null) return unchanged;           // no frame header: not an image we can vouch for
  return {bytes: concat(parts), stripped: true, width, height};
}

const PNG_DROP = new Set(['eXIf', 'tEXt', 'iTXt', 'zTXt', 'tIME']);

/**
 * A PNG without its text, EXIF and time chunks (eXIf, tEXt, iTXt, zTXt, tIME).
 * Every other chunk is copied byte for byte with its CRC; nothing after IEND is
 * kept. Width and height come from IHDR. Not a PNG, or truncated: unchanged
 * with stripped false; it never throws.
 */
export function stripPngMetadata(bytes: Uint8Array): Stripped {
  const unchanged: Stripped = {bytes, stripped: false, width: null, height: null};
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
  return {bytes: concat(parts), stripped: true, width, height};
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
  return {id: mediaId, status: 'rejected', reason, mime: null, bytes, width: null, height: null, r2Key: '', sha256: '', exifStripped: false};
}

interface Fill {mime: string; kind: MediaKind; bytes: number; width: number | null; height: number | null; r2Key: string; sha256: string; exifStripped: boolean}
async function fillRow(db: D1Database, mediaId: string, f: Fill): Promise<void> {
  await db.prepare('UPDATE advisor_media SET mime=?,kind=?,bytes=?,width=COALESCE(?,width),height=COALESCE(?,height),r2_key=?,sha256=?,exif_stripped=? WHERE id=?')
    .bind(f.mime, f.kind, f.bytes, f.width, f.height, f.r2Key, f.sha256, f.exifStripped ? 1 : 0, mediaId).run();
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
    let stored = all, width: number | null = null, height: number | null = null, exifStripped = false;
    if (strippable) {
      const result = sniffed.mime === 'image/jpeg' ? stripJpegMetadata(all) : stripPngMetadata(all);
      if (!result.stripped) return rejectMedia(db, id, 'strip-failed', all.length);
      ({width, height} = result); stored = result.bytes; exifStripped = true;
    }
    const sha = hex(await crypto.subtle.digest('SHA-256', stored));
    return await store(env, id, input, sniffed, {bytes: stored.length, width, height, sha, exifStripped},
      key => bucket.put(key, stored, {httpMetadata: {contentType: sniffed.mime}}).then(() => {}));
  } catch (error) {
    await reader.cancel().catch(() => {});
    if (fetchFailure(error)) throw new MediaFetchError('fetch failed: stream');
    throw error;
  }
}

interface Measured {bytes: number; width: number | null; height: number | null; sha: string; exifStripped: boolean}

/** Link to the contact's identical object, or put a new one; then fill the row. */
async function store(env: Env, id: string, input: IngestInput, sniffed: Sniffed, m: Measured, put: (key: string) => Promise<void>): Promise<IngestResult> {
  const db = env.DB!;
  const base = {mime: sniffed.mime, kind: sniffed.kind, bytes: m.bytes, width: m.width, height: m.height, sha256: m.sha, exifStripped: m.exifStripped};
  const twin = await duplicateOf(db, input.contactId, id, m.sha);
  if (twin) {
    const linked = {...base, r2Key: twin.r2_key, width: twin.width ?? m.width, height: twin.height ?? m.height, exifStripped: twin.exif_stripped === 1};
    await fillRow(db, id, linked);
    advisorLog('info', 'advisor_media_linked', {kind: sniffed.kind, bytes: m.bytes});
    return {id, status: 'linked', ...linked};
  }
  const key = mediaKey(input.contactId, id, sniffed.ext);
  await put(key);
  await fillRow(db, id, {...base, r2Key: key});
  advisorLog('info', 'advisor_media_stored', {kind: sniffed.kind, bytes: m.bytes, stripped: m.exifStripped});
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
  return store(env, id, input, sniffed, {bytes: size, width: null, height: null, sha, exifStripped: false}, async () => {});
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
