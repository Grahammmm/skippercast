import assert from 'node:assert/strict';
import test from 'node:test';
import {advisorDatabase, sqliteUnavailable} from './_advisor_d1.mjs';

const region = 'morro-bay'; // Matches the existing home-port and slot catalogs.
const day = '2026-09-28';
const now = Date.parse(`${day}T14:05:00Z`);
globalThis.REGIONS = {[region]: {id: region, status: 'active', name: 'Fixture Coast', timezone: 'America/Los_Angeles',
  species: [], marine_zones: {coastal: 'fixture'}, daily_feed: 'daily', intelligence_feed: 'intelligence'}};
globalThis.DEPLOYMENT = {allowed_origins: []};
const {conditionsStoryId, morningStories} = await import('../server/advisor/social/stories.ts');
const {graphicState} = await import('../server/advisor/media.ts');
const feeds = async url => url === 'daily' ? {
  region_id: region, schema_version: 1, generated_at: new Date(now).toISOString(), reports: [], health: {},
  catch_probability: null, bite_score: null,
  sources: {'alerts-fixture': {data: {alerts: [{event: 'Small Craft Advisory'}]}}},
} : null;

function fixture(t) {
  const {db, sql} = advisorDatabase();
  t.after(() => sql.close());
  const env = {DB: db, ADVISOR_SOCIAL_ENABLED: 'true',
    META_APP_SECRET: 'fixture', META_PAGE_TOKEN: 'fixture', META_IG_USER_ID: 'fixture', META_PAGE_ID: 'fixture'};
  return {db, sql, run: (at = now) => morningStories(env, at, {feeds})};
}

// A failed second write used to strand an approved post: the retry saw its ID and skipped the render.
test('morning Story retries a failed graphic write and commits exactly one post and one request', {skip: sqliteUnavailable || false}, async t => {
  const {db, sql, run} = fixture(t);
  const id = await conditionsStoryId(region, day);
  const posts = () => sql.prepare('SELECT * FROM advisor_posts').all();
  const requests = () => sql.prepare("SELECT * FROM job_state WHERE key LIKE 'advisor.graphic.%'").all();
  sql.exec(`CREATE TRIGGER interrupt_graphic BEFORE INSERT ON job_state
    WHEN NEW.key LIKE 'advisor.graphic.%' BEGIN SELECT RAISE(ABORT, 'fixture interruption'); END;`);
  await assert.rejects(run(), /morning stories failed for 1 region/);
  const interrupted = posts();
  assert.deepEqual(requests(), []);
  sql.exec('DROP TRIGGER interrupt_graphic');

  await run(now + 15 * 60000);
  const graphic = await graphicState(db, id);
  assert.equal(graphic?.status, 'pending', 'same-day retry must leave a render request');
  assert.deepEqual(interrupted, [], 'failed transaction must not leave an approved post without a request');
  assert.equal(graphic.kind, 'story');
  assert.equal(graphic.out_key, `advisor/posts/${id}/story.jpg`);
  assert.match(graphic.data.lines[0], /Small Craft Advisory/i);
  const committedPosts = posts(), committedRequests = requests();
  assert.deepEqual(committedPosts.map(row => [row.id, row.status, row.scheduled_for]), [[id, 'approved', `${day}T14:00:00.000Z`]]);
  assert.equal(committedRequests.length, 1);
  assert.equal((await run(now + 30 * 60000))[0]?.status, 'exists');
  assert.deepEqual(posts(), committedPosts);
  assert.deepEqual(requests(), committedRequests);
});

// Reruns must not re-create a render for existing terminal Stories or yesterday's missed card.
test('morning Story leaves completed, rejected and prior-day Stories untouched', {skip: sqliteUnavailable || false}, async t => {
  for (const [date, status, completed] of [[day, 'posted', true], [day, 'rejected', false], ['2026-09-27', 'approved', false]]) {
    const {sql, run} = fixture(t);
    const id = await conditionsStoryId(region, date), slot = `${date}T14:00:00.000Z`;
    sql.prepare(`INSERT INTO advisor_posts(id,kind,region,media_json,caption,targets_json,status,scheduled_for,created_by,created_at,updated_at)
      VALUES(?,'story',?,'[]','','[]',?,?,'engine',?,?)`).run(id, region, status, slot, slot, slot);
    if (completed) sql.prepare('INSERT INTO job_state(key,value,updated_at) VALUES(?,?,?)')
      .run(`advisor.graphic.${id}`, JSON.stringify({kind: 'story', status: 'done', keys: {public: `advisor/posts/${id}/story.jpg`}}), slot);
    const post = () => sql.prepare('SELECT * FROM advisor_posts WHERE id=?').get(id);
    const request = () => sql.prepare('SELECT * FROM job_state WHERE key=?').get(`advisor.graphic.${id}`);
    const before = [post(), request()];
    const [outcome] = await run();
    assert.equal(outcome.status, date === day ? 'exists' : 'approved');
    assert.deepEqual([post(), request()], before, `${status} Story from ${date}`);
  }
});
