// F01-08: An ambiguous yes must not produce any action that could queue media,
// open a review, or advance the consent state. Exercise the real angler flow
// with read-only synthetic rows and an offline vision stub.
import assert from 'node:assert/strict';
import test from 'node:test';

globalThis.REGIONS = {};
globalThis.DEPLOYMENT = {allowed_origins: []};
const {anglerFlow} = await import('../server/advisor/intake/anglers.ts');

const now = Date.parse('2026-10-03T17:00:00Z');

function fixture(language, kind = 'image') {
  const media = {id: 'synthetic-photo', kind, mime: 'image/png', r2_key: 'synthetic', publish_state: 'private'};
  const identified = [];
  let offer;
  const db = {
    prepare(sql) {
      return {bind(...args) {
        if (sql.startsWith('SELECT value FROM job_state')) {
          assert.deepEqual(args, ['advisor.share.synthetic-angler']);
          return {async first() { return {value: JSON.stringify(offer)}; }};
        }
        if (sql.startsWith('SELECT id,kind,mime')) {
          assert.deepEqual(args, ['synthetic-angler', media.id]);
          return {async all() { return {results: [media]}; }};
        }
        if (sql.startsWith('SELECT credit FROM advisor_media')) return {async first() { return null; }};
        assert.fail(`Unexpected query: ${sql}`);
      }};
    },
  };
  const env = {DB: db, ADVISOR_MEDIA: {}};
  const deps = {vision: {
    async classify() { return {kind: 'deck', contains_person: false}; },
    async identifyFish(image) {
      identified.push(image.media_id);
      return {candidates: [], needs_better_photo: true, reason: 'no_fish'};
    },
  }};
  const contact = {id: 'synthetic-angler', role: 'angler', home_port: null};
  const settings = {publicBase: 'https://example.invalid', regionDefault: 'morro-bay'};
  const run = (text, carry = []) => anglerFlow({db, env, deps, contact, settings, language, now,
    text, media: text ? [] : [media.id], carry});
  return {run, identified, async open() {
    const result = await run('');
    offer = result.actions.find(action => action.type === 'share_state')?.state;
    assert.equal(offer?.step, 'offered');
    return result.actions.find(action => action.type === 'send_text')?.text;
  }};
}

function assertQueued(actions) {
  assert.deepEqual(actions.filter(action => action.type !== 'send_text'), [
    {type: 'angler_share', mediaId: 'synthetic-photo'},
    {type: 'review_open', kind: 'media', refId: 'synthetic-photo', reason: 'angler_photo'},
    {type: 'share_state', state: {step: 'credit', media_id: 'synthetic-photo', asked_at: new Date(now).toISOString()}},
  ]);
}

for (const [language, replies, clarify, share, id] of [
  ['en', ['YES', 'Sure!'], /Reply ID\b.*\bSHARE\b/, 'SHARE', 'ID'],
  ['es', ['¡SÍ!', 'Claro'], /Responde ID\b.*\bCOMPARTIR\b/, 'COMPARTIR', 'Identifícala'],
]) {
  test(`F01-08 (${language}): generic assent only asks for a choice; explicit sharing opens review`, async () => {
    const {run, open} = fixture(language);
    await open();
    for (const reply of replies) {
      const carry = [];
      const result = await run(reply, carry);
      assert.deepEqual([...carry, ...result.actions].map(action => action.type), ['send_text'],
        `${reply} may not queue the photo, open a review, or change the outstanding offer`);
      assert.match(result.actions[0].text, clarify);
    }
    assertQueued((await run(share)).actions);
  });

  test(`F01-08 (${language}): choosing identification reads the offered photo without sharing`, async () => {
    const {run, open, identified} = fixture(language);
    await open();
    const result = await run(id);
    assert.equal(result.intent, 'fishid.ask');
    assert.deepEqual(identified, ['synthetic-photo']);
    assert.deepEqual(result.actions.map(action => action.type), ['send_text']);
  });
}

test('F01-08: a video gets a share-only prompt and YES still queues review', async () => {
  const {run, open} = fixture('en', 'video');
  assert.match(await open(), /share this video.*Reply YES/);
  assertQueued((await run('YES')).actions);
});
