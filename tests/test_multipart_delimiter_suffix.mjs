// RF1110-1: server/advisor/multipart.ts firstFile only ends a file at a real
// delimiter (CRLF--boundary followed by CRLF or "--"). The same bytes followed
// by anything else are file content, whatever the chunk splits. Bodies are
// built here from synthetic bytes; nothing leaves the process.
import test from 'node:test';
import assert from 'node:assert/strict';

const {firstFile} = await import('../server/advisor/multipart.ts');
const {ClientError} = await import('../server/errors.ts');

const B = 'sampleXYZ';
const enc = new TextEncoder();
const cat = (...xs) => { const o = new Uint8Array(xs.reduce((n, x) => n + x.length, 0)); let a = 0; for (const x of xs) { o.set(x, a); a += x.length; } return o; };
const str = s => enc.encode(s);
const same = (a, b) => a.length === b.length && a.every((v, i) => v === b[i]);
const FILE_HEAD = str(`--${B}\r\nContent-Disposition: form-data; name="file"; filename="a.bin"\r\nContent-Type: application/octet-stream\r\n\r\n`);
const FIELD = str(`--${B}\r\nContent-Disposition: form-data; name="note"\r\n\r\nhi\r\n--${B}z\r\nContent-Disposition: form-data; name="f"; filename="fake.bin"\r\n\r\nmore\r\n`);

/** A Request streaming `raw` in `step`-byte chunks; `log.cancels` counts source cancels. */
function chunked(raw, step, log = {cancels: 0}) {
  let at = 0;
  const body = new ReadableStream({
    pull(c) { if (at >= raw.length) return c.close(); c.enqueue(raw.slice(at, at += step)); },
    cancel() { log.cancels++; },
  });
  return new Request('https://x/', {method: 'POST', headers: {'content-type': `multipart/form-data; boundary=${B}`}, body, duplex: 'half'});
}
const read = async f => { const parts = []; for await (const c of f.body) parts.push(c); return cat(...parts); };
const STEPS = [1, 2, 3, 7, 4096];

test('file_preserves_boundary_token_followed_by_non_suffix', async () => {
  // Several candidates (token + an ordinary byte) and binary bytes, byte-for-byte.
  const lookalike = cat(str('before'), str('\r\n--sampleXYZ!'), str('mid'), str('\r\n--sampleXYZ\rX'), str('\r\n--sampleXYZ-X'), new Uint8Array([0, 255, 13, 10, 45, 45, 13]));
  for (const step of STEPS) {
    const f = await firstFile(chunked(cat(FILE_HEAD, lookalike, str(`\r\n--${B}--\r\n`)), step));
    assert.ok(same(await read(f), lookalike), `bytes at step ${step}`);
  }
});

test('delimiter_and_suffix_split_at_every_offset', async () => {
  const tailOf = suffix => cat(FILE_HEAD, str('abc'), str(`\r\n--${B}`), str(suffix), str('LATER'));
  // Real terminators: CRLF (next part) and "--" (closing) cut the file at "abc" at every split.
  for (const suffix of ['\r\n', '--']) {
    const raw = tailOf(suffix);
    for (let step = 1; step <= raw.length; step++) {
      const f = await firstFile(chunked(raw, step));
      assert.ok(same(await read(f), str('abc')), `terminator ${JSON.stringify(suffix)} step ${step}`);
    }
  }
  // False candidates: CR then non-LF, lone hyphen then non-hyphen, other bytes: all content, then a real end.
  for (const suffix of ['\rX', '-X', 'Q', ' \r\n']) {
    const content = cat(str('abc'), str(`\r\n--${B}`), str(suffix), str('LATER'));
    const raw = cat(FILE_HEAD, content, str(`\r\n--${B}--\r\n`));
    for (let step = 1; step <= 40; step++) {
      const f = await firstFile(chunked(raw, step));
      assert.ok(same(await read(f), content), `lookalike ${JSON.stringify(suffix)} step ${step}`);
    }
  }
});

test('plain_field_lookalike_does_not_hide_later_file', async () => {
  const content = str('real file bytes');
  const raw = cat(FIELD, FILE_HEAD, content, str(`\r\n--${B}--\r\n`));
  for (const step of STEPS) {
    const f = await firstFile(chunked(raw, step));
    assert.equal(f.name, 'a.bin');
    assert.equal(f.type, 'application/octet-stream');
    assert.ok(same(await read(f), content), `bytes at step ${step}`);
  }
});

test('incomplete_suffix_at_eof_rejects', async () => {
  const early = err => err instanceof ClientError && err.message === 'upload ended early';
  for (const tail of ['\r\n--sampleXY', `\r\n--${B}`, `\r\n--${B}\r`, `\r\n--${B}-`]) {
    for (const step of [1, 5, 4096]) {
      const f = await firstFile(chunked(cat(FILE_HEAD, str('abc'), str(tail)), step));
      await assert.rejects(read(f), early, `tail ${JSON.stringify(tail)} step ${step}`);
    }
  }
});

test('real_boundary_and_cancel_still_stop_source', async () => {
  // A real next-part delimiter ends the file, excludes the later part and cancels the source once.
  const log = {cancels: 0};
  const f = await firstFile(chunked(cat(FILE_HEAD, str('abc'), str(`\r\n--${B}\r\nLATER PART`)), 4, log));
  assert.ok(same(await read(f), str('abc')));
  assert.equal(log.cancels, 1);
  // Downstream cancel reaches the source once.
  const log2 = {cancels: 0};
  const g = await firstFile(chunked(cat(FILE_HEAD, new Uint8Array(100000).fill(7), str(`\r\n--${B}--\r\n`)), 1000, log2));
  const reader = g.body.getReader();
  assert.ok((await reader.read()).value.length > 0);
  await reader.cancel();
  assert.equal(log2.cancels, 1);
  // A large chunked payload streams through in pieces, never as one whole-body chunk.
  const big = new Uint8Array(3_000_000).map((_, i) => (i * 31 + 7) & 255);
  const h = await firstFile(chunked(cat(FILE_HEAD, big, str(`\r\n--${B}--\r\n`)), 65536));
  let total = 0, biggest = 0, ok = true;
  for await (const c of h.body) { for (let i = 0; i < c.length; i++) if (c[i] !== big[total + i]) ok = false; total += c.length; biggest = Math.max(biggest, c.length); }
  assert.ok(ok && total === big.length, 'bytes preserved');
  assert.ok(biggest < big.length / 4, `largest chunk ${biggest} is far below the body size`);
});
