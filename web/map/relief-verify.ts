// E2E-17: authenticate the bytes returned by PMTiles, not the directory or
// the compressed bytes on disk. The deployed regional pointer is the anchor.
const blockSize = 64;
const sha256 = /^[0-9a-f]{64}$/;
const record = (value: unknown): value is Record<string, unknown> =>
  !!value && typeof value === 'object' && !Array.isArray(value);

async function hash(bytes: ArrayBuffer): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', bytes);
  return Array.from(new Uint8Array(digest), b => b.toString(16).padStart(2, '0')).join('');
}

export function reliefVerifier(archive: {object_key: string; digest_root_sha256: string},
  page: string, fetchFn: typeof fetch, signal: AbortSignal) {
  const expectedRoot = archive.digest_root_sha256;
  // Same immutable archive namespace as the uploader, with a separate version
  // for the index in case an archive is re-indexed without changing its bytes.
  const index = new URL(`feeds/${archive.object_key.slice(0, -'.pmtiles'.length)}.digests/${expectedRoot}/`, page);
  let root: Promise<Record<string, unknown>> | undefined;
  const chunks = new Map<string, Promise<Map<string, string>>>();

  async function read(path: string, expected: string): Promise<unknown> {
    signal.throwIfAborted();
    const response = await fetchFn(new URL(path, index), {signal, redirect: 'error'});
    if (!response.ok) throw new Error(`Relief digest ${path} unavailable (HTTP ${response.status})`);
    const bytes = await response.arrayBuffer();
    if (await hash(bytes) !== expected) throw new Error(`Relief digest ${path} hash mismatch`);
    signal.throwIfAborted();
    return JSON.parse(new TextDecoder('utf-8', {fatal: true}).decode(bytes));
  }

  async function loadRoot() {
    const doc = await read('root.json', expectedRoot);
    if (!record(doc) || !record(doc.chunks)) throw new Error('Invalid relief digest root');
    return doc.chunks;
  }

  async function loadChunk(path: string, expected: string, blockX: number, blockY: number) {
    const rows = await read(path, expected);
    if (!Array.isArray(rows)) throw new Error('Invalid relief digest chunk');
    const entries = new Map<string, string>();
    for (const row of rows) {
      if (!Array.isArray(row) || row.length !== 3) throw new Error('Invalid relief digest row');
      const [x, y, digest] = row, key = `${x}/${y}`;
      if (!Number.isInteger(x) || Math.floor(x / blockSize) !== blockX || !Number.isInteger(y) ||
          Math.floor(y / blockSize) !== blockY || typeof digest !== 'string' || !sha256.test(digest) || entries.has(key)) {
        throw new Error('Invalid relief digest row');
      }
      entries.set(key, digest);
    }
    return entries;
  }

  return async (z: number, x: number, y: number, data: ArrayBuffer | undefined) => {
    const blockX = Math.floor(x / blockSize), blockY = Math.floor(y / blockSize);
    const path = `${z}/${blockX}_${blockY}.json`;
    const doc = await (root ??= loadRoot());
    let digest: string | undefined;
    if (Object.hasOwn(doc, path)) {
      const expected = doc[path];
      if (typeof expected !== 'string' || !sha256.test(expected)) throw new Error('Invalid relief chunk digest');
      let chunk = chunks.get(path);
      if (!chunk) {
        chunk = loadChunk(path, expected, blockX, blockY);
        chunks.set(path, chunk);
      }
      digest = (await chunk).get(`${x}/${y}`);
    }
    // Sparse holes are normal only if the authenticated index agrees. A
    // directory change must not turn an indexed tile into an apparent hole.
    if (data === undefined && digest === undefined) return;
    if (digest === undefined) throw new Error('Missing relief tile digest');
    if (data === undefined) throw new Error('Indexed relief tile missing from archive');
    if (await hash(data) !== digest) throw new Error('Relief tile hash mismatch');
  };
}
