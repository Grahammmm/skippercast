// RF1230-6: the upload reader recognises an RFC 5987 filename*= (UTF-8,
// percent-encoded) as a file part, prefers its decoded name over filename=,
// and falls back (to filename= or a null name) on a bad one without throwing.
import test from 'node:test';
import assert from 'node:assert/strict';

const {firstFile} = await import('../server/advisor/multipart.ts');

const part = (disposition, content = 'DATA') =>
  `--b\r\nContent-Disposition: form-data; ${disposition}\r\nContent-Type: image/jpeg\r\n\r\n${content}\r\n`;
const upload = (...parts) => new Request('https://x/', {
  method: 'POST',
  headers: {'content-type': 'multipart/form-data; boundary=b'},
  body: parts.join('') + '--b--\r\n',
});
const read = async (...parts) => {
  const file = await firstFile(upload(...parts));
  return {name: file.name, text: await new Response(file.body).text()};
};

test('a part with only filename*=UTF-8 is a file, its name decoded and its bytes intact', async () => {
  const got = await read(part(`name="f"; filename*=UTF-8''%E2%82%AC%20rates.jpg`, 'euro bytes'));
  assert.equal(got.name, '€ rates.jpg');
  assert.equal(got.text, 'euro bytes');
});

test('the decoded filename*= wins over filename= in either order; the charset is case-insensitive', async () => {
  assert.equal((await read(part(`name="f"; filename="rates.jpg"; filename*=UTF-8''%C3%A9t%C3%A9.jpg`))).name, 'été.jpg');
  assert.equal((await read(part(`name="f"; filename*=UTF-8''%C3%A9t%C3%A9.jpg; filename="rates.jpg"`))).name, 'été.jpg');
  assert.equal((await read(part(`name="f"; filename=rates.jpg; filename*=utf-8'en'%C3%A9t%C3%A9.jpg`))).name, 'été.jpg');
});

test('broken percent-encoding falls back to filename=, or to a null name that is still a file', async () => {
  assert.equal((await read(part(`name="f"; filename*=UTF-8''%ZZ.jpg; filename="ok.jpg"`))).name, 'ok.jpg');
  assert.equal((await read(part(`name="f"; filename="ok.jpg"; filename*=UTF-8''%E2%82.jpg`))).name, 'ok.jpg');
  const alone = await read(part(`name="f"; filename*=UTF-8''%ZZ.jpg`, 'kept'));
  assert.equal(alone.name, null);
  assert.equal(alone.text, 'kept');
});

test('another charset or a value without the charset\'\'lang\' structure gives no name but still a file', async () => {
  const latin = await read(part(`name="f"; filename*=iso-8859-1''caf%E9.jpg`, 'latin'));
  assert.equal(latin.name, null);
  assert.equal(latin.text, 'latin');
  assert.equal((await read(part(`name="f"; filename*=caf%C3%A9.jpg`))).name, null);
  assert.equal((await read(part(`name="f"; filename*=UTF-8'caf%C3%A9.jpg; filename="plain.jpg"`))).name, 'plain.jpg');
});

test('the decoded name is sanitised: no slashes, no CR/LF, capped at 200 characters', async () => {
  const traversal = (await read(part(`name="f"; filename*=UTF-8''..%2F..%2Fetc%2Fpasswd`))).name;
  assert.ok(!traversal.includes('/'), traversal);
  assert.equal(traversal, '....etcpasswd');
  assert.equal((await read(part(`name="f"; filename*=UTF-8''a%5Cb%0D%0Ac.jpg`))).name, 'abc.jpg');
  assert.equal((await read(part(`name="f"; filename*=UTF-8''${'a'.repeat(300)}`))).name, 'a'.repeat(200));
  // A decoded name that sanitises to nothing is a null name, still a file.
  assert.equal((await read(part(`name="f"; filename*=UTF-8''%2F%0A`))).name, null);
});

test('a plain field before the filename*= part is skipped and the file part returned', async () => {
  const got = await read(
    `--b\r\nContent-Disposition: form-data; name="note"\r\n\r\nhello\r\n`,
    part(`name="f"; filename*=UTF-8''%C3%A9.jpg`, 'second'),
  );
  assert.equal(got.name, 'é.jpg');
  assert.equal(got.text, 'second');
});

test('plain filename= forms are unchanged', async () => {
  assert.equal((await read(part(`name="f"; filename="clip.mov"`))).name, 'clip.mov');
  assert.equal((await read(part(`name="f"; filename=clip.mov`))).name, 'clip.mov');
});
