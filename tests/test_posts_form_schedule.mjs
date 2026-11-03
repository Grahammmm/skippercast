// RF1050-2: the post editor's schedule text (web/admin/posts-form.ts). Empty
// text clears the schedule; text that is not a datetime-local value
// (YYYY-MM-DDTHH:MM[:SS[.sss]]) or names no such day is unreadable and leaves
// the schedule as it is (no scheduled_for in the patch). Expectations are built
// with new Date(y, m, d, h, mi) so they hold in any zone (CI runs
// TZ=America/Los_Angeles as well as UTC).
import test from 'node:test';
import assert from 'node:assert/strict';

const {postEdits, fromLocalInput} = await import('../web/admin/posts-form.ts');

const at = new Date(2026, 10, 1, 9, 15).toISOString();
const post = {kind: 'photo', caption: 'A', targets: ['instagram'], allowed_targets: ['instagram', 'facebook'], collaborators: [],
  user_tags: [], scheduled_for: at};
const form = {caption: 'A', targets: ['instagram'], collaborators: '', tags: '', schedule: ''};
const UNREADABLE = ['garbage', '1', '2026-11-02', '2026-02-30T10:00', '2026-11-02 10:00', '2026-11-02T10:00Z',
  '2026-11-02T10:00:00+01:00', '2026-13-01T10:00', '2026-11-31T10:00', '+02026-11-02T10:00', ' 2026-11-02T10:00'];

test('fromLocalInput reads only the datetime-local shape: empty is null, unreadable is undefined', () => {
  assert.equal(fromLocalInput(''), null);
  for (const text of UNREADABLE) assert.equal(fromLocalInput(text), undefined, text);
  assert.equal(fromLocalInput('2026-11-03T07:30'), new Date(2026, 10, 3, 7, 30).toISOString());
  assert.equal(fromLocalInput('2026-11-03T07:30:45'), new Date(2026, 10, 3, 7, 30, 45).toISOString());
  assert.equal(fromLocalInput('2026-11-03T07:30:45.250'), new Date(2026, 10, 3, 7, 30, 45, 250).toISOString());
  assert.equal(fromLocalInput('2028-02-29T23:59'), new Date(2028, 1, 29, 23, 59).toISOString(), 'a leap day is a real day');
});

test('a scheduled post with unreadable schedule text keeps its schedule (no scheduled_for)', () => {
  for (const schedule of UNREADABLE) assert.equal('scheduled_for' in postEdits(post, {...form, schedule}), false, schedule);
  assert.equal('scheduled_for' in postEdits({...post, scheduled_for: null}, {...form, schedule: 'garbage'}), false, 'unscheduled stays unscheduled');
});

test('empty schedule text still clears a scheduled post', () => {
  assert.deepEqual(postEdits(post, form), {scheduled_for: null});
  assert.deepEqual(postEdits({...post, scheduled_for: null}, form), {}, 'already unscheduled: nothing to clear');
});

test('a readable time schedules an unscheduled post at that local time', () => {
  assert.deepEqual(postEdits({...post, scheduled_for: null}, {...form, schedule: '2026-11-03T07:30'}),
    {scheduled_for: new Date(2026, 10, 3, 7, 30).toISOString()});
  assert.deepEqual(postEdits(post, {...form, schedule: '2026-11-03T07:30'}), {scheduled_for: new Date(2026, 10, 3, 7, 30).toISOString()}, 'a move');
});

test('the same minute as before (seconds differ) is no change', () => {
  const withSeconds = {...post, scheduled_for: new Date(2026, 10, 1, 9, 15, 40).toISOString()};
  assert.deepEqual(postEdits(withSeconds, {...form, schedule: '2026-11-01T09:15'}), {});
  assert.deepEqual(postEdits(post, {...form, schedule: '2026-11-01T09:15:59'}), {});
});

test('other edits still reach the patch when the schedule text is unreadable', () => {
  const edited = {...form, caption: 'B', targets: ['instagram', 'facebook'], collaborators: '@Deckhand.Example', tags: 'deckhand.example'};
  for (const schedule of ['garbage', '1', '2026-02-30T10:00']) {
    assert.deepEqual(postEdits(post, {...edited, schedule}), {caption: 'B', targets: ['instagram', 'facebook'], collaborators: ['deckhand.example'],
      user_tags: [{username: 'deckhand.example', x: 0.5, y: 0.5}]}, schedule);
  }
});
