// RF1300-5: update_profile names the target species it could not map to a
// species key (unknown_targets: cleaned strings, input order, de-duplicated,
// at most 8, each at most 40 code points) while still saving the known ones;
// `rejected` keeps its meaning (a field with nothing saved).
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

const read = p => JSON.parse(readFileSync(new URL(p, import.meta.url)));
globalThis.REGIONS = {'morro-bay': read('../regions/morro-bay/region.json'), 'southern-california': read('../regions/southern-california/region.json')};
globalThis.DEPLOYMENT = read('../deployments/production.json');

const {TOOL_BY_NAME} = await import('../server/advisor/tools/index.ts');
const tool = TOOL_BY_NAME.get('update_profile');
const run = input => tool.run(input, {contact: {id: 'c1', role: 'angler'}, language: 'en', now: 0});

test('mixed: known targets are saved and the unknown one is named', async () => {
  assert.deepEqual(await run({targets: ['Lingcod', 'unicorn', 'california-halibut']}), {
    result: {saved: ['targets'], rejected: [], unknown_targets: ['unicorn']},
    actions: [{type: 'contact_update', fields: {targets_json: '["lingcod","halibut"]'}}]});
});

test('all unknown: no action, targets rejected and every unknown named (trimmed, lower case)', async () => {
  assert.deepEqual(await run({targets: ['unicorn', 'Dragon ']}), {
    result: {saved: [], rejected: ['targets'], unknown_targets: ['unicorn', 'dragon']}, actions: []});
});

test('all known: no unknown_targets key at all', async () => {
  const out = await run({targets: ['lingcod']});
  assert.equal('unknown_targets' in out.result, false);
  assert.deepEqual(out, {result: {saved: ['targets'], rejected: []}, actions: [{type: 'contact_update', fields: {targets_json: '["lingcod"]'}}]});
});

test('duplicates: the same unknown target (any case or spacing) is named once', async () => {
  assert.deepEqual((await run({targets: ['unicorn', 'Unicorn ', 'unicorn']})).result.unknown_targets, ['unicorn']);
  assert.deepEqual((await run({targets: [5, null, '   ', '']})).result.unknown_targets, ['(not text)', '(blank)'], 'placeholders are de-duplicated too');
});

test('not text and blank entries get placeholders; nothing saved', async () => {
  assert.deepEqual(await run({targets: [5, '   ']}), {
    result: {saved: [], rejected: ['targets'], unknown_targets: ['(not text)', '(blank)']}, actions: []});
  assert.deepEqual((await run({targets: ['\u0007\u0000']})).result.unknown_targets, ['(blank)'], 'control characters only is blank');
});

test('bounds: at most 8 entries in input order, 40 code points each, control characters removed', async () => {
  const many = Array.from({length: 12}, (_, i) => `beast${i}`);
  assert.deepEqual((await run({targets: many})).result.unknown_targets, many.slice(0, 8));
  const long = (await run({targets: ['x'.repeat(100)]})).result.unknown_targets;
  assert.deepEqual(long, ['x'.repeat(40)]);
  const emoji = (await run({targets: ['🐟'.repeat(50)]})).result.unknown_targets[0];
  assert.equal([...emoji].length, 40, 'cut by code points, not UTF-16 units');
  assert.deepEqual((await run({targets: ['uni\u0007corn']})).result.unknown_targets, ['unicorn']);
  assert.deepEqual((await run({targets: ['uni\u009bcorn\u007f']})).result.unknown_targets, ['unicorn'], 'C1 and DEL removed too');
});

test('bounds: unknown entries do not displace known ones, and known ones keep their own cap', async () => {
  const out = await run({targets: [...Array.from({length: 9}, (_, i) => `beast${i}`), 'lingcod']});
  assert.deepEqual(out.result, {saved: ['targets'], rejected: [], unknown_targets: Array.from({length: 8}, (_, i) => `beast${i}`)});
  assert.deepEqual(out.actions[0].fields, {targets_json: '["lingcod"]'});
});

test('non-array targets: rejected as before, no unknown_targets', async () => {
  const out = await run({targets: 'lingcod'});
  assert.deepEqual(out, {result: {saved: [], rejected: ['targets']}, actions: []});
  assert.equal('unknown_targets' in out.result, false);
  assert.deepEqual(await run({targets: []}), {result: {saved: [], rejected: ['targets']}, actions: []}, 'empty array: nothing to name');
});

test('other fields untouched: home_port alone returns exactly saved/rejected', async () => {
  assert.deepEqual(await run({home_port: 'morro-bay'}), {result: {saved: ['home_port'], rejected: []}, actions: [{type: 'contact_update', fields: {home_port: 'morro-bay'}}]});
  assert.deepEqual(await run({home_port: 'atlantis'}), {result: {saved: [], rejected: ['home_port']}, actions: []});
});

test('the tool description tells the model to ask about unknown_targets', () => {
  assert.match(tool.description, /If unknown_targets is returned, ask what they meant by those\.$/);
});
