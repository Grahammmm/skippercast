// RF1300-16: the species text get_species (`asked`) and get_strategy
// (`species_key`) echo back on an unknown species is cleaned like a label:
// whitespace folded, Cc/Cf (controls, zero-width, bidi) removed, trimmed, and
// cut at 40 UTF-16 units without a final lone high surrogate
// (server/advisor/tools/tool.ts echoText). Known species are unchanged.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createHash} from 'node:crypto';

const read = p => JSON.parse(readFileSync(new URL(p, import.meta.url)));
globalThis.REGIONS = {'morro-bay': read('../regions/morro-bay/region.json'), 'southern-california': read('../regions/southern-california/region.json')};
globalThis.DEPLOYMENT = read('../deployments/production.json');

const {TOOL_BY_NAME} = await import('../server/advisor/tools/index.ts');
const {echoText} = await import('../server/advisor/tools/tool.ts');
const {advisorSettings} = await import('../server/advisor/settings.ts');

// A fake D1 handle: get_strategy's "asked before?" lookup finds nothing.
const db = {prepare: () => ({bind: () => ({first: async () => null})})};
const ctx = () => ({env: {}, contact: {id: 'c1', role: 'angler', home_port: 'morro-bay'}, message: {id: 'in1'}, deps: {}, db,
  language: 'en', settings: advisorSettings({}), now: Date.parse('2026-09-28T19:00:00Z')});
const species = async input => (await TOOL_BY_NAME.get('get_species').run(input, ctx())).result;
const strategy = async input => (await TOOL_BY_NAME.get('get_strategy').run(input, ctx())).result;
const loneSurrogate = s => /[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/.test(s);
const digest = v => createHash('sha256').update(JSON.stringify(v)).digest('hex').slice(0, 16);

test('get_species: a bidi override, a line break, null and a missing key echo cleaned text', async () => {
  assert.deepEqual(await species({species_key: 'zz\u202etop'}), {error: 'unknown species', asked: 'zztop'});
  assert.deepEqual(await species({species_key: 'a\nb'}), {error: 'unknown species', asked: 'a b'});
  assert.deepEqual(await species({species_key: '  a \t\r\n  b  '}), {error: 'unknown species', asked: 'a b'}, 'runs fold to one space, ends trimmed');
  assert.deepEqual(await species({species_key: 'x\u0000\u0007\u200b\u200d\u2066\u202ay'}), {error: 'unknown species', asked: 'xy'});
  assert.deepEqual(await species({species_key: null}), {error: 'unknown species', asked: ''});
  assert.deepEqual(await species({}), {error: 'unknown species', asked: ''});
  assert.deepEqual(await species({species_key: 'unicorn'}), {error: 'unknown species', asked: 'unicorn'}, 'plain text is unchanged');
});

test('get_species: the 40-unit cut never leaves a lone surrogate', async () => {
  const fish = await species({species_key: 'q'.repeat(39) + '\u{1F41F}'});
  assert.equal(fish.asked, 'q'.repeat(39));
  assert.equal(fish.asked.length, 39);
  assert.ok(!loneSurrogate(fish.asked));
  const whole = await species({species_key: 'q'.repeat(38) + '\u{1F41F}'});
  assert.equal(whole.asked, 'q'.repeat(38) + '\u{1F41F}', 'a pair that fits is kept whole');
  assert.equal((await species({species_key: 'q'.repeat(60)})).asked, 'q'.repeat(40));
  const late = await species({species_key: '\u202e'.repeat(30) + 'q'.repeat(45)});
  assert.equal(late.asked, 'q'.repeat(40), 'cleaned before the cut, so removed characters do not use up the limit');
});

test('get_strategy: an unresolvable species echoes cleaned, lower-cased text', async () => {
  assert.deepEqual(await strategy({species_key: 'Mystery\u200bFish'}), {error: 'no method notes for this species', species_key: 'mysteryfish'});
  assert.deepEqual(await strategy({species_key: 'Mystery\nFish\u202e'}), {error: 'no method notes for this species', species_key: 'mystery fish'});
  assert.deepEqual(await strategy({species_key: null}), {error: 'no method notes for this species', species_key: ''});
  const cut = await strategy({species_key: 'Q'.repeat(39) + '\u{1F41F}'});
  assert.equal(cut.species_key, 'q'.repeat(39));
  assert.ok(!loneSurrogate(cut.species_key));
  assert.equal((await strategy({species_key: 'Q'.repeat(60)})).species_key, 'q'.repeat(40));
});

test('known species: both tools answer exactly as on origin/main', async () => {
  // Golden: sha256 prefix of the JSON each tool returned for lingcod on origin/main f98d95e8 with this ctx.
  const sp = await species({species_key: 'lingcod'});
  const st = await strategy({species_key: 'lingcod'});
  assert.equal(sp.species_key, 'lingcod');
  assert.equal(st.species_key, 'lingcod');
  assert.equal(digest(sp), '060232fa4de4a114', 'get_species lingcod result changed');
  assert.equal(digest(st), '3c099be77f699991', 'get_strategy lingcod result changed');
  assert.equal((await species({species_key: 'lings'})).species_key, 'lingcod', 'resolution is untouched');
  assert.equal((await strategy({species_key: 'LINGS'})).species_key, 'lingcod');
});

test('echoText: controls removed, default 40-unit limit, a smaller max', () => {
  assert.equal(echoText('\u0000'), '');
  assert.equal(echoText(undefined), '');
  assert.equal(echoText(42), '42');
  assert.equal(echoText('q'.repeat(41)), 'q'.repeat(40));
  assert.equal(echoText('q'.repeat(40)), 'q'.repeat(40));
  assert.equal(echoText('abcdefgh', 5), 'abcde');
  assert.equal(echoText('abcd\u{1F41F}', 5), 'abcd', 'max 5 drops the high half of a split pair');
  assert.equal(echoText('abc\u{1F41F}', 5), 'abc\u{1F41F}');
});
