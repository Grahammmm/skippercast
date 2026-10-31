// RF1200-9: client error messages lose North American phone numbers written
// with separators before they reach Analytics Engine (server/telemetry.ts scrub).
// Synthetic 555-01XX numbers only.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

const read = p => JSON.parse(readFileSync(new URL(p, import.meta.url)));
globalThis.REGIONS = {'morro-bay': read('../regions/morro-bay/region.json')};
globalThis.DEPLOYMENT = read('../deployments/production.json');
const {parseBatch, scrub} = await import('../server/telemetry.ts');

test('separated phone shapes become [phone] with the surrounding words intact', () => {
  for (const phone of ['805-555-0100', '(805) 555-0100', '805.555.0100', '805 555 0100', '+1 805-555-0100', '1 (805) 555-0100',
    '+1 805.555.0101', '1-805-555-0102', '(805)555-0103']) {
    assert.equal(scrub(`Invalid number ${phone} for contact`), 'Invalid number [phone] for contact', phone);
  }
  assert.equal(scrub('Call 805-555-0100.'), 'Call [phone].');
  assert.equal(scrub('a 805-555-0100, b (805) 555-0101'), 'a [phone], b [phone]');
});

test('an unseparated number keeps falling to the long-digit rule', () => {
  assert.equal(scrub('id 8055550100'), 'id #');
  assert.equal(scrub('id +18055550100'), 'id +#');
  assert.equal(scrub('id 805-5550100'), 'id 805-#', 'no separator before the last four digits');
});

test('times, dates, versions and short or non-NANP numbers are unchanged', () => {
  for (const text of ['at 12:30', 'v1.2.3', 'on 2026-10-31', 'at 2026-10-31T12:30:00Z', 'line 42 col 7', 'ext 555-0100',
    'bad 105-555-0100', 'bad 805-155-0100', 'bad 805-555-01000', 'v805.555.0100', 'x805-555-0100', '9805-555-0100']) {
    assert.equal(scrub(text), text.replace(/\d{6,}/g, '#'), text);
  }
});

test('the path rule runs first, then the phone rule, then e-mail', () => {
  const out = scrub('Failed https://a.test/call/tel:805-555-0100?token=abc&who=x#frag here');
  assert.equal(out, 'Failed https://a.test/call/tel:[phone] here');
  assert.doesNotMatch(out, /token|abc|frag|0100/);
  assert.equal(scrub('Reach 805-555-0100 bob@example.org'), 'Reach [phone] [email]');
  assert.equal(scrub('Reach (805) 555-0100 at 35.3658, -120.851'), 'Reach [phone] at [coord], [coord]');
});

test('the mask is applied before the 96-character cut', () => {
  const ninety = 'e'.repeat(76) + ' 805-555-0100.';
  assert.equal(ninety.length, 90);
  assert.equal(scrub(ninety), 'e'.repeat(76) + ' [phone].');
  const long = 'e'.repeat(88) + ' +1 (805) 555-0100';
  assert.ok(long.length > 96);
  const out = scrub(long);
  assert.ok(out.length <= 96);
  assert.ok(out.endsWith(' [phone]'), out);
  assert.doesNotMatch(out, /\d/);
});

test('parseBatch scrubs a phone out of an error event message', () => {
  const batch = parseBatch({build: 'dev', events: [{type: 'error', kind: 'error', message: 'Error: bad contact (805) 555-0100 rejected',
    source: 'app.js', line: 1, column: 2}]});
  const [event] = batch.events;
  assert.equal(event.message, 'Error: bad contact [phone] rejected');
  assert.doesNotMatch(event.message, /805|555|0100/);
});
