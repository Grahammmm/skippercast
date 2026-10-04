// In-memory R2 bucket for advisor media tests: the subset of R2Bucket the
// Worker uses (put/get/head/delete/list and multipart uploads), with call
// counters. Not a test file itself (no test_ prefix).

const bytesOf = async value => {
  if (value == null) return new Uint8Array(0);
  if (value instanceof Uint8Array) return new Uint8Array(value);
  if (value instanceof ArrayBuffer) return new Uint8Array(value.slice(0));
  if (typeof value === 'string') return new TextEncoder().encode(value);
  if (value instanceof ReadableStream) return new Uint8Array(await new Response(value).arrayBuffer());
  if (typeof value.arrayBuffer === 'function') return new Uint8Array(await value.arrayBuffer());
  throw Error('unsupported R2 body');
};

function objectBody(key, entry) {
  return {
    key, size: entry.bytes.length, httpMetadata: {...entry.httpMetadata}, customMetadata: {...entry.customMetadata},
    get body() { return new Response(entry.bytes.slice()).body; },
    arrayBuffer: async () => entry.bytes.slice().buffer,
    text: async () => new TextDecoder().decode(entry.bytes),
  };
}

/** {objects: Map<key, {bytes, httpMetadata, customMetadata}>, calls: {put, get, delete, multipart}} plus the R2 methods. */
export function memoryBucket(initial = {}) {
  const objects = new Map(Object.entries(initial).map(([k, v]) => [k, {bytes: typeof v === 'string' ? new TextEncoder().encode(v) : new Uint8Array(v), httpMetadata: {}}]));
  const calls = {put: [], get: [], delete: [], multipart: []};
  return {
    objects, calls,
    async put(key, value, options = {}) {
      const bytes = await bytesOf(value);
      calls.put.push(key);
      objects.set(key, {bytes, httpMetadata: {...options.httpMetadata}, customMetadata: {...options.customMetadata}});
      return {key, size: bytes.length};
    },
    async get(key, options = {}) {
      calls.get.push(key);
      const e = objects.get(key);
      if (!e) return null;
      // R2's {range: {offset, length}}: the body is the slice; size stays the whole object's.
      const r = options.range;
      if (!r) return objectBody(key, e);
      const body = objectBody(key, {...e, bytes: e.bytes.slice(r.offset, r.offset + r.length)});
      return {...body, size: e.bytes.length, range: {offset: r.offset, length: r.length}, get body() { return new Response(e.bytes.slice(r.offset, r.offset + r.length)).body; }};
    },
    async head(key) { const e = objects.get(key); return e ? {key, size: e.bytes.length, httpMetadata: {...e.httpMetadata}, customMetadata: {...e.customMetadata}} : null; },
    async delete(keys) { for (const key of [].concat(keys)) { calls.delete.push(key); objects.delete(key); } },
    async list({prefix = ''} = {}) { return {objects: [...objects.keys()].filter(k => k.startsWith(prefix)).sort().map(key => ({key})), truncated: false}; },
    async createMultipartUpload(key, options = {}) {
      const parts = new Map(), record = {key, parts: [], completed: false, aborted: false};
      calls.multipart.push(record);
      return {
        key, uploadId: `upload-${calls.multipart.length}`,
        async uploadPart(number, value) { const bytes = await bytesOf(value); parts.set(number, bytes); record.parts.push(bytes.length); return {partNumber: number, etag: `etag-${number}`}; },
        async complete(uploaded) {
          const ordered = [...uploaded].sort((a, b) => a.partNumber - b.partNumber).map(p => parts.get(p.partNumber));
          const total = ordered.reduce((n, b) => n + b.length, 0), bytes = new Uint8Array(total);
          let at = 0; for (const b of ordered) { bytes.set(b, at); at += b.length; }
          objects.set(key, {bytes, httpMetadata: {...options.httpMetadata}});
          record.completed = true;
          return {key, size: total};
        },
        async abort() { record.aborted = true; },
      };
    },
  };
}
