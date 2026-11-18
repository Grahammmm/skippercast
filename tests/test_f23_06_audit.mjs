// SCA-225 / F23-06: the data-issue form must not solicit private locations. Synthetic, offline.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';

const path = new URL('../.github/ISSUE_TEMPLATE/data-issue.yml', import.meta.url);

// Minimal reader for the flat GitHub form shape: body items start at "  - type:".
function items(text) {
  return text.split(/^ {2}- type: /m).slice(1).map(chunk => {
    const lines = chunk.split('\n');
    const field = key => (chunk.match(new RegExp(`^ {4,6}${key}: (.*)$`, 'm')) || [])[1];
    return {
      type: lines[0].trim(), id: field('id'), label: field('label'),
      required: /^ {6}required: true$/m.test(chunk), text: chunk,
    };
  });
}
// Fails when a form asks for coordinates/spots or lacks the privacy notice or a region-only path.
function problems(text) {
  const out = [];
  const body = items(text);
  const notice = body.find(i => i.type === 'markdown');
  if (!notice || !/do not include[^\n]*private[^\n]*(coordinates|marks|waypoints)/i.test(notice.text)
      || !/trip links/i.test(notice.text)) out.push('no privacy notice');
  const where = body.find(i => i.id === 'where');
  if (!where) out.push('no region field');
  else {
    if (!where.required) out.push('region not required');
    const ask = where.text.replace(/do not[^\n.]*\./gi, '');
    if (/coordinates|\bspot\b|waypoint/i.test(ask) || /location/i.test(where.label)) out.push('asks for location');
    if (!/approximate area/i.test(where.text) || !/synthetic example/i.test(where.text)) out.push('no safe alternative');
  }
  const required = body.filter(i => i.required && i.type !== 'checkboxes').map(i => i.id);
  if (required.join() !== 'kind,where,shown,expected') out.push(`required fields: ${required}`);
  return out;
}

test('F23-06 current data-issue form passes', () => {
  assert.deepEqual(problems(readFileSync(path, 'utf8')), []);
});

test('F23-06 negative control: the original wording is rejected', () => {
  const old = readFileSync(path, 'utf8')
    .replace(/^ +Please do not include private fishing marks.*\n/m, '')
    .replace(/label: Region\n.*description: .*\n/, 'label: Region and location\n      description: Region name and the spot, forecast point or coordinates.\n');
  const found = problems(old);
  assert.ok(found.includes('no privacy notice') && found.includes('asks for location'), found.join());
});

test('F23-06 positive control: a region plus official source is enough to submit', () => {
  const body = items(readFileSync(path, 'utf8'));
  assert.deepEqual(body.filter(i => i.required && i.type !== 'checkboxes').map(i => i.id), ['kind', 'where', 'shown', 'expected']);
  assert.match(body.find(i => i.id === 'expected').text, /official or original source/);
});
