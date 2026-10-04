// The first file of a multipart/form-data body as a stream (TA-C4 upload link).
// request.formData() buffers the whole body, and an upload may be 300 MB while
// a Worker has 128 MB, so the upload route reads the part this way instead:
// the part headers (capped at 8 KB) are parsed, then the part's content is
// streamed until the closing boundary. Only the first part that carries a
// filename is read; anything after it is discarded.
import {ClientError} from '../errors.ts';

export interface MultipartFile {name: string | null; type: string | null; body: ReadableStream<Uint8Array>}

const encoder = new TextEncoder(), decoder = new TextDecoder();
const MAX_HEADERS = 8192;

/** The boundary from a multipart/form-data Content-Type, or null. */
export function boundaryOf(contentType: string | null): string | null {
  if (!contentType || !/^multipart\/form-data\s*;/i.test(contentType)) return null;
  const m = contentType.match(/;\s*boundary=(?:"([^"]{1,70})"|([^\s;"]{1,70}))/i);
  return m ? (m[1] ?? m[2] ?? null) : null;
}

function indexOf(haystack: Uint8Array, needle: Uint8Array, from = 0): number {
  outer: for (let i = from; i <= haystack.length - needle.length; i++) {
    for (let j = 0; j < needle.length; j++) if (haystack[i + j] !== needle[j]) continue outer;
    return i;
  }
  return -1;
}
const join = (a: Uint8Array, b: Uint8Array): Uint8Array => { const out = new Uint8Array(a.length + b.length); out.set(a); out.set(b, a.length); return out; };

/** Parse a part's header block into the field filename and content type. */
function partHeaders(block: string): {filename: string | null; type: string | null; isFile: boolean} {
  let filename: string | null = null, type: string | null = null, isFile = false;
  for (const line of block.split('\r\n')) {
    const [rawName, ...rest] = line.split(':');
    const name = rawName?.trim().toLowerCase(), value = rest.join(':').trim();
    if (name === 'content-disposition') {
      const f = value.match(/;\s*filename="([^"]*)"/i) ?? value.match(/;\s*filename=([^;\s]+)/i);
      if (f) { isFile = true; filename = f[1]!.replace(/[\u0000-\u001f\u007f/\\]/g, '').slice(0, 200) || null; }
    } else if (name === 'content-type') type = value.slice(0, 100) || null;
  }
  return {filename, type, isFile};
}

/**
 * The first file part of `request`'s multipart body. Throws ClientError when
 * the body is not multipart or carries no file part within its first parts.
 */
export async function firstFile(request: Request): Promise<MultipartFile> {
  const boundary = boundaryOf(request.headers.get('content-type'));
  if (!boundary || !request.body) throw new ClientError('expected a multipart file upload');
  const reader = request.body.getReader();
  const opening = encoder.encode(`--${boundary}`), delimiter = encoder.encode(`\r\n--${boundary}`), blank = encoder.encode('\r\n\r\n');
  let buffer: Uint8Array = new Uint8Array(0), ended = false;
  const more = async (): Promise<boolean> => {
    if (ended) return false;
    const {done, value} = await reader.read();
    if (done) { ended = true; return false; }
    if (value?.length) buffer = join(buffer, value);
    return true;
  };
  const fail = async (message: string): Promise<never> => { await reader.cancel().catch(() => {}); throw new ClientError(message); };

  // Preamble, then the first boundary line.
  while (indexOf(buffer, opening) < 0) { if (buffer.length > MAX_HEADERS || !await more()) return fail('expected a multipart file upload'); }
  buffer = buffer.subarray(indexOf(buffer, opening) + opening.length);
  for (let parts = 0; parts < 8; parts++) {
    while (buffer.length < 2) if (!await more()) return fail('no file in the upload');
    if (buffer[0] === 0x2d && buffer[1] === 0x2d) return fail('no file in the upload');     // closing "--"
    let end: number;
    while ((end = indexOf(buffer, blank)) < 0) { if (buffer.length > MAX_HEADERS || !await more()) return fail('invalid multipart headers'); }
    if (end > MAX_HEADERS) return fail('invalid multipart headers');
    const headers = partHeaders(decoder.decode(buffer.subarray(0, end)).replace(/^\r\n/, ''));
    buffer = buffer.subarray(end + blank.length);
    if (headers.isFile) {
      let start = buffer;
      const body = new ReadableStream<Uint8Array>({
        async pull(controller) {
          for (;;) {
            const at = indexOf(start, delimiter);
            if (at >= 0) {
              if (at) controller.enqueue(start.slice(0, at));
              controller.close(); await reader.cancel().catch(() => {}); return;
            }
            // Everything but a possible partial delimiter at the end is content.
            const safe = start.length - (delimiter.length - 1);
            if (safe > 0) { controller.enqueue(start.slice(0, safe)); start = start.subarray(safe); return; }
            const {done, value} = await reader.read();
            if (done) { controller.error(new ClientError('upload ended early')); return; }
            if (value?.length) start = join(start, value);
          }
        },
        cancel() { return reader.cancel(); },
      });
      return {name: headers.filename, type: headers.type, body};
    }
    // A plain field: skip to the next boundary.
    let next: number;
    while ((next = indexOf(buffer, delimiter)) < 0) { if (buffer.length > MAX_HEADERS * 8 || !await more()) return fail('no file in the upload'); }
    buffer = buffer.subarray(next + delimiter.length);
  }
  return fail('no file in the upload');
}
