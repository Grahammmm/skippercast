// The Hermes vision conformance script (scripts/advisor/vision-conformance.mjs,
// TA-V2; docs/plans/text-advisor/07-vision.md § Hand-off to Hermes): it passes
// against its own contract-valid mock and fails against a deliberately broken
// one, its shape checks catch each kind of contract break, the Worker's
// Hermes client reads the mock's answers, and the deploy uploads the two
// HERMES_VISION_* secrets only when set. Offline: the mock listens on 127.0.0.1.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync, mkdtempSync, rmSync, writeFileSync} from 'node:fs';
import {spawnSync} from 'node:child_process';
import {tmpdir} from 'node:os';
import {join} from 'node:path';

const read = p => JSON.parse(readFileSync(new URL(p, import.meta.url)));
const script = await import('../scripts/advisor/vision-conformance.mjs');
const hermesClient = await import('../server/advisor/vision/hermes.ts');
const species = await import('../server/advisor/vision/species.ts');

const run = async (argv, env = {}) => { const lines = []; const code = await script.main(argv, {env, log: l => lines.push(l)}); return {code, lines, text: lines.join('\n')}; };

test('--mock: every check passes against the built-in contract-valid mock', async () => {
  const {code, lines, text} = await run(['--mock']);
  assert.equal(code, 0, text);
  assert.match(lines.at(-1), /^PASS: \d+ passed, 0 warnings, 0 failed against http:\/\/127\.0\.0\.1:\d+$/);
  const images = script.fixtureImages().map(i => i.name);
  assert.deepEqual(images, ['blank.png', 'count-board.png', 'deck-person.png', 'fish.png'], 'every fixture image');
  for (const name of images) for (const method of ['classify', 'count_board', 'fish_id']) assert.match(text, new RegExp(`^PASS  ${method} ${name.replace('.', '\\.')}  \\d+ ms$`, 'm'), `${method} ${name}`);
  for (const check of ['GET /v1/health', 'a request without the token is refused', 'count-board.png classifies as a count board', 'count-board.png reads at least one line',
    'fish.png classifies as a fish', 'blank.png names no fish with confidence']) assert.match(text, new RegExp(`^PASS  ${check.replace(/[.\/]/g, '\\$&')}`, 'm'), check);
});

test('against a deliberately broken service the run fails, naming each contract break', async () => {
  const mock = await script.startMock({broken: true});
  try {
    const {code, text} = await run(['--url', mock.url], {HERMES_VISION_TOKEN: mock.token});
    assert.equal(code, 1, text);
    assert.match(text, /^FAIL  GET \/v1\/health  the body is not \{ok: true, \.\.\.\}$/m);
    assert.match(text, /^FAIL  a request without the token is refused  HTTP 200/m);
    assert.match(text, /^FAIL  classify count-board\.png  kind "selfie" is not one of .*; kind_confidence 1\.7 is not a number in 0\.\.1; has_person is not a boolean$/m);
    assert.match(text, /^FAIL  count_board count-board\.png  .*lines\[0\]\.label is empty.*lines\[0\]\.count is not a non-negative integer/m);
    assert.match(text, /^FAIL  fish_id fish\.png  4 candidates \(at most 3\); candidates\[0\]\.species_key "not-a-species-1" is not one of the keys sent/m);
    assert.match(text, /^FAIL: 0 passed, 0 warnings, \d+ failed/m);
  } finally { await mock.close(); }
});

test('a slow answer, a 503, a missing model header and an unreachable service are each reported', async () => {
  const mock = await script.startMock();
  try {
    // Every request takes 21 s on the injected clock; the run fails on latency.
    let t = 0;
    const slow = await script.runConformance({base: mock.url, token: mock.token, clock: () => (t += 21000)});
    assert.ok(slow.failed);
    assert.match(slow.results.find(r => r.check === 'classify fish.png').detail, /took 21000 ms \(limit 20000 ms\)/);
    // A 503 from one endpoint, no X-Vision-Model from the others.
    const fetcher = async (url, init) => {
      if (url.endsWith('/v1/vision/count-board')) return new Response('busy', {status: 503});
      const r = await fetch(url, init);
      const headers = new Headers(r.headers); headers.delete('x-vision-model');
      return new Response(await r.text(), {status: r.status, headers});
    };
    const mixed = await script.runConformance({base: mock.url, token: mock.token, fetcher});
    assert.ok(mixed.failed);
    assert.match(mixed.results.find(r => r.check === 'count_board blank.png').detail, /HTTP 503/);
    const fish = mixed.results.find(r => r.check === 'classify fish.png');
    assert.equal(fish.status, 'WARN'); assert.match(fish.detail, /no X-Vision-Model header/);
  } finally { await mock.close(); }
  const down = await script.runConformance({base: 'http://127.0.0.1:9', token: 't', images: script.fixtureImages().slice(0, 1)});
  assert.ok(down.failed);
  assert.equal(down.results[0].status, 'FAIL'); assert.match(down.results[0].detail, /no answer/);
});

test('arguments: one of --url or --mock; the token from the environment; only an https URL (http on loopback for a mock)', async () => {
  for (const argv of [[], ['--mock', '--url', 'https://h.example'], ['--what'], ['--url'], ['--mock', '--region', 'Bad Region']]) assert.equal((await run(argv)).code, 2, JSON.stringify(argv));
  assert.deepEqual(script.parseArgs(['--url=https://h.example/vision', '--region', 'southern-california']), {url: 'https://h.example/vision', mock: false, region: 'southern-california'});
  const noToken = await run(['--url', 'https://h.example']);
  assert.equal(noToken.code, 2); assert.match(noToken.text, /HERMES_VISION_TOKEN is not set/);
  const http = await run(['--url', 'http://h.example'], {HERMES_VISION_TOKEN: 't'});
  assert.equal(http.code, 1); assert.match(http.text, /only an https HERMES_VISION_URL/);
  assert.deepEqual(script.checkBase('https://h.example/v//'), {ok: true, base: 'https://h.example/v'});
  assert.equal(script.checkBase('http://127.0.0.1:8080').ok, true);
  assert.equal(script.checkBase('https://u:p@h.example').ok, false);
  const source = readFileSync(new URL('../scripts/advisor/vision-conformance.mjs', import.meta.url), 'utf8');
  assert.doesNotMatch(source, /writeFile|appendFile|createWriteStream/, 'nothing is written to disk');
  assert.doesNotMatch(source, /argv[^\n]*TOKEN/, 'the token never comes from argv');
});

test('the shape checks catch each contract break the Worker would otherwise have to clamp', () => {
  const good = read('./fixtures/advisor/vision/classify-fish.json').content[0].input;
  assert.deepEqual(script.classificationProblems(good), []);
  assert.deepEqual(script.classificationProblems({...good, nsfw: undefined}), ['nsfw is not a boolean']);
  assert.deepEqual(script.classificationProblems([]), ['the body is not a JSON object']);
  const board = read('./fixtures/advisor/vision/count-board.json').content[0].input;
  assert.deepEqual(script.countBoardProblems(board), []);
  assert.deepEqual(script.countBoardProblems({...board, date_iso: '10/03', anglers: 2.5}), ['date_iso "10/03" is not YYYY-MM-DD', 'anglers is not a non-negative integer or null']);
  const keys = ['vermilion', 'canary', 'yelloweye'];
  const fish = read('./fixtures/advisor/vision/fish-id.json').content[0].input;
  assert.deepEqual(script.fishIdProblems(fish, keys), []);
  assert.deepEqual(script.fishIdProblems({...fish, candidates: [{...fish.candidates[0], species_key: 'lingcod'}]}, keys), ['candidates[0].species_key "lingcod" is not one of the keys sent (or null)']);
  assert.deepEqual(script.fishIdProblems({...fish, candidates: [{...fish.candidates[0], species_key: null}]}, keys), [], 'null with a label is allowed');
  assert.deepEqual(script.fishIdProblems({candidates: [], needs_better_photo: 'no', reason: 3}, keys), ['needs_better_photo is not a boolean', 'reason is not a string or null']);
  // The script sends the keys the Worker sends.
  assert.deepEqual(script.regionSpeciesKeys('morro-bay'), species.speciesForTargets(read('../regions/morro-bay/region.json').species).map(s => s.key));
  assert.deepEqual(script.ENDPOINTS, {classify: '/v1/vision/classify', count_board: '/v1/vision/count-board', fish_id: '/v1/vision/fish-id'});
  assert.deepEqual(script.ENDPOINTS, hermesClient.HERMES_PATHS, 'the script and the Worker client use the same paths');
  assert.equal(script.LATENCY_LIMIT_MS, hermesClient.HERMES_TIMEOUT_MS);
});

test('the Worker\'s Hermes client reads the mock\'s answers (multipart body, token, model header)', async () => {
  const mock = await script.startMock();
  try {
    // The client accepts only https, so route its https base to the mock's http address.
    const fetcher = (url, init) => fetch(url.replace('https://hermes.test', mock.url), init);
    const env = {HERMES_VISION_URL: 'https://hermes.test', HERMES_VISION_TOKEN: mock.token};
    const provider = hermesClient.createHermesVision({fetcher, regionTargets: () => read('../regions/morro-bay/region.json').species});
    const image = name => ({media_id: 'm1', mime: 'image/png', bytes: async () => new Uint8Array(readFileSync(new URL(`./fixtures/advisor/vision/images/${name}`, import.meta.url))).buffer});
    const quietly = async fn => { const saved = console.log; console.log = () => {}; try { return await fn(); } finally { console.log = saved; } };
    const c = await quietly(() => provider.classify(image('count-board.png'), env));
    assert.deepEqual([c.kind, c.provider, c.model], ['count_board', 'hermes', 'mock-vision-1']);
    const r = await quietly(() => provider.readCountBoard(image('count-board.png'), env));
    assert.equal(r.boat_name, 'Rita G');
    const f = await quietly(() => provider.identifyFish(image('fish.png'), env, 'morro-bay'));
    assert.deepEqual(f.candidates.map(x => x.species_key), ['vermilion', 'canary', 'yelloweye']);
    assert.deepEqual(await provider.health(env), {ok: true, detail: 'classify=mock-vision-1, fish_id=mock-vision-1'});
    await assert.rejects(quietly(() => provider.classify(image('fish.png'), {...env, HERMES_VISION_TOKEN: 'wrong'})), /HTTP 401/);
  } finally { await mock.close(); }
});

test('deploy wiring: the workflow passes HERMES_VISION_URL and HERMES_VISION_TOKEN, and the deploy uploads each only when set', () => {
  const NAMES = ['HERMES_VISION_URL', 'HERMES_VISION_TOKEN'];
  const workflow = readFileSync(new URL('../.github/workflows/deploy-cloudflare.yml', import.meta.url), 'utf8');
  for (const n of NAMES) assert.match(workflow, new RegExp(`^ {10}${n}: \\$\\{\\{ secrets\\.${n} \\}\\}$`, 'm'), n);
  const sh = readFileSync(new URL('../scripts/cloudflare_deploy.sh', import.meta.url), 'utf8');
  const marker = "python3 - <<'PY' > var/cloudflare-secrets.json";
  const python = sh.slice(sh.indexOf(marker) + marker.length, sh.indexOf('\nPY\n')).trim();
  const dir = mkdtempSync(join(tmpdir(), 'secrets-'));
  try {
    const file = join(dir, 'secrets.py');
    writeFileSync(file, python);
    const run = env => JSON.parse(spawnSync('python3', [file], {encoding: 'utf8', env: {PATH: process.env.PATH, ...env}}).stdout);
    assert.deepEqual(run({HERMES_VISION_URL: 'https://h.example', HERMES_VISION_TOKEN: 't'}), {HERMES_VISION_URL: 'https://h.example', HERMES_VISION_TOKEN: 't'});
    assert.deepEqual(run({HERMES_VISION_TOKEN: 't'}), {HERMES_VISION_TOKEN: 't'});
    assert.deepEqual(run({}), {});
  } finally { rmSync(dir, {recursive: true, force: true}); }
  // Secrets, never deploy vars (scripts/wrangler_config.mjs refuses them as vars).
  const config = readFileSync(new URL('../scripts/wrangler_config.mjs', import.meta.url), 'utf8');
  for (const n of NAMES) assert.match(config, new RegExp(`'${n}'`), n);
});
