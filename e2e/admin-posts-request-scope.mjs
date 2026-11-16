// RF0511-9: the admin Posts list, status and Load more cursor belong to the CURRENT status/kind filters. The real PostsView is bundled in
// memory and mounted in Chromium; only fetch is replaced, by deferred synthetic responses. No network, no real posts.
import test from 'node:test';
import assert from 'node:assert/strict';
import {dirname, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {build} from 'esbuild';
import {chromium} from '@playwright/test';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const bundle = (await build({
  stdin: {contents: `import {h, render} from 'preact'; import {PostsView} from './web/admin/posts.tsx';
    window.show = () => render(h(PostsView, {}), document.getElementById('root')); window.hide = () => render(null, document.getElementById('root'));`,
  resolveDir: ROOT, loader: 'tsx'}, bundle: true, write: false, format: 'iife', jsx: 'automatic', jsxImportSource: 'preact'})).outputFiles[0].text;

const post = (id, status, over = {}) => ({id, kind: 'photo', region: 'r', status, caption: `Caption ${id}`, caption_stats: {length: 9, hashtags: 0, mentions: 0},
  targets: [], allowed_targets: [], collaborators: [], user_tags: [], scheduled_for: null, error: null, created_by: 'x', approved_by: null, approved_at: null,
  posted_at: null, created_at: '2026-11-01T12:00:00Z', updated_at: '2026-11-01T12:00:00Z', boat: null, media: [], review_id: null, hold: null,
  ig_media_id: null, fb_post_id: null, fb_story_id: null, collab_status: null, ...over});

async function mount(browser) {
  const page = await browser.newPage();
  await page.setContent('<div id="root"></div>');
  await page.evaluate(() => {
    window.pending = [];
    window.fetch = (url, init) => new Promise((resolve, reject) => window.pending.push({url: String(url), init, resolve, reject, done: false}));
    // Settle the n-th request whose URL is exactly `url`; status >= 400 answers an error.
    window.reply = (url, n, data, status = 200) => {
      const r = window.pending.filter(x => x.url === url)[n];
      if (!r || r.done) throw new Error(`no open request ${url} #${n}`);
      r.done = true;
      r.resolve(new Response(JSON.stringify(data), {status, headers: {'Content-Type': 'application/json'}}));
    };
  });
  await page.addScriptTag({content: bundle});
  await page.evaluate(() => window.show());
  const api = {
    page,
    asked: (url, n = 0) => page.waitForFunction(([u, i]) => window.pending.filter(x => x.url === u).length > i, [url, n]),
    reply: (url, n, data, status) => page.evaluate(([u, i, d, s]) => window.reply(u, i, d, s), [url, n, data, status]),
    // Let any (wrongly) admitted completion render before asserting absence.
    settle: () => page.evaluate(() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))),
    text: () => page.locator('.admin-view').textContent(),
    more: () => page.getByRole('button', {name: 'Load more', exact: true}),
    select: (i, v) => page.locator('select').nth(i).selectOption(v),
  };
  return api;
}
const q = (status, kind = '', cursor = '') => `/api/admin/posts?status=${status}${kind ? `&kind=${kind}` : ''}${cursor ? `&cursor=${cursor}` : ''}`;

async function run(fn) {
  const browser = await chromium.launch({headless: true});
  try { await fn(await mount(browser), browser); } finally { await browser.close(); }
}

test('late_first_page_cannot_supply_another_filters_cursor', () => run(async t => {
  await t.asked(q('draft'));
  await t.select(0, 'approved');
  await t.asked(q('approved'));
  await t.reply(q('approved'), 0, {posts: [], next: null});
  await t.page.getByText('No posts match.').waitFor();
  await t.reply(q('draft'), 0, {posts: [], next: 'synthetic-draft-cursor'});
  await t.settle();
  assert.equal(await t.page.locator('select').first().inputValue(), 'approved');
  assert.equal(await t.more().count(), 0, 'a draft cursor must not offer Load more under approved');
}));

test('late_first_page_cannot_replace_current_rows', () => run(async t => {
  await t.asked(q('draft'));
  await t.select(0, 'approved');
  await t.asked(q('approved'));
  await t.reply(q('approved'), 0, {posts: [post('a1', 'approved', {caption: 'Approved synthetic card'})], next: null});
  await t.page.getByText('Approved synthetic card').waitFor();
  await t.reply(q('draft'), 0, {posts: [post('d1', 'draft', {caption: 'Draft synthetic card'})], next: null});
  await t.settle();
  assert.ok((await t.text()).includes('Approved synthetic card'));
  assert.ok(!(await t.text()).includes('Draft synthetic card'), 'stale rows must not appear');
}));

test('late_failure_cannot_fail_successful_current_filter', () => run(async t => {
  await t.asked(q('draft'));
  await t.select(0, 'approved');
  await t.asked(q('approved'));
  await t.reply(q('approved'), 0, {posts: [post('a1', 'approved', {caption: 'Approved synthetic card'})], next: 'approved-cursor'});
  await t.page.getByText('Approved synthetic card').waitFor();
  await t.reply(q('draft'), 0, {error: 'x'}, 500);
  await t.settle();
  assert.equal(await t.page.getByRole('alert').filter({hasText: 'Could not load'}).count(), 0, 'old failure must not fail the current filter');
  assert.ok((await t.text()).includes('Approved synthetic card'));
  assert.equal(await t.more().count(), 1);
  // Reverse: the current filter fails, then the old one succeeds late: the failure stays.
  await t.select(0, 'posted');
  await t.asked(q('posted'));
  await t.select(0, 'scheduled');
  await t.asked(q('scheduled'));
  await t.reply(q('scheduled'), 0, {error: 'x'}, 500);
  await t.page.getByRole('alert').filter({hasText: 'Could not load'}).waitFor();
  await t.reply(q('posted'), 0, {posts: [], next: null});
  await t.settle();
  assert.equal(await t.page.getByRole('alert').filter({hasText: 'Could not load'}).count(), 1);
}));

test('kind_changes_and_aba_do_not_readmit_old_responses', () => run(async t => {
  await t.asked(q('draft'));
  await t.select(1, 'story');           // draft+story
  await t.asked(q('draft', 'story'));
  await t.select(1, '');                // draft again, a newer generation
  await t.asked(q('draft'), 1);
  await t.reply(q('draft'), 1, {posts: [post('n', 'draft', {caption: 'Newest synthetic card'})], next: null});
  await t.page.getByText('Newest synthetic card').waitFor();
  await t.reply(q('draft', 'story'), 0, {posts: [post('s', 'draft', {caption: 'Story synthetic card'})], next: 'story-cursor'});
  await t.reply(q('draft'), 0, {posts: [post('o', 'draft', {caption: 'Oldest synthetic card'})], next: 'oldest-cursor'});
  await t.settle();
  assert.ok((await t.text()).includes('Newest synthetic card'));
  assert.ok(!/Oldest synthetic|Story synthetic/.test(await t.text()));
  assert.equal(await t.more().count(), 0);
  // Status ABA: draft -> approved -> draft; the first draft request settles last.
  await t.select(0, 'approved');
  await t.asked(q('approved'));
  await t.select(0, 'draft');
  await t.asked(q('draft'), 2);
  await t.reply(q('draft'), 2, {posts: [], next: null});
  await t.page.getByText('No posts match.').waitFor();
  await t.reply(q('approved'), 0, {posts: [post('a', 'approved', {caption: 'Approved synthetic card'})], next: 'approved-cursor'});
  await t.settle();
  assert.ok(!(await t.text()).includes('Approved synthetic card'));
  assert.equal(await t.more().count(), 0);
}));

test('old_pagination_cannot_append_or_replace_next_after_filter_change', () => run(async t => {
  await t.asked(q('draft'));
  await t.reply(q('draft'), 0, {posts: [post('d1', 'draft', {caption: 'Draft one'})], next: 'draft-cursor'});
  await t.more().click();
  await t.asked(q('draft', '', 'draft-cursor'));
  await t.select(0, 'approved');
  await t.asked(q('approved'));
  await t.reply(q('approved'), 0, {posts: [post('a1', 'approved', {caption: 'Approved one'})], next: 'approved-cursor'});
  await t.page.getByText('Approved one').waitFor();
  await t.reply(q('draft', '', 'draft-cursor'), 0, {posts: [post('d2', 'draft', {caption: 'Draft two'})], next: 'draft-cursor-2'});
  await t.settle();
  assert.ok(!(await t.text()).includes('Draft two'));
  await t.more().click();
  await t.asked(q('approved', '', 'approved-cursor'));
  assert.equal(await t.page.evaluate(() => window.pending.some(x => x.url.includes('draft-cursor-2'))), false);
}));

test('current_first_page_more_and_refresh_keep_working', () => run(async t => {
  await t.asked(q('draft'));
  await t.reply(q('draft'), 0, {posts: [post('d1', 'draft', {caption: 'Draft one'})], next: 'c1'});
  await t.more().click();
  await t.asked(q('draft', '', 'c1'));
  await t.reply(q('draft', '', 'c1'), 0, {posts: [post('d2', 'draft', {caption: 'Draft two'})], next: null});
  await t.page.getByText('Draft two').waitFor();
  assert.ok((await t.text()).includes('Draft one'), 'the next page appends');
  assert.equal(await t.more().count(), 0);
  await t.select(0, 'approved');
  await t.asked(q('approved'));
  await t.reply(q('approved'), 0, {error: 'x'}, 500);
  await t.page.getByRole('alert').filter({hasText: 'Could not load'}).waitFor();
  // The independent calendar keeps its own request and is not remounted by a filter change.
  assert.equal(await t.page.evaluate(() => window.pending.filter(x => x.url.startsWith('/api/admin/posts/calendar')).length) >= 1, true);
}));

test('abandoned_decision_cannot_publish_after_filter_round_trip', () => run(async t => {
  await t.asked(q('draft'));
  await t.reply(q('draft'), 0, {posts: [post('d1', 'draft', {review_id: 'rv1'})], next: null});
  await t.page.getByRole('button', {name: 'Approve', exact: true}).click();
  await t.asked('/api/admin/reviews/rv1');
  await t.select(0, 'approved');
  await t.asked(q('approved'));
  await t.select(0, 'draft');
  await t.asked(q('draft'), 1);
  await t.reply('/api/admin/reviews/rv1', 0, {review: {id: 'rv1', status: 'approved'}});
  await t.settle();
  assert.equal(await t.page.locator('.admin-view > .admin-notice').textContent(), '', 'no abandoned approval notice');
  assert.equal(await t.page.evaluate(() => window.pending.filter(x => x.url === '/api/admin/posts?status=draft').length), 2, 'no abandoned reload superseding the current request');
  await t.reply(q('draft'), 1, {posts: [post('d2', 'draft', {caption: 'Current draft'})], next: 'current-cursor'});
  await t.page.getByText('Current draft', {exact: true}).waitFor();
  assert.equal(await t.more().count(), 1, 'the current request still owns its cursor');
  // A decision started in this generation still refreshes and announces success.
  await t.select(0, 'approved');
  await t.asked(q('approved'), 1);
  await t.select(0, 'draft');
  await t.asked(q('draft'), 2);
  await t.reply(q('draft'), 2, {posts: [post('d3', 'draft', {review_id: 'rv3'})], next: null});
  await t.page.getByRole('button', {name: 'Approve', exact: true}).click();
  await t.asked('/api/admin/reviews/rv3');
  await t.reply('/api/admin/reviews/rv3', 0, {review: {id: 'rv3', status: 'approved'}});
  await t.asked(q('draft'), 3);
  assert.equal(await t.page.locator('.admin-view > .admin-notice').textContent(), 'Marked approved.');
}));

test('abandoned_change_cannot_publish_after_filter_round_trip', () => run(async t => {
  await t.asked(q('draft'));
  await t.select(0, 'approved');
  await t.asked(q('approved'));
  await t.reply(q('approved'), 0, {posts: [post('a1', 'approved', {caption: 'Original caption'})], next: null});
  await t.page.locator('input[type="datetime-local"]').fill('2026-12-01T12:00');
  await t.page.getByRole('button', {name: 'Save time', exact: true}).click();
  await t.asked('/api/admin/posts/a1/schedule');
  await t.select(1, 'story');
  await t.asked(q('approved', 'story'));
  await t.select(1, '');
  await t.asked(q('approved'), 1);
  await t.reply(q('approved'), 1, {posts: [post('a1', 'approved', {caption: 'Current caption'})], next: 'current-cursor'});
  await t.page.getByText('Current caption', {exact: true}).waitFor();
  await t.reply('/api/admin/posts/a1/schedule', 0, {post: post('a1', 'scheduled', {caption: 'Abandoned caption'})});
  await t.settle();
  assert.equal(await t.page.locator('.admin-view > .admin-notice').textContent(), '', 'no abandoned change notice');
  assert.ok((await t.text()).includes('Current caption'));
  assert.ok(!(await t.text()).includes('Abandoned caption'));
  assert.equal(await t.more().count(), 1);
  // The current generation may still change the row and announce it.
  await t.page.locator('input[type="datetime-local"]').fill('2026-12-02T12:00');
  await t.page.getByRole('button', {name: 'Save time', exact: true}).click();
  await t.asked('/api/admin/posts/a1/schedule', 1);
  await t.reply('/api/admin/posts/a1/schedule', 1, {post: post('a1', 'scheduled', {caption: 'Current saved caption'})});
  await t.page.getByText('Current saved caption', {exact: true}).waitFor();
  assert.notEqual(await t.page.locator('.admin-view > .admin-notice').textContent(), '');
}));

test('abandoned_list_callback_and_unmount_do_not_publish', () => run(async t => {
  await t.asked(q('draft'));
  await t.reply(q('draft'), 0, {posts: [post('d1', 'draft', {caption: 'Draft one', review_id: 'rv1'})], next: null});
  await t.page.getByText('Draft one').waitFor();
  await t.page.getByRole('button', {name: 'Approve', exact: true}).click();
  await t.asked('/api/admin/reviews/rv1');
  await t.select(0, 'approved');
  await t.asked(q('approved'));
  await t.reply(q('approved'), 0, {posts: [post('a1', 'approved', {caption: 'Approved one'})], next: null});
  await t.page.getByText('Approved one').waitFor();
  await t.reply('/api/admin/reviews/rv1', 0, {review: {id: 'rv1', status: 'approved'}});
  await t.settle();
  assert.equal(await t.page.locator('.admin-notice[role="status"]').first().textContent().then(s => s.trim()), '', 'no abandoned notice');
  assert.equal(await t.page.evaluate(() => window.pending.filter(x => x.url.startsWith('/api/admin/posts?')).length), 2, 'no old-filter reload');
  // Unmount with a request outstanding: settling it publishes nothing and throws nothing.
  await t.select(0, 'posted');
  await t.asked(q('posted'));
  const errors = [];
  t.page.on('pageerror', e => errors.push(e));
  await t.page.evaluate(() => window.hide());
  await t.reply(q('posted'), 0, {posts: [post('p1', 'posted')], next: 'x'});
  await t.settle();
  assert.equal(await t.page.locator('.admin-view').count(), 0);
  assert.deepEqual(errors, []);
}));
