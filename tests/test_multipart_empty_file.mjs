// RF1239-5: an empty file input (filename="" with no bytes, what a browser
// sends when nothing was picked) is skipped by server/advisor/multipart.ts
// firstFile like a plain field, so an upload with no real file is the 400
// "no file in the upload", not a zero-byte file. Bodies are built here.
import test from 'node:test';
import assert from 'node:assert/strict';

const {firstFile} = await import('../server/advisor/multipart.ts');
const {ClientError} = await import('../server/errors.ts');

const B = 'rf1239boundary';
const enc = new TextEncoder();
const bytes = n => new Uint8Array(n).map((_, i) => (i * 7 + 3) & 255);
const empty = (disposition = 'filename=""') => ({head: `Content-Disposition: form-data; name="file"; ${disposition}\r\nContent-Type: application/octet-stream`, body: new Uint8Array(0)});
const field = () => ({head: 'Content-Disposition: form-data; name="note"', body: enc.encode('hello')});
const file = (name, body, type = 'image/jpeg') => ({head: `Content-Disposition: form-data; name="file"; filename="${name}"\r\nContent-Type: ${type}`, body});

/** A multipart/form-data Request with `parts` in order, closed by `--B--`. */
function upload(parts) {
  const chunks = [];
  for (const p of parts) chunks.push(enc.encode(`--${B}\r\n${p.head}\r\n\r\n`), p.body, enc.encode('\r\n'));
  chunks.push(enc.encode(`--${B}--\r\n`));
  const raw = new Uint8Array(chunks.reduce((n, c) => n + c.length, 0));
  let at = 0; for (const c of chunks) { raw.set(c, at); at += c.length; }
  return new Request('https://x/', {method: 'POST', headers: {'content-type': `multipart/form-data; boundary=${B}`}, body: raw});
}
const read = async f => new Uint8Array(await new Response(f.body).arrayBuffer());
const sameBytes = (a, b) => a.length === b.length && a.every((v, i) => v === b[i]);
const noFile = err => err instanceof ClientError && err.message === 'no file in the upload';

test('only an empty file input (filename="") is "no file in the upload"', async () => {
  await assert.rejects(firstFile(upload([empty()])), noFile);
});

test('an unquoted empty filename= is "no file in the upload"', async () => {
  // The unquoted pattern needs one character, so this part was never a file part; the outcome is pinned here.
  await assert.rejects(firstFile(upload([empty('filename=')])), noFile);
});

test('an empty file input before a real file resolves to the real file', async () => {
  const content = bytes(5000);
  const f = await firstFile(upload([empty(), file('a.jpg', content)]));
  assert.equal(f.name, 'a.jpg');
  assert.equal(f.type, 'image/jpeg');
  assert.ok(sameBytes(await read(f), content), 'body bytes of the second part');
});

test('a plain field, then an empty file input, then a real file resolves to the real file', async () => {
  const content = bytes(300);
  const f = await firstFile(upload([field(), empty(), file('b.png', content, 'image/png')]));
  assert.deepEqual([f.name, f.type], ['b.png', 'image/png']);
  assert.ok(sameBytes(await read(f), content), 'body bytes of the third part');
});

test('a filename that sanitises to empty ("///") is still a file part with name null', async () => {
  const content = bytes(64);
  const f = await firstFile(upload([file('///', content)]));
  assert.equal(f.name, null);
  assert.ok(sameBytes(await read(f), content), 'body bytes unchanged');
});

test('a normal single file keeps its name, type and bytes', async () => {
  const content = bytes(70000);
  const f = await firstFile(upload([file('fish.jpg', content)]));
  assert.deepEqual([f.name, f.type], ['fish.jpg', 'image/jpeg']);
  assert.ok(sameBytes(await read(f), content), 'body bytes unchanged');
});

test('nine empty file inputs are "no file in the upload" (the 8-part cap holds)', async () => {
  await assert.rejects(firstFile(upload(Array.from({length: 9}, () => empty()))), noFile);
});

test('eight empty file inputs then a real file is still refused by the 8-part cap', async () => {
  await assert.rejects(firstFile(upload([...Array.from({length: 8}, () => empty()), file('late.jpg', bytes(10))])), noFile);
});
