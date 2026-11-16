// RF0452-6: a datetime-local text naming no clock time in the browser zone (DST gap) is unreadable,
// not silently shifted. Each zone runs in its own child process (TZ scoped per child).
import test from 'node:test';
import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';

const SELF = fileURLToPath(import.meta.url);

if (process.env.RF0452_6_CHILD) {
  const {postEdits, fromLocalInput} = await import('../web/admin/posts-form.ts');
  const post = {kind: 'photo', caption: 'A', targets: ['instagram'], allowed_targets: ['instagram', 'facebook'],
    collaborators: [], user_tags: [], scheduled_for: null};
  const form = {caption: 'B', targets: ['instagram'], collaborators: '', tags: '', schedule: ''};
  const texts = ['2026-03-08T01:59', '2026-03-08T02:00', '2026-03-08T02:30', '2026-03-08T02:59:59.250', '2026-03-08T03:00',
    '2026-03-08T03:00:00.1', '2026-03-08T03:00:00.12', '2026-03-08T03:00:00.123', '2026-11-01T01:30', '2026-02-30T10:00', 'garbage', ''];
  const out = {};
  for (const t of texts) {
    const patch = {scheduled: postEdits({...post, scheduled_for: '2026-01-01T00:00:00.000Z'}, {...form, schedule: t}),
      unscheduled: postEdits(post, {...form, schedule: t})};
    out[t] = {iso: fromLocalInput(t) ?? null, undef: fromLocalInput(t) === undefined,
      hasSchedule: 'scheduled_for' in patch.scheduled, hasScheduleU: 'scheduled_for' in patch.unscheduled, caption: patch.scheduled.caption};
  }
  process.stdout.write(JSON.stringify(out));
} else {
  const run = (tz) => {
    const r = spawnSync(process.execPath, [SELF], {env: {...process.env, TZ: tz, RF0452_6_CHILD: '1'}, encoding: 'utf8'});
    assert.equal(r.status, 0, r.stderr);
    return JSON.parse(r.stdout);
  };

  test('America/Los_Angeles: spring-gap times are unreadable and produce no schedule patch', () => {
    const o = run('America/Los_Angeles');
    for (const t of ['2026-03-08T02:00', '2026-03-08T02:30', '2026-03-08T02:59:59.250']) {
      assert.equal(o[t].undef, true, t);
      assert.equal(o[t].hasSchedule, false, t);
      assert.equal(o[t].hasScheduleU, false, t);
      assert.equal(o[t].caption, 'B', 'caption edit still present');
    }
  });

  test('America/Los_Angeles: valid neighbours, fractions, fall overlap and malformed input keep their behaviour', () => {
    const o = run('America/Los_Angeles');
    assert.equal(o['2026-03-08T01:59'].iso, '2026-03-08T09:59:00.000Z');
    assert.equal(o['2026-03-08T03:00'].iso, '2026-03-08T10:00:00.000Z');
    assert.equal(o['2026-03-08T03:00:00.1'].iso, '2026-03-08T10:00:00.100Z');
    assert.equal(o['2026-03-08T03:00:00.12'].iso, '2026-03-08T10:00:00.120Z');
    assert.equal(o['2026-03-08T03:00:00.123'].iso, '2026-03-08T10:00:00.123Z');
    assert.equal(o['2026-11-01T01:30'].iso, '2026-11-01T08:30:00.000Z', 'earlier occurrence');
    assert.equal(o['2026-03-08T03:00'].hasSchedule, true);
    assert.equal(o['2026-02-30T10:00'].undef, true);
    assert.equal(o['garbage'].undef, true);
    assert.equal(o[''].iso, null);
    assert.equal(o[''].hasSchedule, true, 'blank clears');
  });

  test('UTC: the same 02:30 civil time is valid', () => {
    const o = run('UTC');
    assert.equal(o['2026-03-08T02:30'].iso, '2026-03-08T02:30:00.000Z');
    assert.equal(o['2026-03-08T02:59:59.250'].iso, '2026-03-08T02:59:59.250Z');
  });
}
