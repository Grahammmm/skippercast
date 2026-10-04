// Text Advisor contact card, deep link, QR code and source attribution (TA-C6;
// docs/plans/text-advisor/03-channels.md § contact card and deep links):
// the vCard's fields, CRLF and 75-octet folding; GET /contact.vcf, /text and
// /qr/text.svg; the QR encoder against matrices pinned from the reference
// encoder (Project Nayuki's qrcodegen, checked once when this was written) and
// a small decoder here that reads the payload back out of the matrix; the
// `[via <source>]` marker parser; and storeInbound keeping the first source.
import test from 'node:test';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {readFileSync} from 'node:fs';
import {execFileSync} from 'node:child_process';
import {advisorDatabase, sqliteUnavailable} from './_advisor_d1.mjs';

const read = p => JSON.parse(readFileSync(new URL(p, import.meta.url)));
globalThis.REGIONS = {'morro-bay': read('../regions/morro-bay/region.json')};
globalThis.DEPLOYMENT = read('../deployments/production.json');
globalThis.SHELLS = {'/': '/index.0123456789.html'};
globalThis.BUILD_ID = 'build-test';
const {default: worker} = await import('../server/index.ts');
const {contactCard, foldLine, VCARD_LINE_OCTETS} = await import('../server/advisor/pages/contact-card.ts');
const {CONTACT_ICON_PNG_BASE64} = await import('../server/advisor/pages/icon.ts');
const qr = await import('../server/advisor/pages/qr.ts');
const {parseSourceMarker, SOURCE_PATTERN} = await import('../server/advisor/intents.ts');
const {storeInbound} = await import('../server/advisor/inbound.ts');
const {textBody, TEXT_MAX_MESSAGE} = await import('../server/routes/advisor.ts');

const dbTest = (name, fn) => test(name, {skip: sqliteUnavailable || false}, fn);
const ORIGIN = 'https://skippercast.com';
const NUMBER = '+18055550123';
const ON = {TEXT_ADVISOR_ENABLED: 'true', ADVISOR_NUMBER: NUMBER};
const ASSETS = {fetch: async request => new Response(new URL(request.url).pathname, {status: 299})};
const get = (path, env) => worker.fetch(new Request(ORIGIN + path), {ASSETS, ...env});
const octets = s => Buffer.byteLength(s, 'utf8');

// ---- vCard ---------------------------------------------------------------------

/** Unfold RFC 2425 content lines: CRLF followed by one space joins to the previous line. */
const unfold = text => text.replace(/\r\n /g, '').split('\r\n').filter(Boolean);

test('the contact card is a vCard 3.0 with the number, the site and the app icon', () => {
  const card = contactCard({number: NUMBER, publicBase: 'https://skippercast.com'});
  assert.ok(card.endsWith('\r\n'));
  assert.doesNotMatch(card.replace(/\r\n/g, ''), /[\r\n]/, 'CRLF only, no bare LF or CR');
  const lines = unfold(card);
  assert.deepEqual(lines.filter(l => !l.startsWith('PHOTO')), [
    'BEGIN:VCARD', 'VERSION:3.0', 'FN:SkipperCast', 'N:SkipperCast;;;;', 'ORG:SkipperCast',
    `TEL;TYPE=CELL,VOICE:${NUMBER}`, 'URL:https://skippercast.com', 'END:VCARD',
  ]);
  const photo = lines.find(l => l.startsWith('PHOTO;ENCODING=b;TYPE=PNG:'));
  assert.ok(photo, 'PHOTO line');
  const png = Buffer.from(photo.slice('PHOTO;ENCODING=b;TYPE=PNG:'.length), 'base64');
  assert.deepEqual(png, readFileSync(new URL('../dist/app-icon-192.png', import.meta.url)), 'the photo is dist/app-icon-192.png');
  assert.equal(lines.indexOf(photo), lines.length - 2, 'PHOTO just before END');
  for (const physical of card.split('\r\n')) assert.ok(octets(physical) <= VCARD_LINE_OCTETS, `line over 75 octets: ${physical.slice(0, 20)}`);
  assert.ok(card.split('\r\n').length > 50, 'the photo is folded across many lines');
  assert.equal(unfold(contactCard({number: NUMBER, publicBase: 'https://example.org/sc', photo: null})).length, 8, 'no PHOTO line when photo is null');
  assert.throws(() => contactCard({number: '8055550123', publicBase: ORIGIN}), /E\.164/);
  assert.throws(() => contactCard({number: NUMBER, publicBase: 'http://x.org'}), /https/);
});

test('foldLine folds at 75 octets, continues with one space and never splits a UTF-8 character', () => {
  assert.equal(foldLine('a'.repeat(75)), 'a'.repeat(75));
  assert.equal(foldLine('a'.repeat(76)), `${'a'.repeat(75)}\r\n a`);
  assert.equal(foldLine('a'.repeat(75 + 74 + 1)), `${'a'.repeat(75)}\r\n ${'a'.repeat(74)}\r\n a`, 'continuations hold 74 octets after the space');
  const folded = foldLine('é'.repeat(80));
  for (const line of folded.split('\r\n')) { assert.ok(octets(line) <= 75); assert.doesNotMatch(line, /�/); }
  assert.equal(folded.replace(/\r\n /g, ''), 'é'.repeat(80));
});

test('the committed icon module matches dist/app-icon-192.png', () => {
  assert.equal(Buffer.from(CONTACT_ICON_PNG_BASE64, 'base64').toString('hex'), readFileSync(new URL('../dist/app-icon-192.png', import.meta.url)).toString('hex'),
    'run node scripts/advisor/make-contact-icon.mjs');
  execFileSync(process.execPath, ['scripts/advisor/make-contact-icon.mjs', '--check'], {cwd: new URL('..', import.meta.url)});
});

test('GET /contact.vcf: the card as an attachment, cached a day; 503 without a number; 404 while dark', async () => {
  const response = await get('/contact.vcf', ON);
  assert.equal(response.status, 200);
  assert.equal(response.headers.get('Content-Type'), 'text/vcard; charset=utf-8');
  assert.equal(response.headers.get('Content-Disposition'), 'attachment; filename="SkipperCast.vcf"');
  assert.equal(response.headers.get('Cache-Control'), 'public, max-age=86400');
  const text = await response.text();
  assert.equal(text, contactCard({number: NUMBER, publicBase: 'https://skippercast.com'}));
  const based = await (await get('/contact.vcf', {...ON, ADVISOR_PUBLIC_BASE: 'https://staging.skippercast.com'})).text();
  assert.ok(unfold(based).includes('URL:https://staging.skippercast.com'), 'URL is ADVISOR_PUBLIC_BASE');
  const none = await get('/contact.vcf', {TEXT_ADVISOR_ENABLED: 'true'});
  assert.equal(none.status, 503);
  assert.match(none.headers.get('Content-Type'), /^text\/plain/);
  assert.equal(none.headers.get('Cache-Control'), 'no-store');
  assert.equal((await get('/contact.vcf', {ADVISOR_NUMBER: NUMBER})).status, 404);
});

// ---- /text ---------------------------------------------------------------------

const bodyOf = location => { assert.ok(location.startsWith(`sms:${NUMBER}?&body=`), location); return decodeURIComponent(location.slice(`sms:${NUMBER}?&body=`.length)); };

test('GET /text redirects to sms:<number>?&body=<message> [via <source>]', async () => {
  const cases = [
    ['/text?s=ig&m=hi', 'hi [via ig]'],
    ['/text?s=qr', 'Hi SkipperCast [via qr]'],
    ['/text?m=Where%20are%20the%20rockfish%3F', 'Where are the rockfish?'],
    ['/text', 'Hi SkipperCast'],
    ['/text?s=ig:post_123&m=hi', 'hi [via ig:post_123]'],
    ['/text?s=IG&m=hi', 'hi', 'uppercase source dropped'],
    ['/text?s=ig%5D%20oops&m=hi', 'hi', 'source with a bracket and a space dropped'],
    ['/text?s=' + 'a'.repeat(33) + '&m=hi', 'hi', 'source over 32 characters dropped'],
    ['/text?s=&m=hi', 'hi', 'empty source dropped'],
    ['/text?m=%20%20&s=web', 'Hi SkipperCast [via web]', 'blank message gets the default'],
    ['/text?m=a%0Ab%00c', 'a b c', 'control characters become spaces'],
  ];
  for (const [path, expected, why] of cases) {
    const response = await get(path, ON);
    assert.equal(response.status, 302, path);
    assert.equal(response.headers.get('Cache-Control'), 'no-store');
    assert.equal(bodyOf(response.headers.get('Location')), expected, why ?? path);
  }
  const long = 'x'.repeat(200);
  assert.equal(bodyOf((await get(`/text?s=qr&m=${long}`, ON)).headers.get('Location')), `${'x'.repeat(TEXT_MAX_MESSAGE)} [via qr]`, 'message capped at 140');
  const emoji = '🎣'.repeat(150);
  assert.equal(textBody(emoji, null), '🎣'.repeat(140), 'the cap counts characters, not UTF-16 units');
  // Encoding: & = ? # + and spaces in the body cannot break out of the body parameter.
  const location = (await get('/text?m=' + encodeURIComponent('a&b=c?d#e+f g') + '&s=qr', ON)).headers.get('Location');
  assert.equal(location, `sms:${NUMBER}?&body=${encodeURIComponent('a&b=c?d#e+f g [via qr]')}`);
  assert.doesNotMatch(location.slice(location.indexOf('body=') + 5), /[&?# +]/);
  assert.equal((await get('/text?s=qr', {TEXT_ADVISOR_ENABLED: 'true'})).status, 503, 'no number');
  assert.equal((await get('/text?s=qr', {ADVISOR_NUMBER: NUMBER})).status, 404, 'dark');
});

test('every source /text accepts round-trips through parseSourceMarker', () => {
  for (const source of ['ig', 'qr', 'web', 'fb', 'igdm', 'skipper-invite', 'a', 'x_1:2-3', 'z'.repeat(32)]) {
    assert.match(source, SOURCE_PATTERN);
    const parsed = parseSourceMarker(textBody('hello there', source));
    assert.equal(parsed.text, 'hello there');
    assert.equal(parsed.source, source);
  }
  assert.deepEqual(parseSourceMarker(textBody('hi', 'ig:17895695668004550')), {text: 'hi', source: 'ig', postId: '17895695668004550'});
});

// ---- source marker -------------------------------------------------------------

test('parseSourceMarker strips a trailing [via <source>] and nothing else', () => {
  const table = [
    ['Hi SkipperCast [via qr]', {text: 'Hi SkipperCast', source: 'qr'}],
    ['hi [via ig]', {text: 'hi', source: 'ig'}],
    ['hi [via ig]  \n', {text: 'hi', source: 'ig'}],
    ['[via web]', {text: '', source: 'web'}],
    ['hi [via ig:12345]', {text: 'hi', source: 'ig', postId: '12345'}],
    ['hi [via ig:]', {text: 'hi', source: 'ig:'}],
    ['hi [via skipper-invite]', {text: 'hi', source: 'skipper-invite'}],
    ['hi', {text: 'hi', source: null}],
    ['', {text: '', source: null}],
    ['[via qr] then more', {text: '[via qr] then more', source: null}],
    ['hi [via QR]', {text: 'hi [via QR]', source: null}],
    ['hi [via  qr]', {text: 'hi [via  qr]', source: null}],
    ['hi [via q r]', {text: 'hi [via q r]', source: null}],
    ['hi [via ]', {text: 'hi [via ]', source: null}],
    [`hi [via ${'a'.repeat(33)}]`, {text: `hi [via ${'a'.repeat(33)}]`, source: null}],
    ['hi [via qr] [via ig]', {text: 'hi [via qr]', source: 'ig'}],
    ['hi (via qr)', {text: 'hi (via qr)', source: null}],
  ];
  for (const [input, expected] of table) assert.deepEqual(parseSourceMarker(input), expected, JSON.stringify(input));
  assert.deepEqual(parseSourceMarker(undefined), {text: '', source: null});
});

// ---- storeInbound --------------------------------------------------------------

const KEY = Buffer.alloc(32, 5).toString('base64');
let seq = 0;
const inbound = (text, from = '+18055550111') => ({channel: 'sms', providerId: `p-${++seq}`, from, to: NUMBER, text, media: [], receivedAt: new Date().toISOString(), isGroup: false});

dbTest('storeInbound strips the marker from the body and sets the contact source on the first message only', async () => {
  const {sql, db} = advisorDatabase(), env = {DB: db, ADVISOR_PHONE_KEY: KEY};
  const first = await storeInbound(env, inbound('Hi SkipperCast [via qr]'));
  assert.ok(first);
  assert.equal(sql.prepare('SELECT body FROM advisor_messages WHERE id=?').get(first).body, 'Hi SkipperCast');
  const contact = () => sql.prepare('SELECT source FROM advisor_contacts').all();
  assert.deepEqual(contact().map(r => r.source), ['qr']);
  const second = await storeInbound(env, inbound('again [via ig]'));
  assert.equal(sql.prepare('SELECT body FROM advisor_messages WHERE id=?').get(second).body, 'again', 'a later marker is still stripped');
  assert.deepEqual(contact().map(r => r.source), ['qr'], 'the first value is kept');

  // A contact whose first message had no marker gets none later either: source is first touch.
  await storeInbound(env, inbound('plain hello', '+18055550122'));
  await storeInbound(env, inbound('now [via ig]', '+18055550122'));
  assert.equal(sql.prepare('SELECT COUNT(*) n FROM advisor_contacts WHERE source IS NULL').get().n, 1);

  // Only a marker: the stored body is NULL, like a media-only message.
  const bare = await storeInbound(env, inbound('[via web]', '+18055550133'));
  assert.equal(sql.prepare('SELECT body FROM advisor_messages WHERE id=?').get(bare).body, null);
  assert.ok(sql.prepare("SELECT 1 FROM advisor_contacts WHERE source='web'").get());

  // ig:<post_id> records 'ig'; a duplicate delivery changes nothing.
  const msg = inbound('fish? [via ig:17895695668004550]', '+18055550144');
  assert.ok(await storeInbound(env, msg));
  assert.equal(await storeInbound(env, msg), null);
  assert.equal(sql.prepare("SELECT COUNT(*) n FROM advisor_contacts WHERE source='ig'").get().n, 1);
  assert.equal(sql.prepare("SELECT COUNT(*) n FROM advisor_messages WHERE body='fish?'").get().n, 1);
});

// ---- QR ------------------------------------------------------------------------

const matrixHash = code => createHash('sha256').update(code.modules.map(r => r.map(Number).join('')).join('\n')).digest('hex');

// Version, mask and matrix SHA-256 from qrcodegen 1.8 (level M, byte mode, no ECC boost, versions 1-10).
const REFERENCE = [
  ['https://skippercast.com/text?s=qr', 3, 0, '0c1c050b1ca166d6e5c7c99c02323f4c4abd9111958154a07145ba25f6013c63'],
  ['HELLO', 1, 4, 'c346c75add5698735afe3f7eb4f3e6c57ccefd9563f45f65c6d76aa518fb6f91'],
  ['https://example.org/' + 'y'.repeat(100), 7, 1, '553c6b88aa1f17b1c6c83937270b2e871301ddcf6854735e5efa95206858c2ea'],
  ['w'.repeat(213), 10, 6, '8b26bac8f5400ff35ef58718036a413dd89b119207b8a6caa503a3ebab8f9565'],
];

test('the QR encoder matches the reference encoder on pinned payloads (versions 1, 3, 7 and 10)', () => {
  for (const [text, version, mask, hash] of REFERENCE) {
    const code = qr.encodeQr(text);
    assert.deepEqual({version: code.version, size: code.size, mask: code.mask}, {version, size: version * 4 + 17, mask}, text.slice(0, 20));
    assert.equal(matrixHash(code), hash, text.slice(0, 20));
  }
  assert.throws(() => qr.encodeQr('w'.repeat(214)), /too long/);
  assert.deepEqual([1, 2, 3, 4, 5, 6, 7, 8, 9, 10].map(qr.byteCapacity), [14, 26, 42, 62, 84, 106, 122, 152, 180, 213], 'level-M byte capacities from the specification');
});

// A small decoder, independent of the encoder's matrix code: function-pattern map,
// format information (both copies), unmask, zigzag read, de-interleave, check
// each block's error correction and parse the byte-mode segment.
const BLOCK_LAYOUT = {1: [1, 10], 2: [1, 16], 3: [1, 26], 4: [2, 18], 5: [2, 24], 6: [4, 16], 7: [4, 18], 8: [4, 22], 9: [5, 22], 10: [5, 26]};
const ALIGN = {1: [], 2: [6, 18], 3: [6, 22], 4: [6, 26], 5: [6, 30], 6: [6, 34], 7: [6, 22, 38], 8: [6, 24, 42], 9: [6, 26, 46], 10: [6, 28, 50]};
const MASK = [(x, y) => (x + y) % 2 === 0, (x, y) => y % 2 === 0, x => x % 3 === 0, (x, y) => (x + y) % 3 === 0,
  (x, y) => (Math.floor(x / 3) + Math.floor(y / 2)) % 2 === 0, (x, y) => (x * y) % 2 + (x * y) % 3 === 0,
  (x, y) => ((x * y) % 2 + (x * y) % 3) % 2 === 0, (x, y) => ((x + y) % 2 + (x * y) % 3) % 2 === 0];

function decode(m) {
  const size = m.length, version = (size - 17) / 4;
  assert.ok(Number.isInteger(version) && version >= 1 && version <= 10, 'size');
  // Finder patterns: 7x7 rings at three corners, with light separators.
  for (const [ox, oy] of [[0, 0], [size - 7, 0], [0, size - 7]]) {
    for (let y = 0; y < 7; y++) for (let x = 0; x < 7; x++) {
      const d = Math.max(Math.abs(x - 3), Math.abs(y - 3));
      assert.equal(m[oy + y][ox + x], d !== 2, `finder at ${ox},${oy}`);
    }
  }
  for (let i = 0; i < 8; i++) { assert.equal(m[7][i], false); assert.equal(m[i][7], false); assert.equal(m[7][size - 1 - i], false); assert.equal(m[size - 1 - i][7], false); }
  for (let i = 8; i < size - 8; i++) { assert.equal(m[6][i], i % 2 === 0, 'timing'); assert.equal(m[i][6], i % 2 === 0, 'timing'); }
  const fn = Array.from({length: size}, () => new Array(size).fill(false));
  const mark = (x, y) => { if (x >= 0 && y >= 0 && x < size && y < size) fn[y][x] = true; };
  for (let y = 0; y < 9; y++) for (let x = 0; x < 9; x++) mark(x, y);
  for (let y = 0; y < 9; y++) for (let x = 0; x < 8; x++) mark(size - 8 + x, y);
  for (let y = 0; y < 8; y++) for (let x = 0; x < 9; x++) mark(x, size - 8 + y);
  for (let i = 0; i < size; i++) { mark(6, i); mark(i, 6); }
  const a = ALIGN[version];
  for (const cx of a) for (const cy of a) {
    if ((cx < 9 && cy < 9) || (cx > size - 9 && cy < 9) || (cx < 9 && cy > size - 9)) continue;   // overlaps a finder
    for (let dy = -2; dy <= 2; dy++) for (let dx = -2; dx <= 2; dx++) { mark(cx + dx, cy + dy); assert.equal(m[cy + dy][cx + dx], Math.max(Math.abs(dx), Math.abs(dy)) !== 1, 'alignment'); }
  }
  if (version >= 7) for (let i = 0; i < 6; i++) for (let j = 0; j < 3; j++) { mark(size - 11 + j, i); mark(i, size - 11 + j); }
  // Format information: copy 1 around the top-left finder.
  const f1 = [];
  for (let i = 0; i <= 5; i++) f1.push(m[i][8]);
  f1.push(m[7][8], m[8][8], m[8][7]);
  for (let i = 9; i < 15; i++) f1.push(m[8][14 - i]);
  const f2 = [];
  for (let i = 0; i < 8; i++) f2.push(m[8][size - 1 - i]);
  for (let i = 8; i < 15; i++) f2.push(m[size - 15 + i][8]);
  assert.deepEqual(f1, f2, 'both format copies agree');
  assert.equal(m[size - 8][8], true, 'dark module');
  const format = f1.reduce((acc, bit, i) => acc | (Number(bit) << i), 0) ^ 0x5412;
  assert.equal(format >> 13, 0, 'error correction level M');
  const mask = (format >> 10) & 7;
  // Zigzag read of the unmasked data modules.
  const bits = [];
  for (let right = size - 1; right >= 1; right -= 2) {
    if (right === 6) right = 5;
    for (let vert = 0; vert < size; vert++) for (let j = 0; j < 2; j++) {
      const x = right - j, y = ((right + 1) & 2) === 0 ? size - 1 - vert : vert;
      if (!fn[y][x]) bits.push(m[y][x] !== MASK[mask](x, y));
    }
  }
  const total = Math.floor(bits.length / 8), bytes = [];
  for (let i = 0; i < total; i++) bytes.push(bits.slice(i * 8, i * 8 + 8).reduce((acc, b) => (acc << 1) | Number(b), 0));
  const [blocks, ecc] = BLOCK_LAYOUT[version], short = Math.floor(total / blocks), longCount = total % blocks;
  const dataLen = i => short - ecc + (i >= blocks - longCount ? 1 : 0);
  const data = Array.from({length: blocks}, () => []), checks = Array.from({length: blocks}, () => []);
  let k = 0;
  for (let i = 0; i < short - ecc + 1; i++) for (let b = 0; b < blocks; b++) if (i < dataLen(b)) data[b].push(bytes[k++]);
  for (let i = 0; i < ecc; i++) for (let b = 0; b < blocks; b++) checks[b].push(bytes[k++]);
  for (let b = 0; b < blocks; b++) assert.deepEqual(qr.rsRemainder(data[b], qr.rsDivisor(ecc)), checks[b], `block ${b} error correction`);
  const stream = data.flat().flatMap(byte => [7, 6, 5, 4, 3, 2, 1, 0].map(s => (byte >> s) & 1));
  const take = n => { let v = 0; for (let i = 0; i < n; i++) v = (v << 1) | stream.shift(); return v; };
  assert.equal(take(4), 0b0100, 'byte mode');
  const length = take(version <= 9 ? 8 : 16);
  return {mask, text: new TextDecoder().decode(Uint8Array.from({length}, () => take(8)))};
}

test('every pinned payload, and the real deep link, decodes back out of its matrix with every mask', () => {
  const payloads = [...REFERENCE.map(r => r[0]), 'a', 'ünïcødé 🎣', 'z'.repeat(150), 'q'.repeat(120), 'https://skippercast.com/text?s=qr'];
  for (const text of payloads) {
    const best = qr.encodeQr(text);
    assert.deepEqual(decode(best.modules), {mask: best.mask, text}, text.slice(0, 20));
    for (let mask = 0; mask < 8; mask++) assert.deepEqual(decode(qr.encodeQr(text, mask).modules), {mask, text}, `${text.slice(0, 20)} mask ${mask}`);
  }
});

test('the Reed-Solomon helpers match the specification example (version 1-M, "01234567")', () => {
  // ISO/IEC 18004 Annex I: data codewords for "01234567" in numeric mode, level M.
  const data = [0x10, 0x20, 0x0c, 0x56, 0x61, 0x80, 0xec, 0x11, 0xec, 0x11, 0xec, 0x11, 0xec, 0x11, 0xec, 0x11];
  assert.deepEqual(qr.rsRemainder(data, qr.rsDivisor(10)), [0xa5, 0x24, 0xd4, 0xc1, 0xed, 0x36, 0xc7, 0x87, 0x2c, 0x55]);
  assert.equal(qr.formatBits(0).toString(2).padStart(15, '0'), '101010000010010', 'level M, mask 0');
  assert.equal(qr.versionBits(7).toString(2).padStart(18, '0'), '000111110010010100');
});

test('GET /qr/text.svg: the deep link with s=qr as an SVG, quiet zone included, cached a day', async () => {
  const response = await get('/qr/text.svg', ON);
  assert.equal(response.status, 200);
  assert.equal(response.headers.get('Content-Type'), 'image/svg+xml; charset=utf-8');
  assert.equal(response.headers.get('Cache-Control'), 'public, max-age=86400');
  const svg = await response.text();
  assert.equal(svg, qr.qrSvg('https://skippercast.com/text?s=qr'));
  const side = 29 + 2 * qr.QUIET_ZONE;   // version 3
  assert.match(svg, new RegExp(`viewBox="0 0 ${side} ${side}" width="${side * 8}" height="${side * 8}"`));
  assert.doesNotMatch(svg, /<script|on\w+=/i);
  // Rebuild the matrix from the path's runs and decode it.
  const modules = Array.from({length: 29}, () => new Array(29).fill(false));
  for (const [, x, y, w] of svg.matchAll(/M(\d+) (\d+)h(\d+)v1h-\d+z/g)) for (let i = 0; i < Number(w); i++) modules[Number(y) - 4][Number(x) - 4 + i] = true;
  assert.equal(decode(modules).text, 'https://skippercast.com/text?s=qr');
  const staging = await (await get('/qr/text.svg', {TEXT_ADVISOR_ENABLED: 'true', ADVISOR_PUBLIC_BASE: 'https://staging.skippercast.com'})).text();
  assert.equal(staging, qr.qrSvg('https://staging.skippercast.com/text?s=qr'), 'ADVISOR_PUBLIC_BASE, and no number needed');
  assert.equal((await get('/qr/text.svg', {})).status, 404, 'dark');
});
