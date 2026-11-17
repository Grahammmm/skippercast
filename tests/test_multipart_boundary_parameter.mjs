// RF0015-18: boundaryOf returns a complete boundary parameter value or null,
// never a truncated prefix of an over-long or trailing-junk value.
import test from 'node:test';
import assert from 'node:assert/strict';

const {boundaryOf, firstFile} = await import('../server/advisor/multipart.ts');
const {ClientError} = await import('../server/errors.ts');

const ct = p => `multipart/form-data; ${p}`;
const enc = new TextEncoder();

test('unquoted boundary: 1 and 70 characters kept whole; 71 and longer rejected', () => {
  assert.equal(boundaryOf(ct('boundary=a')), 'a');
  assert.equal(boundaryOf(ct(`boundary=${'a'.repeat(70)}`)), 'a'.repeat(70));
  assert.equal(boundaryOf(ct(`boundary=${'a'.repeat(71)}`)), null);
  assert.equal(boundaryOf(ct(`boundary=${'a'.repeat(500)}`)), null);
});

test('quoted boundary: 70 characters kept whole; 71 rejected', () => {
  assert.equal(boundaryOf(ct(`boundary="${'b'.repeat(70)}"`)), 'b'.repeat(70));
  assert.equal(boundaryOf(ct(`boundary="${'b'.repeat(71)}"`)), null);
});

test('trailing junk after the value is rejected, not truncated', () => {
  for (const p of ['boundary=abc def', 'boundary="abc"junk', 'boundary=abc def; charset=utf-8', 'boundary="abc"junk; charset=utf-8']) {
    assert.equal(boundaryOf(ct(p)), null, p);
  }
});

test('valid terminators keep the value', () => {
  assert.equal(boundaryOf(ct('boundary=abc')), 'abc');
  assert.equal(boundaryOf(ct('boundary=abc; charset=utf-8')), 'abc');
  assert.equal(boundaryOf(ct('boundary=abc \t')), 'abc');
  assert.equal(boundaryOf(ct('boundary="abc def"')), 'abc def');
  assert.equal(boundaryOf(ct('boundary="abc" \t; charset=utf-8')), 'abc');
  assert.equal(boundaryOf('Multipart/Form-Data; BOUNDARY=abc'), 'abc');
});

test('missing, empty and non-multipart stay null', () => {
  assert.equal(boundaryOf(null), null);
  assert.equal(boundaryOf(ct('charset=utf-8')), null);
  assert.equal(boundaryOf(ct('boundary=')), null);
  assert.equal(boundaryOf('text/plain; boundary=abc'), null);
});

test('firstFile rejects a 71-char header before acquiring a reader', async () => {
  const header = 'a'.repeat(71), prefix = 'a'.repeat(70);
  const body = enc.encode(`--${prefix}\r\nContent-Disposition: form-data; name="file"; filename="synthetic.txt"\r\nContent-Type: text/plain\r\n\r\nsynthetic\r\n--${prefix}--\r\n`);
  let readers = 0;
  const stream = new ReadableStream({start(c) { c.enqueue(body); c.close(); }});
  const real = stream.getReader.bind(stream);
  stream.getReader = (...a) => { readers++; return real(...a); };
  const request = {headers: new Headers({'content-type': ct(`boundary=${header}`)}), body: stream};
  await assert.rejects(firstFile(request), e => e instanceof ClientError && e.message === 'expected a multipart file upload');
  assert.equal(readers, 0);
});

test('a valid 70-char boundary streams the file across split chunks', async () => {
  const b = 'z'.repeat(70), payload = 'synthetic payload';
  const raw = enc.encode(`--${b}\r\nContent-Disposition: form-data; name="file"; filename="synthetic.txt"\r\nContent-Type: text/plain\r\n\r\n${payload}\r\n--${b}--\r\n`);
  const stream = new ReadableStream({start(c) {
    for (let i = 0; i < raw.length; i += 7) c.enqueue(raw.slice(i, i + 7));
    c.close();
  }});
  const f = await firstFile({headers: new Headers({'content-type': ct(`boundary=${b}`)}), body: stream});
  assert.equal(f.name, 'synthetic.txt');
  assert.equal(f.type, 'text/plain');
  assert.equal(await new Response(f.body).text(), payload);
});
