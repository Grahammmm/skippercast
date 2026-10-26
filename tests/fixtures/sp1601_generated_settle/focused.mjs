export function registerFocused({test, assert, product, scenario, fixtures, NOW, guard}) {
  const atAge = age => ({run_id: 'synthetic-boundary', generated_at: new Date(NOW - age).toISOString()});
  for (const [label, age, action] of [
    ['minus one', product.SETTLE_MS - 1, 'settling'],
    ['exactly', product.SETTLE_MS, 'enqueued'],
    ['plus one', product.SETTLE_MS + 1, 'enqueued'],
    ['future', -1, 'settling'],
  ]) test(`A2 ${label}`, async t => {
    const s = scenario(t), feed = atAge(age);
    const result = await s.run(feed);
    assert.equal(result.action, action);
    if (action === 'settling') {
      assert.deepEqual(s.queries, []);
      assert.deepEqual(s.messages, []);
    } else {
      assert.equal(result.owners, 1);
      assert.equal(s.messages.length, 1);
      assert.equal((await s.run(feed)).action, 'unchanged');
      assert.equal(s.messages.length, 1);
    }
  });

  const recent = fixtures.recent.generated_at, old = fixtures.old.generated_at;
  for (const [label, feed, action, marker] of [
    ['published recent overrides old completed/generated', {published_at: recent, completed_at: old, generated_at: old}, 'settling', old],
    ['published old overrides recent completed/generated', {published_at: old, completed_at: recent, generated_at: recent}, 'enqueued', recent],
    ['completed recent overrides old generated', {completed_at: recent, generated_at: old}, 'settling', recent],
    ['completed old overrides recent generated', {completed_at: old, generated_at: recent}, 'enqueued', old],
    ['empty published/completed uses generated', {published_at: '', completed_at: '', generated_at: recent}, 'settling', recent],
  ]) test(`A3 ${label}`, async t => {
    const s = scenario(t), result = await s.run({run_id: 'synthetic-precedence', ...feed});
    assert.equal(result.action, action);
    // Publication identity deliberately remains completed_at then generated_at.
    assert.equal(result.publication, `synthetic-precedence@${marker}`);
    assert.equal(s.messages.length, action === 'enqueued' ? 1 : 0);
    if (action === 'settling') assert.deepEqual(s.queries, []);
  });

  for (const [label, feed] of [
    ['null', null], ['absent', {}], ['invalid generated', {generated_at: 'invalid'}],
    ['invalid completed stays invalid', {completed_at: 'invalid', generated_at: recent}],
    ['published only has no publication identity', {published_at: recent}],
  ]) test(`A3 no-feed ${label}`, async t => {
    const s = scenario(t);
    assert.deepEqual(await s.run(feed), {action: 'no-feed'});
    assert.deepEqual(s.queries, []);
    assert.deepEqual(s.messages, []);
  });

  test('A4 unchanged publication', async t => {
    const publication = product.publicationMarker(fixtures.old);
    const s = scenario(t, {previous: publication});
    assert.deepEqual(await s.run(fixtures.old), {action: 'unchanged', publication});
    assert.equal(s.state(), publication);
    assert.equal(s.queries.length, 1);
    assert.deepEqual(s.messages, []);
  });
  for (const absent of ['TRIP_QUEUE', 'DB']) test(`A4 absent ${absent}`, async t => {
    const s = scenario(t);
    delete s.env[absent];
    assert.deepEqual(await s.run(fixtures.old), {action: absent === 'DB' ? 'no-db' : 'no-queue'});
    assert.deepEqual(s.queries, []);
    assert.deepEqual(s.messages, []);
  });
  for (const previous of [null, 'synthetic-previous@publication']) test(`A4 failed send restores ${previous === null ? 'absent claim' : 'previous claim'}`, async t => {
    const s = scenario(t, {previous, failSend: true});
    const saved = console.error, logs = [];
    console.error = (...args) => logs.push(args);
    let result;
    try { result = await s.run(fixtures.old); } finally { console.error = saved; }
    assert.deepEqual(result, {action: 'enqueue-failed', publication: product.publicationMarker(fixtures.old)});
    assert.equal(s.state(), previous);
    assert.equal(logs.length, 1);
    assert.deepEqual(s.messages, []);
    // The same real module can retry after the synthetic producer recovers.
    s.env.TRIP_QUEUE = {async sendBatch(messages) { s.messages.push(...messages); }};
    assert.equal((await s.run(fixtures.old)).action, 'enqueued');
    assert.equal(s.messages.length, 1);
  });
  test('A4 implicit feed reader is intercepted before network', async t => {
    const s = scenario(t);
    // The sentinel throws synchronously before fetch returns a promise, so the
    // real default reader rejects rather than treating this as an HTTP outage.
    await assert.rejects(product.scheduleTripChecks(s.env, NOW), /SP1601 offline sentinel: fetch\/network\/model/);
    assert.deepEqual(guard.attempts.splice(0), ['fetch/network/model']);
    assert.deepEqual(s.queries, []);
    assert.deepEqual(s.messages, []);
  });
}
