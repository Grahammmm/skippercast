// Text Advisor vision (server/advisor/vision/, TA-V1; docs/plans/text-advisor/07-vision.md):
// forced-tool parsing into each result type, field validation, the thresholds
// table as pure decide* functions, the provider chain (cache in
// advisor_media.classification_json, has_person, 10-minute skip after a failure
// and recovery, hermes skipped while not configured), the Claude provider
// (request shape, global daily cap, 429 retry, HEIC and size errors, the llm
// analytics point), the catalog files and the synthetic fixture images.
// Offline: a fake fetcher answers with the recorded responses in
// tests/fixtures/advisor/vision/, against the real migrations.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync, readdirSync, statSync} from 'node:fs';
import {advisorDatabase, sqliteUnavailable} from './_advisor_d1.mjs';

const read = p => JSON.parse(readFileSync(new URL(p, import.meta.url)));
globalThis.REGIONS = {'morro-bay': read('../regions/morro-bay/region.json'), 'southern-california': read('../regions/southern-california/region.json')};
globalThis.DEPLOYMENT = read('../deployments/production.json');
const vision = await import('../server/advisor/vision/index.ts');
const claude = await import('../server/advisor/vision/claude.ts');
const species = await import('../server/advisor/vision/species.ts');
const prompts = await import('../server/advisor/prompts/vision.ts');
const images = await import('../scripts/advisor/make-fixture-images.mjs');
const {visionChain, THRESHOLDS, MediaTooLarge, UnsupportedImage, VisionCapReached, VisionUnavailable, downKey,
  decideCountBoard, decideReadingUsable, decideAcceptReading, decideHold, decideFishBand, decideProtected} = vision;
const {parseClassification, parseCountBoard, parseFishId, createClaudeVision} = claude;

const dbTest = (name, fn) => test(name, {skip: sqliteUnavailable || false}, fn);
const T0 = Date.parse('2026-10-03T15:00:00Z');
const fixture = name => read(`./fixtures/advisor/vision/${name}`);
const png = name => readFileSync(new URL(`./fixtures/advisor/vision/images/${name}`, import.meta.url));
const META = {provider: 'claude', model: 'm', ms: 5};
const toolInput = name => fixture(name).content.find(b => b.type === 'tool_use').input;
const quiet = async fn => { const saved = {log: console.log, warn: console.warn, error: console.error}, lines = []; console.log = console.warn = console.error = (...a) => lines.push(a.join(' ')); try { return {value: await fn(), lines}; } finally { Object.assign(console, saved); } };

/** An image input over real bytes (or a fake length) with a counter of reads. */
function imageOf(bytes, {id = 'm1', mime = 'image/png', size} = {}) {
  const input = {media_id: id, mime, reads: 0, bytes: async () => { input.reads++; return size ? new ArrayBuffer(size) : new Uint8Array(bytes).buffer; }};
  return input;
}
/** A fake Messages API: answers with fixtures by tool name (or a function), recording each request. */
function fakeApi(answers) {
  const calls = [];
  const fetcher = async (url, init) => {
    const body = JSON.parse(init.body); calls.push({url, init, body});
    const answer = typeof answers === 'function' ? answers(body, calls.length) : answers[body.tool_choice.name];
    if (answer instanceof Response) return answer;
    return new Response(JSON.stringify(answer), {status: 200, headers: {'content-type': 'application/json'}});
  };
  return {fetcher, calls};
}
const ANSWERS = {record_classification: fixture('classify-count-board.json'), record_count_board: fixture('count-board.json'), record_fish_id: fixture('fish-id.json')};
function analytics() { const points = []; return {points, writeDataPoint: p => points.push(p)}; }
function setup(vars = {}) {
  const {sql, db} = advisorDatabase();
  sql.prepare("INSERT INTO advisor_media(id,contact_id,kind,mime,bytes,r2_key,sha256,created_at) VALUES('m1','c1','image','image/png',100,'advisor/media/c1/m1.png','x',?)").run(new Date(T0).toISOString());
  const env = {DB: db, ANTHROPIC_API_KEY: 'k', ANALYTICS: analytics(), ADVISOR_VISION_PROVIDERS: 'claude', ...vars};
  return {sql, env};
}

// ---- Parsing and validation ------------------------------------------------------

test('forced-tool output parses into a Classification, a CountBoardReading and a FishId', () => {
  const c = parseClassification(toolInput('classify-count-board.json'), META);
  assert.deepEqual(c, {kind: 'count_board', kind_confidence: 0.94, has_person: false, person_confidence: 0.02, has_fish: false, text_present: true, nsfw: false, ...META});
  const r = parseCountBoard(toolInput('count-board.json'), META);
  assert.equal(r.boat_name, 'Rita G'); assert.equal(r.date_text, '10/03'); assert.equal(r.date_iso, null); assert.equal(r.anglers, 22);
  assert.deepEqual(r.lines[1], {label: 'Lingcod', count: 12, released: 2, confidence: 0.9});
  assert.equal(r.lines.length, 4); assert.equal(r.overall_confidence, 0.87); assert.equal(r.provider, 'claude');
  const f = parseFishId(toolInput('fish-id.json'), new Set(['vermilion', 'canary', 'yelloweye']), META);
  assert.deepEqual(f.candidates.map(x => x.species_key), ['vermilion', 'canary', 'yelloweye']);
  assert.equal(f.needs_better_photo, false); assert.equal(f.reason, null); assert.equal(f.model, 'm');
});

test('validation clamps confidences, nulls unknown species keys (label kept), trims to 3 candidates sorted desc', () => {
  const f = parseFishId(toolInput('fish-id-invalid.json'), new Set(['vermilion', 'canary', 'yelloweye']), META);
  assert.equal(f.candidates.length, 3);
  assert.deepEqual(f.candidates.map(c => c.confidence), [1, 0.4, 0.3], 'clamped to 0..1 and sorted');
  assert.deepEqual(f.candidates[1], {species_key: null, label: 'Red snapper', confidence: 0.4, cues: ['red body', 'red fins', 'big eye']}, 'bad key -> null, label kept, cues max 3');
  assert.ok(!f.candidates.some(c => c.label === 'Canary rockfish'), 'the lowest (clamped to 0) is trimmed');
  assert.equal(f.needs_better_photo, false, 'a non-boolean flag is false');
  assert.equal(f.reason, null, 'a reason that is not a short code is dropped');
  const c = parseClassification({kind: 'selfie', kind_confidence: '0.9', has_person: 'true', person_confidence: 3, nsfw: 1}, META);
  assert.deepEqual([c.kind, c.kind_confidence, c.has_person, c.person_confidence, c.nsfw], ['unknown', 0, false, 1, false]);
  const r = parseCountBoard({date_iso: '2026-02-30', anglers: -1, date_confidence: NaN, lines: [{label: '  ', count: 3}, {label: 'Reds', count: '12', released: 1.5, confidence: 2}, 'junk']}, META);
  assert.equal(r.date_iso, null); assert.equal(r.anglers, null); assert.equal(r.date_confidence, 0);
  assert.deepEqual(r.lines, [{label: 'Reds', count: 12, released: null, confidence: 1}]);
  const none = parseFishId({candidates: []}, new Set(), META);
  assert.deepEqual([none.needs_better_photo, none.reason], [true, 'no_fish']);
});

// ---- Thresholds ---------------------------------------------------------------------

test('THRESHOLDS holds the 07 table and the decide* functions apply it', () => {
  assert.deepEqual({...THRESHOLDS}, {countBoardKind: 0.6, readingUsable: 0.5, acceptOverall: 0.8, acceptLine: 0.7, holdPerson: 0.5, fishHigh: 0.85, fishMedium: 0.6,
    protectedWarning: 0.3, maxImageBytes: 4.5 * 1024 * 1024, providerDownMs: 600000});
  assert.ok(Object.isFrozen(THRESHOLDS));
  // route to count-board reading
  assert.equal(decideCountBoard({kind: 'count_board', kind_confidence: 0.6, text_present: false}), true);
  assert.equal(decideCountBoard({kind: 'count_board', kind_confidence: 0.59, text_present: false}), false);
  assert.equal(decideCountBoard({kind: 'scenery', kind_confidence: 0.4, text_present: true}), true, 'text and a low-confidence kind: try it');
  assert.equal(decideCountBoard({kind: 'document', kind_confidence: 0.9, text_present: true}), false);
  assert.equal(decideReadingUsable({overall_confidence: 0.5}), true); assert.equal(decideReadingUsable({overall_confidence: 0.49}), false);
  // accept a reading without asking
  const line = (confidence, count = 1) => ({label: 'x', count, released: null, confidence});
  assert.deepEqual(decideAcceptReading({overall_confidence: 0.8, lines: [line(0.7), line(0.9)]}), {accept: true, uncertain: []});
  assert.deepEqual(decideAcceptReading({overall_confidence: 0.79, lines: [line(0.9)]}), {accept: false, uncertain: []});
  assert.deepEqual(decideAcceptReading({overall_confidence: 0.95, lines: [line(0.9), line(0.69), line(0.9, null)]}), {accept: false, uncertain: [1, 2]});
  assert.equal(decideAcceptReading({overall_confidence: 0.95, lines: []}).accept, false, 'nothing read: ask');
  // hold for human
  assert.equal(decideHold({has_person: true, person_confidence: 0.5, nsfw: false}), true);
  assert.equal(decideHold({has_person: true, person_confidence: 0.49, nsfw: false}), false);
  assert.equal(decideHold({has_person: false, person_confidence: 0.9, nsfw: false}), false);
  assert.equal(decideHold({has_person: false, person_confidence: 0, nsfw: true}), true);
  // fish-ID bands
  const fish = (confidence, needs = false) => ({candidates: confidence === null ? [] : [{species_key: 'lingcod', label: 'Lingcod', confidence, cues: []}], needs_better_photo: needs});
  assert.equal(decideFishBand(fish(0.85)), 'high'); assert.equal(decideFishBand(fish(0.84)), 'medium');
  assert.equal(decideFishBand(fish(0.6)), 'medium'); assert.equal(decideFishBand(fish(0.59)), 'ask');
  assert.equal(decideFishBand(fish(0.95, true)), 'ask'); assert.equal(decideFishBand(fish(null)), 'ask');
  // protected-species warning
  const cands = (...c) => ({candidates: c.map(([species_key, confidence]) => ({species_key, label: species_key ?? 'x', confidence, cues: []}))});
  assert.deepEqual(decideProtected(cands(['vermilion', 0.6], ['yelloweye', 0.3])).map(p => p.key), ['yelloweye']);
  assert.deepEqual(decideProtected(cands(['vermilion', 0.6], ['yelloweye', 0.29])), []);
  assert.deepEqual(decideProtected(cands(['cowcod', 0.5], ['canary', 0.4], [null, 0.9])).map(p => p.key), ['cowcod', 'canary']);
  assert.equal(decideProtected(cands(['canary', 0.9]))[0].must_release, false, 'canary is a sub-bag species');
});

// ---- Claude provider ------------------------------------------------------------------

dbTest('the Claude provider sends one forced-tool request per method with the image as base64', async () => {
  const {env} = setup({ADVISOR_VISION_MODEL: 'claude-test-1'});
  const api = fakeApi(ANSWERS), provider = createClaudeVision({fetcher: api.fetcher});
  const bytes = png('count-board.png');
  const {value: c} = await quiet(() => provider.classify(imageOf(bytes), env));
  assert.equal(c.kind, 'count_board'); assert.equal(c.model, 'claude-test-1'); assert.equal(c.provider, 'claude'); assert.ok(c.ms >= 0);
  const {url, init, body} = api.calls[0];
  assert.equal(url, 'https://api.anthropic.com/v1/messages');
  assert.equal(init.headers['anthropic-version'], '2023-06-01'); assert.equal(init.headers['x-api-key'], 'k');
  assert.ok(init.signal instanceof AbortSignal);
  assert.equal(body.model, 'claude-test-1'); assert.equal(body.max_tokens, 600); assert.equal(body.temperature, 0);
  assert.deepEqual(body.tool_choice, {type: 'tool', name: 'record_classification'});
  assert.equal(body.tools.length, 1); assert.equal(body.tools[0].input_schema.type, 'object');
  const [image, text] = body.messages[0].content;
  assert.deepEqual(image, {type: 'image', source: {type: 'base64', media_type: 'image/png', data: bytes.toString('base64')}});
  assert.match(text.text, /count board is a whiteboard|count_board: a whiteboard/);
  await quiet(() => provider.readCountBoard(imageOf(bytes), env));
  const {value: f} = await quiet(() => provider.identifyFish(imageOf(png('fish.png')), env, 'morro-bay'));
  assert.equal(api.calls.length, 3);
  assert.deepEqual(api.calls.map(c => c.body.tool_choice.name), ['record_classification', 'record_count_board', 'record_fish_id']);
  const keys = api.calls[2].body.tools[0].input_schema.properties.candidates.items.properties.species_key.enum;
  assert.ok(keys.includes('vermilion') && keys.includes('lingcod') && keys.includes('dungeness') && keys.includes(null));
  assert.ok(!keys.includes('yellowtail') && !keys.includes('lobster'), 'only the region\'s species');
  assert.match(api.calls[2].body.messages[0].content[1].text, /- yelloweye: Yelloweye rockfish — bright yellow eye/);
  assert.equal(f.candidates[0].species_key, 'vermilion');
});

dbTest('usage goes to an llm analytics point with feature advisor:vision:<method>', async () => {
  const {env} = setup({ADVISOR_VISION_MODEL: 'claude-test-1'});
  const provider = createClaudeVision({fetcher: fakeApi(ANSWERS).fetcher});
  const {lines} = await quiet(() => provider.classify(imageOf(png('count-board.png')), env));
  const point = env.ANALYTICS.points[0];
  assert.deepEqual(point.indexes, ['llm']);
  assert.deepEqual(point.blobs, ['llm', 'advisor:vision:classify', 'ok', 'claude-test-1']);
  assert.deepEqual(point.doubles, [1650, 120, 0, 1]);
  const log = JSON.parse(lines.find(l => l.includes('advisor_vision_call')));
  assert.deepEqual([log.method, log.outcome, log.input_tokens, log.output_tokens], ['classify', 'ok', 1650, 120]);
  assert.ok(!lines.join('').includes('m1'), 'no media id in the log line');
  await quiet(() => provider.identifyFish(imageOf(png('fish.png')), env, 'morro-bay'));
  assert.equal(env.ANALYTICS.points[1].blobs[1], 'advisor:vision:fish_id');
  const failing = createClaudeVision({fetcher: async () => new Response('{}', {status: 500})});
  await quiet(() => assert.rejects(failing.readCountBoard(imageOf(png('count-board.png')), env), /HTTP 500/));
  assert.deepEqual(env.ANALYTICS.points[2].blobs.slice(1, 3), ['advisor:vision:count_board', 'error']);
});

dbTest('HTTP 429 or 529 is retried once after 2 s; a second failure or any other status fails', async () => {
  const {env} = setup();
  const sleeps = [];
  let api = fakeApi((body, n) => n === 1 ? new Response('busy', {status: 429}) : ANSWERS[body.tool_choice.name]);
  let provider = createClaudeVision({fetcher: api.fetcher, sleep: async ms => { sleeps.push(ms); }});
  const {value} = await quiet(() => provider.classify(imageOf(png('blank.png')), env));
  assert.equal(value.kind, 'count_board'); assert.equal(api.calls.length, 2); assert.deepEqual(sleeps, [2000]);
  assert.equal(env.ANALYTICS.points[0].doubles[3], 2, 'two turns recorded');
  api = fakeApi(() => new Response('overloaded', {status: 529}));
  provider = createClaudeVision({fetcher: api.fetcher, sleep: async () => {}});
  await quiet(() => assert.rejects(provider.classify(imageOf(png('blank.png')), env), /HTTP 529/));
  assert.equal(api.calls.length, 2, 'one retry only');
  api = fakeApi(() => new Response('bad', {status: 400}));
  provider = createClaudeVision({fetcher: api.fetcher, sleep: async () => { throw Error('no sleep for 400'); }});
  await quiet(() => assert.rejects(provider.classify(imageOf(png('blank.png')), env), /HTTP 400/));
  assert.equal(api.calls.length, 1);
});

dbTest('a response without the forced tool_use block fails as invalid', async () => {
  const {env} = setup();
  const provider = createClaudeVision({fetcher: fakeApi(() => ({content: [{type: 'text', text: '{"kind":"fish"}'}], usage: {input_tokens: 10, output_tokens: 5}})).fetcher});
  await quiet(() => assert.rejects(provider.classify(imageOf(png('blank.png')), env), /no tool input/));
  assert.equal(env.ANALYTICS.points[0].blobs[2], 'invalid');
});

dbTest('HEIC throws UnsupportedImage before any request', async () => {
  const {sql, env} = setup();
  const api = fakeApi(ANSWERS), provider = createClaudeVision({fetcher: api.fetcher});
  await assert.rejects(provider.classify(imageOf(png('blank.png'), {mime: 'image/heic'}), env), UnsupportedImage);
  // Through the chain: an input error, so the provider is not marked down.
  await assert.rejects(visionChain(env, {fetcher: api.fetcher}).classify(imageOf(png('blank.png'), {mime: 'image/heif'})), UnsupportedImage);
  assert.equal(api.calls.length, 0);
  assert.equal(sql.prepare('SELECT count(*) n FROM job_state').get().n, 0);
});

dbTest('the global daily cap ADVISOR_GLOBAL_DAILY_VISION counts in request_limits and stops at the limit', async () => {
  const {sql, env} = setup({ADVISOR_GLOBAL_DAILY_VISION: '2'});
  const api = fakeApi(ANSWERS), provider = createClaudeVision({fetcher: api.fetcher, now: () => T0});
  await quiet(() => provider.classify(imageOf(png('blank.png')), env));
  await quiet(() => provider.readCountBoard(imageOf(png('blank.png')), env));
  const {lines} = await quiet(() => assert.rejects(provider.classify(imageOf(png('blank.png')), env), VisionCapReached));
  assert.equal(api.calls.length, 2, 'no request past the cap');
  assert.ok(lines.some(l => l.includes('advisor_vision_global_cap')));
  const day = Math.floor(T0 / 86400000);
  assert.deepEqual({...sql.prepare('SELECT id,count,expires_at FROM request_limits').get()}, {id: `global:vision:${day}`, count: 3, expires_at: (day + 2) * 86400});
  // The next day starts again.
  const tomorrow = createClaudeVision({fetcher: api.fetcher, now: () => T0 + 86400000});
  await quiet(() => tomorrow.classify(imageOf(png('blank.png')), env));
  assert.equal(api.calls.length, 3);
  // Through the chain: the cap is not a provider fault (no down mark), and it is what the caller sees.
  await quiet(() => assert.rejects(visionChain(env, {fetcher: api.fetcher, now: () => T0}).classify(imageOf(png('blank.png'), {id: 'm1'})), VisionCapReached));
  assert.equal(sql.prepare("SELECT count(*) n FROM job_state WHERE key LIKE 'advisor.vision.%'").get().n, 0);
});

// ---- Chain ---------------------------------------------------------------------------

dbTest('the chain caches each method in classification_json and sets has_person; a cache hit makes no call', async () => {
  const {sql, env} = setup();
  const api = fakeApi(body => body.tool_choice.name === 'record_classification' ? fixture('classify-deck-person.json') : ANSWERS[body.tool_choice.name]);
  const chain = visionChain(env, {fetcher: api.fetcher});
  const image = imageOf(png('deck-person.png'));
  const {value: first} = await quiet(() => chain.classify(image));
  assert.equal(first.has_person, true);
  let row = sql.prepare("SELECT classification_json,has_person FROM advisor_media WHERE id='m1'").get();
  assert.equal(row.has_person, 1);
  assert.deepEqual(Object.keys(JSON.parse(row.classification_json)), ['classify']);
  const {value: again} = await quiet(() => visionChain(env, {fetcher: api.fetcher}).classify(imageOf(png('deck-person.png'))));
  assert.deepEqual(again, first); assert.equal(api.calls.length, 1, 'cache hit: no provider call');
  await quiet(() => chain.readCountBoard(image)); await quiet(() => chain.identifyFish(image, 'morro-bay'));
  row = sql.prepare("SELECT classification_json FROM advisor_media WHERE id='m1'").get();
  assert.deepEqual(Object.keys(JSON.parse(row.classification_json)).sort(), ['classify', 'count_board', 'fish_id'], 'keyed by method, earlier results kept');
  assert.equal(JSON.parse(row.classification_json).count_board.boat_name, 'Rita G');
  assert.equal(api.calls.length, 3);
  await quiet(() => chain.readCountBoard(image)); assert.equal(api.calls.length, 3);
  // A corrupt cache value is ignored and replaced.
  sql.prepare("UPDATE advisor_media SET classification_json='not json' WHERE id='m1'").run();
  await quiet(() => chain.classify(image)); assert.equal(api.calls.length, 4);
  assert.deepEqual(Object.keys(JSON.parse(sql.prepare("SELECT classification_json FROM advisor_media WHERE id='m1'").get().classification_json)), ['classify']);
});

dbTest('an original over 4.5 MB throws MediaTooLarge without a provider call', async () => {
  const {env} = setup();
  const api = fakeApi(ANSWERS);
  const big = imageOf(null, {size: THRESHOLDS.maxImageBytes + 1, mime: 'image/jpeg'});
  const {lines} = await quiet(() => assert.rejects(visionChain(env, {fetcher: api.fetcher}).classify(big), err => err instanceof MediaTooLarge && err.bytes === THRESHOLDS.maxImageBytes + 1));
  assert.equal(api.calls.length, 0);
  assert.ok(lines.some(l => JSON.parse(l).event === 'advisor_vision_too_large'));
  const edge = imageOf(null, {size: THRESHOLDS.maxImageBytes, mime: 'image/jpeg'});
  await quiet(() => visionChain(env, {fetcher: api.fetcher}).classify(edge));
  assert.equal(api.calls.length, 1, 'exactly 4.5 MB is sent');
});

dbTest('a failed provider is skipped for 10 minutes, then tried again and cleared on success', async () => {
  const {sql, env} = setup({ADVISOR_VISION_PROVIDERS: 'claude'});
  let clock = T0, fail = true;
  const api = fakeApi(body => fail ? new Response('down', {status: 500}) : ANSWERS[body.tool_choice.name]);
  const deps = {fetcher: api.fetcher, now: () => clock};
  await quiet(() => assert.rejects(visionChain(env, deps).classify(imageOf(png('blank.png'))), VisionUnavailable));
  assert.equal(api.calls.length, 1);
  const state = sql.prepare('SELECT value FROM job_state WHERE key=?').get(downKey('claude'));
  assert.equal(state.value, new Date(T0 + 600000).toISOString());
  fail = false; clock = T0 + 9 * 60000;
  await quiet(() => assert.rejects(visionChain(env, deps).classify(imageOf(png('blank.png'))), /claude: down/));
  assert.equal(api.calls.length, 1, 'still inside the 10 minutes: no call');
  clock = T0 + 10 * 60000 + 1;
  const {value, lines} = await quiet(() => visionChain(env, deps).classify(imageOf(png('blank.png'))));
  assert.equal(value.kind, 'count_board'); assert.equal(api.calls.length, 2);
  assert.equal(sql.prepare('SELECT value FROM job_state WHERE key=?').get(downKey('claude')), undefined, 'recovery clears the mark');
  assert.ok(lines.some(l => l.includes('advisor_vision_provider_up')));
});

dbTest('the chain tries providers in order and falls through a failing one to the next', async () => {
  const {sql, env} = setup({ADVISOR_VISION_PROVIDERS: 'hermes,claude', HERMES_VISION_URL: 'https://hermes.test'});
  const order = [];
  const hermes = {name: 'hermes', classify: async () => { order.push('hermes'); throw Error('tunnel down'); }, readCountBoard: async () => { order.push('hermes'); return {...parseCountBoard(toolInput('count-board.json'), {provider: 'hermes', model: 'local', ms: 1})}; },
    identifyFish: async () => { throw Error('x'); }, health: async () => ({ok: true, detail: ''})};
  const api = fakeApi(ANSWERS);
  const chain = visionChain(env, {fetcher: api.fetcher, providers: {hermes}, now: () => T0});
  const {value} = await quiet(() => chain.classify(imageOf(png('blank.png'))));
  assert.deepEqual(order, ['hermes']); assert.equal(value.provider, 'claude'); assert.equal(api.calls.length, 1);
  assert.ok(sql.prepare('SELECT value FROM job_state WHERE key=?').get(downKey('hermes')), 'hermes marked down');
  const {value: board} = await quiet(() => chain.readCountBoard(imageOf(png('blank.png'))));
  assert.equal(board.provider, 'claude', 'hermes skipped while down'); assert.deepEqual(order, ['hermes']);
});

dbTest('an unconfigured hermes (no HERMES_VISION_URL) is skipped silently; the stub reports not-configured', async () => {
  const {sql, env} = setup({ADVISOR_VISION_PROVIDERS: 'hermes,claude'});
  const api = fakeApi(ANSWERS);
  const {value, lines} = await quiet(() => visionChain(env, {fetcher: api.fetcher}).classify(imageOf(png('blank.png'))));
  assert.equal(value.provider, 'claude');
  assert.ok(!lines.some(l => l.includes('hermes')), 'nothing logged about hermes');
  assert.equal(sql.prepare('SELECT count(*) n FROM job_state').get().n, 0);
  assert.deepEqual(await vision.hermesStub.health(env), {ok: false, detail: 'not-configured'});
  // Even with a URL set, the TA-V1 stub is not-configured, not a failure.
  const withUrl = {...env, HERMES_VISION_URL: 'https://hermes.test'};
  await quiet(() => visionChain(withUrl, {fetcher: api.fetcher}).readCountBoard(imageOf(png('blank.png'))));
  assert.equal(sql.prepare('SELECT count(*) n FROM job_state').get().n, 0);
  // Claude without a key: not configured, no down mark, VisionUnavailable.
  const noKey = {...env, ANTHROPIC_API_KEY: undefined, ADVISOR_VISION_PROVIDERS: 'claude'};
  sql.prepare("UPDATE advisor_media SET classification_json=NULL WHERE id='m1'").run();
  await quiet(() => assert.rejects(visionChain(noKey, {fetcher: api.fetcher}).classify(imageOf(png('blank.png'))), /claude: not-configured/));
  assert.equal(sql.prepare('SELECT count(*) n FROM job_state').get().n, 0);
});

dbTest('the image bytes are read once per chain call, whatever the number of providers', async () => {
  const {env} = setup({ADVISOR_VISION_PROVIDERS: 'hermes,claude', HERMES_VISION_URL: 'https://h'});
  const hermes = {...vision.hermesStub, classify: async image => { await image.bytes(); throw Error('down'); }};
  const image = imageOf(png('blank.png'));
  await quiet(() => visionChain(env, {fetcher: fakeApi(ANSWERS).fetcher, providers: {hermes}}).classify(image));
  assert.equal(image.reads, 1);
});

// ---- Catalog, prompts and fixtures -------------------------------------------------------

test('species-extra, lookalikes and protected reference known keys and sources', () => {
  const catalogKeys = new Set(read('../catalog/species.json').species.map(s => s.id));
  const extra = read('../catalog/advisor/species-extra.json').species;
  const required = ['vermilion', 'canary', 'yelloweye', 'cowcod', 'copper', 'bocaccio', 'chilipepper', 'black', 'blue', 'gopher', 'cabezon', 'kelp-greenling',
    'white-seabass', 'california-halibut', 'pacific-halibut', 'king-salmon', 'albacore', 'bluefin', 'yellowtail', 'dungeness'];
  const known = new Set([...catalogKeys, ...extra.map(e => e.key)]);
  for (const k of required) assert.ok(known.has(k), k);
  for (const e of extra) {
    assert.ok(!catalogKeys.has(e.key), `${e.key} duplicates a catalog key`);
    assert.ok(e.parent === null ? typeof e.target === 'string' : catalogKeys.has(e.parent), `${e.key} parent`);
  }
  const looks = read('../catalog/advisor/lookalikes.json').species;
  for (const k of required) assert.ok(looks[k], `lookalikes for ${k}`);
  for (const [k, v] of Object.entries(looks)) {
    assert.ok(known.has(k), k);
    assert.ok(v.cues.length >= 2 && v.cues.length <= 3, `${k} has 2-3 cues`);
    for (const l of v.lookalikes) assert.ok(known.has(l), `${k} -> ${l}`);
    assert.match(v.source, /^https:\/\/(?:wildlife\.ca\.gov|www\.fisheries\.noaa\.gov)\//, k);
  }
  const prot = read('../catalog/advisor/protected.json').species;
  assert.deepEqual(prot.map(p => p.key).sort(), ['bronzespotted', 'canary', 'cowcod', 'yelloweye']);
  for (const p of prot) { assert.ok(known.has(p.key)); assert.equal(p.must_release, p.key !== 'canary'); assert.match(p.note, /descending device/); assert.match(p.note, /rules table/); }
  assert.match(prot.find(p => p.key === 'canary').note, /sub-bag/);
  assert.deepEqual(species.PROTECTED.map(p => p.key).sort(), prot.map(p => p.key).sort());
});

test('speciesForTargets narrows to a region and canonicalises synonyms; prompts carry the rules', () => {
  const mb = species.speciesForTargets(read('../regions/morro-bay/region.json').species).map(s => s.key);
  for (const k of ['lingcod', 'rockfish', 'halibut', 'salmon', 'albacore', 'bluefin', 'dungeness', 'vermilion', 'yelloweye', 'cowcod', 'cabezon', 'kelp-greenling']) assert.ok(mb.includes(k), k);
  assert.ok(!mb.includes('california-halibut') && !mb.includes('king-salmon'), 'synonyms are canonical keys');
  assert.ok(!mb.includes('yellowtail'));
  const halibut = species.speciesForTargets(['halibut']).find(s => s.key === 'halibut');
  assert.deepEqual(halibut.lookalikes, ['pacific-halibut']); assert.ok(halibut.cues.length >= 2, 'halibut uses california-halibut cues');
  assert.equal(species.canonicalSpecies('king-salmon'), 'salmon');
  assert.ok(species.speciesForTargets(null).length >= 30, 'unknown region: every key');
  assert.match(prompts.classifyPrompt(), /hand or arm holding a fish is has_person=false unless a face is visible/);
  assert.match(prompts.countBoardPrompt(), /Never invent a boat name or a date/);
  assert.match(prompts.countBoardPrompt(), /keep the original label/);
  const fishPrompt = prompts.fishIdPrompt(species.speciesForTargets(['reef']));
  assert.match(fishPrompt, /- canary: Canary rockfish — /); assert.match(fishPrompt, /needs_better_photo/);
});

test('the synthetic fixture images are small PNGs that match a fresh render', () => {
  const dir = new URL('./fixtures/advisor/vision/images/', import.meta.url);
  const files = readdirSync(dir).sort();
  assert.deepEqual(files, Object.keys(images.IMAGES).sort());
  for (const name of files) {
    const bytes = readFileSync(new URL(name, dir));
    assert.ok(statSync(new URL(name, dir)).size <= 50 * 1024, name);
    assert.equal(bytes.subarray(1, 4).toString(), 'PNG');
    const w = bytes.readUInt32BE(16), h = bytes.readUInt32BE(20);
    assert.ok(w <= 256 && h <= 256, `${name} ${w}x${h}`);
    assert.ok(Buffer.compare(bytes, images.render(name)) === 0, `${name} is reproducible (node scripts/advisor/make-fixture-images.mjs)`);
  }
  for (const name of readdirSync(new URL('./fixtures/advisor/vision/', import.meta.url)).filter(f => f.endsWith('.json'))) {
    const f = fixture(name);
    assert.match(f._source, /Hand-written/, name);
    assert.ok(files.includes(f._image.replace('images/', '')), `${name} names an existing image`);
  }
});
