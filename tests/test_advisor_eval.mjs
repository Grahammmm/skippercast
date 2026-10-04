// The opt-in live eval (scripts/advisor/eval.mjs; 11 § launch checklist): offline
// checks only. It never calls the model here: the argument parser, the three
// judges against the recorded outputs and against bad ones, and the refusal to
// run without ANTHROPIC_API_KEY.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {parseArgs, judge, judgeDaily, judgeCaption, DAILY_CASES, CAPTION_CASES, SUITES} from '../scripts/advisor/eval.mjs';

const read = p => JSON.parse(readFileSync(new URL(p, import.meta.url)));
const script = fileURLToPath(new URL('../scripts/advisor/eval.mjs', import.meta.url));

test('parseArgs: suites, case, model; unknown options and suites fail', () => {
  assert.deepEqual(SUITES, ['system', 'daily', 'caption']);
  assert.deepEqual(parseArgs([]), {only: null, model: null, suite: null, help: false});
  assert.deepEqual(parseArgs(['--suite', 'daily', '--case', 'daily-landing-only', '--model', 'm']), {only: 'daily-landing-only', model: 'm', suite: 'daily', help: false});
  assert.throws(() => parseArgs(['--suite', 'everything']), /unknown suite/);
  assert.throws(() => parseArgs(['--fast']), /unknown option/);
});

test('judge (system): length, markdown, a refusal that is not one, banned text', () => {
  const fixture = {expect: {intent: 'refused', reply_not_contains: ['%']}};
  assert.deepEqual(judge(fixture, 'Only fishing questions here.', 'refused'), []);
  assert.deepEqual(judge(fixture, `**${'x'.repeat(480)} 50%`, 'chat'), ['over 480 characters (486)', 'markdown or an unresolved placeholder', 'intent chat, expected refused', 'contains "%"']);
});

test('judgeDaily: the recorded answers pass their own case; odds, an unverified boat, a rejected text and length are flagged', () => {
  for (const spec of DAILY_CASES) {
    const raw = read(`./fixtures/advisor/daily/${spec.fixture}.json`).response.body.content[0].input;
    assert.deepEqual(judgeDaily(spec, raw, {source: 'model', text_en: raw.en, text_es: raw.es}), [], spec.name);
  }
  const spec = DAILY_CASES[0];
  const bad = {en: `Morro Bay: Example Boat Two says 80% chance. ${'x'.repeat(400)}`, es: 'Hola'};
  const problems = judgeDaily(spec, bad, {source: 'composed', text_en: 'a', text_es: 'b'});
  assert.ok(problems.some(p => p.startsWith('stored source composed')));
  assert.ok(problems.some(p => p.startsWith('en: ') && p.includes('over 420')));
  assert.ok(problems.includes('en: odds or a percentage'));
  assert.ok(problems.includes('en: names "Example Boat Two" (unverified or absent)'));
  assert.ok(problems.includes('es: does not start with the port name'));
  assert.ok(problems.includes('en: missing "Example Boat One"'));
  assert.deepEqual(judgeDaily(spec, null, null).slice(0, 2), ['no record_daily_answer tool input', 'stored source -: the live text was rejected and the composed fallback used']);
});

test('judgeCaption: the recorded line passes; an invented number, a tag, a followed note, English in Spanish and an invented fish are flagged', () => {
  const [boat, es, reel] = CAPTION_CASES;
  assert.deepEqual(judgeCaption(boat, boat.recorded, {source: 'model'}), []);
  assert.deepEqual(judgeCaption(boat, 'Limits for 30 anglers #fishing', {source: 'fixed'}),
    ['source fixed: the live line was rejected and the fixed line used', 'a hashtag, mention or link', 'invents the number 30', 'followed the note\'s instructions']);
  assert.deepEqual(judgeCaption(es, 'Buen vermilion en un día tranquilo.', {source: 'model'}), []);
  assert.deepEqual(judgeCaption(es, 'Good vermilion on a calm day and this one came up.', {source: 'model'}), ['English words in the Spanish line']);
  assert.deepEqual(judgeCaption(reel, 'Lings on the rail all morning.', {source: 'model'}), ['names a fish the facts do not']);
  assert.ok(judgeCaption(boat, 'x'.repeat(151), {source: 'model'}).includes('151 characters, over 150'));
});

test('without ANTHROPIC_API_KEY the script refuses to run (exit 1) and calls nothing', () => {
  const env = {...process.env}; delete env.ANTHROPIC_API_KEY;
  const r = spawnSync(process.execPath, [script, '--suite', 'daily'], {env, encoding: 'utf8'});
  assert.equal(r.status, 1);
  assert.match(r.stderr, /ANTHROPIC_API_KEY is not set/);
});
