// An R2 stand-in for Worker tests (SC2184-13). Published feeds are served only
// from the FEEDS bucket, so a test that stubs globalThis.fetch for a feed's
// logical URL (RAW + key) passes this bucket as FEEDS instead: each get() of a
// feed key reads the test's current fetch stub at RAW + key, so the stub's
// assertions and read counters keep working unchanged.
//
// get() returns null (as R2 does for an absent object) for the release-layout
// `.r2-*` keys, so the resolver takes the legacy layout without bumping a read
// counter; for keys outside the published-feed prefixes; and when the stub
// answers with a non-ok status. Range and conditional options are ignored: the
// whole object is returned.
import {createHash} from 'node:crypto';
import {RAW, feedKey} from '../../server/feeds.ts';

function object(key, bytes, withBody) {
  const etag = createHash('sha256').update(bytes).digest('hex').slice(0, 16);
  const text = () => new TextDecoder().decode(bytes);
  const out = {key, size: bytes.byteLength, etag, httpEtag: `"${etag}"`, uploaded: new Date(0), customMetadata: {}, httpMetadata: {},
    writeHttpMetadata() {}};
  if (!withBody) return out;
  return Object.assign(out, {
    body: new Response(bytes).body,
    bodyUsed: false,
    json: async () => JSON.parse(text()),
    text: async () => text(),
    arrayBuffer: async () => bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength),
  });
}

async function read(key) {
  if (typeof key !== 'string' || feedKey(RAW + key) !== key) return null;
  const response = await globalThis.fetch(RAW + key);
  if (!response?.ok) return null;
  return new Uint8Array(await response.arrayBuffer());
}

/** A FEEDS binding that answers feed keys from the current globalThis.fetch stub. */
export function feedBucket() {
  return {
    async get(key) { const bytes = await read(key); return bytes ? object(key, bytes, true) : null; },
    async head(key) { const bytes = await read(key); return bytes ? object(key, bytes, false) : null; },
  };
}
