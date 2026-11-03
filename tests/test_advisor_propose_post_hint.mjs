// propose_post's hint (RF1300-15; server/advisor/tools/propose_post.ts): the
// skipper's words reach the caption line with whitespace folded to one space,
// control, zero-width and bidi characters removed, and the 200-unit cut made on
// a whole code point (never half an emoji). A hint that is empty after
// cleaning sends no `hint`; a non-string hint sends none either. Offline: real
// migrations in node:sqlite, one consenting verified boat, synthetic photos.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {advisorDatabase, sqliteUnavailable} from './_advisor_d1.mjs';

const read = p => JSON.parse(readFileSync(new URL(p, import.meta.url)));
globalThis.REGIONS = {'morro-bay': read('../regions/morro-bay/region.json')};
globalThis.DEPLOYMENT = read('../deployments/production.json');
const {proposePost, cleanHint} = await import('../server/advisor/tools/propose_post.ts');
const {advisorSettings} = await import('../server/advisor/settings.ts');

const dbTest = (name, fn) => test(name, {skip: sqliteUnavailable || false}, fn);
const T0 = Date.parse('2026-10-04T18:00:00Z');
const DAY = 86400000;
const iso = ms => new Date(ms).toISOString();
const LONE_HIGH = /[\uD800-\uDBFF](?![\uDC00-\uDFFF])/;

/** One skipper (c1) on a verified boat (b1) with active photo consent; `media(id, state)` adds one of their photos. */
function setup() {
  const {sql, db} = advisorDatabase();
  sql.prepare(`INSERT INTO advisor_contacts(id,phone_hash,phone_enc,channel,role,language,boat_id,status,last_seen_at,created_at,updated_at) VALUES('c1','h-c1','ENC-c1','imessage','skipper','en','b1','active',?,?,?)`)
    .run(iso(T0 - DAY), iso(T0 - DAY), iso(T0 - DAY));
  sql.prepare(`INSERT INTO advisor_boats(id,slug,name,port,region,instagram,owner_contact_id,status,consent_photos_at,consent_revoked_at,created_at,updated_at) VALUES('b1','sea-example','Sea Example','morro-bay','morro-bay','seaexample','c1','verified',?,NULL,?,?)`)
    .run(iso(T0 - 2 * DAY), iso(T0 - 30 * DAY), iso(T0 - 30 * DAY));
  const env = {TEXT_ADVISOR_ENABLED: 'true', DB: db, ADVISOR_NUMBER: '+180****0100'};
  const media = (id, state = 'private') => sql.prepare(`INSERT INTO advisor_media(id,contact_id,boat_id,kind,mime,bytes,r2_key,sha256,exif_stripped,classification_json,has_person,publish_state,credit,created_at) VALUES(?,'c1','b1','image','image/jpeg',1000,?,'sha',1,NULL,0,?,'Sea Example',?)`)
    .run(id, `advisor/media/c1/${id}.jpg`, state, iso(T0));
  const ctx = () => ({env, contact: sql.prepare("SELECT * FROM advisor_contacts WHERE id='c1'").get(), message: {id: 'in-tool', created_at: iso(T0)}, deps: {}, db,
    language: 'en', settings: advisorSettings(env), now: T0});
  let n = 0;
  /** Runs propose_post on a fresh photo in `state` with `hint`; returns the result and its one action. */
  const run = async (hint, state = 'private') => {
    const id = `m${++n}`;
    media(id, state);
    const out = await proposePost.run(hint === undefined ? {media_id: id} : {media_id: id, hint}, ctx());
    assert.equal(out.actions.length, 1, 'one action (no review: the photo is not classified)');
    return {out, action: out.actions[0], id};
  };
  return {run};
}

dbTest('control, zero-width and bidi characters are dropped from the hint on the media_queue action', async () => {
  const {run} = setup();
  for (const [raw, want] of [['big\u202eling', 'bigling'], ['lingcod\u200b 28 in', 'lingcod 28 in'], ['a\u0007b', 'ab'],
    ['\u2066rock\u2069fish \u202a\u202d\u2067\u2068', 'rockfish'], ['nul\u0000 \u0085c1\u0009\u2060\ufeffok', 'nul c1 ok'], ['\ufeff\u200bhalibut  \u200b  32', 'halibut 32']]) {
    const {out, action, id} = await run(raw);
    assert.equal(out.result.drafted, true, JSON.stringify(raw));
    assert.deepEqual(action, {type: 'media_queue', mediaId: id, hint: want}, JSON.stringify(raw));
    assert.doesNotMatch(action.hint, /[\p{Cc}\p{Cf}]/u, JSON.stringify(raw));
  }
});

dbTest('spaces, tabs and line breaks still fold to one space', async () => {
  const {run} = setup();
  assert.equal((await run('two\n\nlines\tand  tabs')).action.hint, 'two lines and tabs');
  assert.equal((await run('  \r\n lead and trail \t ')).action.hint, 'lead and trail');
});

dbTest('the 200-unit cut never leaves half of an emoji', async () => {
  const {run} = setup();
  const straddle = (await run('a'.repeat(199) + '🐟')).action.hint;
  assert.equal(straddle.length, 199);
  assert.equal(straddle, 'a'.repeat(199));
  assert.doesNotMatch(straddle, LONE_HIGH);
  // An emoji that fits whole stays; emoji past the cut go whole too.
  const fits = (await run('a'.repeat(198) + '🐟🐟')).action.hint;
  assert.equal(fits, 'a'.repeat(198) + '🐟');
  assert.doesNotMatch(fits, LONE_HIGH);
  // Characters removed before the cut do not count toward it.
  assert.equal((await run('\u200b'.repeat(50) + 'b'.repeat(200))).action.hint, 'b'.repeat(200));
  for (let k = 190; k <= 201; k++) assert.doesNotMatch(cleanHint('c'.repeat(k) + '🐟'.repeat(10)), LONE_HIGH, String(k));
});

dbTest('a hint that is empty after cleaning sends no hint; the photo is still drafted', async () => {
  const {run} = setup();
  for (const raw of ['\u200b\u2066 ', '\u0007\u202e', '']) {
    const {out, action, id} = await run(raw);
    assert.equal(out.result.drafted, true, JSON.stringify(raw));
    assert.deepEqual(action, {type: 'media_queue', mediaId: id}, JSON.stringify(raw));
    assert.ok(!('hint' in action), JSON.stringify(raw));
  }
});

dbTest('a plain 200-character hint is unchanged; a queued photo gets the same cleaned hint on post_draft', async () => {
  const {run} = setup();
  const plain = 'Lingcod 28 in, calm seas! '.repeat(8).slice(0, 200);
  assert.equal(plain.length, 200);
  assert.equal((await run(plain)).action.hint, plain);
  const queued = await run('first\u200b ling\u202e of the\nday', 'queued');
  assert.deepEqual(queued.action, {type: 'post_draft', mediaId: queued.id, hint: 'first ling of the day'});
  const queuedLong = await run('d'.repeat(199) + '🐟', 'queued');
  assert.equal(queuedLong.action.type, 'post_draft');
  assert.equal(queuedLong.action.hint, 'd'.repeat(199));
  const queuedEmpty = await run('\u2066\u2069', 'queued');
  assert.deepEqual(queuedEmpty.action, {type: 'post_draft', mediaId: queuedEmpty.id});
});

dbTest('a non-string or missing hint sends no hint (unchanged)', async () => {
  const {run} = setup();
  for (const raw of [42, null, ['big ling'], {text: 'x'}, undefined]) {
    const {out, action, id} = await run(raw);
    assert.equal(out.result.drafted, true, String(raw));
    assert.deepEqual(action, {type: 'media_queue', mediaId: id}, String(raw));
  }
});
