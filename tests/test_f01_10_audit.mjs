// F01-10: a successful tool call alone cannot ground a numeric regulation.
import test from 'node:test';
import assert from 'node:assert/strict';
import {advisorDatabase, sqliteUnavailable} from './_advisor_d1.mjs';

globalThis.REGIONS = {
  'morro-bay': {name: 'Morro Bay', jurisdiction_id: 'california-central'},
  'southern-california': {name: 'Southern California', jurisdiction_id: 'california-southern'},
};
globalThis.DEPLOYMENT = {public_origin: 'https://advisor.example'};
globalThis.SHELLS = {};
globalThis.BUILD_ID = 'fixture';
const {runTurn} = await import('../server/advisor/engine.ts');
const now = Date.parse('2026-10-04T17:00:00Z');
const base = 'https://advisor.example';

for (const scenario of [
  {name: 'empty lookup', rows: [], input: {species_key: 'lingcod'}, seen: [], allowed: false},
  {name: 'nonempty lookup for the wrong species', rows: [['halibut']], input: {species_key: 'halibut'}, seen: ['halibut'], allowed: false},
  {name: 'nonempty lookup for the wrong region', rows: [['lingcod', 'southern-california']], input: {species_key: 'lingcod', region: 'southern-california'}, seen: ['lingcod'], allowed: false},
  {name: 'matching current row', rows: [['lingcod']], input: {species_key: 'lings'}, seen: ['lingcod'], allowed: true},
  {name: 'matching row for an explicitly named region', rows: [['lingcod', 'southern-california']], input: {species_key: 'lingcod', region: 'southern-california'}, place: ' in Southern California', seen: ['lingcod'], allowed: true},
  {name: 'matching row with a numeric claim about a different fish', rows: [['lingcod']], input: {species_key: 'lingcod'}, subject: 'Halibut', seen: ['lingcod'], allowed: false},
]) {
  test(`F01-10: ${scenario.name}`, {skip: sqliteUnavailable || false}, async t => {
    const {sql, db} = advisorDatabase();
    t.after(() => sql.close());
    const seed = sql.prepare(`INSERT INTO advisor_rules
      (id, region, jurisdiction, species_key, species_label, size_min_in, source_name, source_url,
       reviewed_at, review_due, status, updated_by, updated_at)
      VALUES (?, ?, ?, ?, ?, 17, 'Fixture rules', 'https://rules.example', ?, '2026-12-31', 'active', 'fixture', ?)`);
    for (const [species, region = 'morro-bay'] of scenario.rows) {
      seed.run(`${species}:${region}`, region, REGIONS[region].jurisdiction_id, species, species,
        '2026-10-01T00:00:00Z', '2026-10-01T00:00:00Z');
    }
    const quote = `${scenario.subject ?? 'Lingcod'} must be at least 17 inches (Fixture rules; checked Oct 1).`;
    const requests = [];
    const responses = [
      {stop_reason: 'tool_use', content: [{type: 'tool_use', name: 'get_rules', id: 'rule-test', input: scenario.input}]},
      {stop_reason: 'end_turn', content: [{type: 'text', text: `${quote} Ask before you go.`}]},
    ];
    const fetcher = async (_url, init) => {
      requests.push(JSON.parse(init.body));
      return Response.json(responses.shift());
    };
    const result = await runTurn({
      env: {DB: db, ANTHROPIC_API_KEY: 'fixture-only', ADVISOR_PUBLIC_BASE: base},
      contact: {id: 'fixture-contact', role: 'angler', channel: 'web', web_session: 'fixture', status: 'active', language: 'en'},
      message: {id: 'fixture-message', channel: 'web', body: `What size lingcod can I keep${scenario.place ?? ''}?`, created_at: new Date(now).toISOString()},
      now, deps: {fetcher, clock: () => now},
    });
    assert.equal(requests.length, 2);
    const recorded = requests[1].messages.at(-1).content[0];
    assert.equal(recorded.tool_use_id, 'rule-test');
    assert.equal(recorded.is_error, undefined);
    const rules = JSON.parse(recorded.content).rules;
    assert.deepEqual(rules.map(row => row.species_key), scenario.seen);
    for (const row of rules) assert.deepEqual([row.size_min_in, row.stale], [17, false]);

    const reply = result.actions.find(action => action.type === 'send_text')?.text;
    const reviews = result.actions.filter(action => action.type === 'review_open');
    if (scenario.allowed) {
      assert.equal(reply, `${quote} Ask before you go.`);
      assert.deepEqual(reviews, []);
    } else {
      assert.match(reply, /Check the current CDFW rules/);
      assert.ok(reply.includes(`${base}/?s=txt#species-regulations`));
      assert.ok(reply.includes('Ask before you go.'));
      assert.doesNotMatch(reply, /17 inches/);
      assert.deepEqual(reviews.map(action => action.reason), ['rules_without_tool']);
    }
  });
}
