#!/usr/bin/env node
// Hermes vision conformance (docs/plans/text-advisor/07-vision.md § Hermes
// provider and § Hand-off to Hermes; TA-V2). Posts every synthetic fixture
// image under tests/fixtures/advisor/vision/images/ to a Hermes vision service
// and checks what comes back against the contract the Worker's client
// (server/advisor/vision/hermes.ts) relies on, so the Hermes side can test
// itself before the owner sets HERMES_VISION_URL.
//
//   HERMES_VISION_TOKEN=... node scripts/advisor/vision-conformance.mjs --url https://hermes.example.com [--region morro-bay]
//   node scripts/advisor/vision-conformance.mjs --mock      # against a built-in mock service (what the tests run)
//
// Checks, each reported PASS, WARN or FAIL:
//   - GET /v1/health answers 200 {ok: true, models: {...}} (models missing: WARN);
//   - a request without the token is refused (401 or 403);
//   - every image to every endpoint: 200 JSON within 20 s, X-Vision-Model set
//     (WARN when missing), every field of the method's result type present with
//     the right type, confidences within 0..1, fish-ID candidates at most three,
//     each species_key null or one of the meta.species_keys sent;
//   - loose sense checks (WARN only): count-board.png classifies as count_board
//     or text_present and reads at least one line; fish.png classifies as fish
//     (or has_fish); blank.png names no fish.
// Exit status 1 when any check FAILs (WARNs do not fail), 2 on bad arguments.
// The token is read from the environment, never argv (shell history); nothing is written to disk.
import {createServer} from 'node:http';
import {createHash, randomBytes} from 'node:crypto';
import {readFileSync, readdirSync} from 'node:fs';
import {pathToFileURL} from 'node:url';

const root = new URL('../../', import.meta.url);
const {IMAGE_KINDS} = await import(new URL('server/advisor/vision/errors.ts', root).href);
const {speciesForTargets} = await import(new URL('server/advisor/vision/species.ts', root).href);

export const IMAGES_DIR = new URL('tests/fixtures/advisor/vision/images/', root);
const FIXTURES_DIR = new URL('tests/fixtures/advisor/vision/', root);
/** The contract's deadline (07: respond within 20 s or return 503). */
export const LATENCY_LIMIT_MS = 20_000;
export const ENDPOINTS = Object.freeze({classify: '/v1/vision/classify', count_board: '/v1/vision/count-board', fish_id: '/v1/vision/fish-id'});
const USAGE = 'usage: HERMES_VISION_TOKEN=... node scripts/advisor/vision-conformance.mjs --url <https base> [--region <id>]\n       node scripts/advisor/vision-conformance.mjs --mock [--region <id>]';
const MIME = {'.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg'};

/** argv -> {url, mock, region}; throws with the usage line on anything unexpected. */
export function parseArgs(argv) {
  const out = {url: null, mock: false, region: 'morro-bay'};
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--mock') out.mock = true;
    else if (a === '--url' && argv[i + 1]) out.url = argv[++i];
    else if (a.startsWith('--url=')) out.url = a.slice(6);
    else if (a === '--region' && argv[i + 1]) out.region = argv[++i];
    else if (a.startsWith('--region=')) out.region = a.slice(9);
    else throw Error(USAGE);
  }
  if (out.mock === Boolean(out.url)) throw Error(USAGE);
  if (!/^[a-z0-9][a-z0-9-]{0,62}$/.test(out.region)) throw Error(`not a region id: ${out.region}`);
  return out;
}

/** The fixture images: [{name, mime, bytes}], sorted by name. */
export function fixtureImages() {
  return readdirSync(IMAGES_DIR).filter(n => MIME[n.slice(n.lastIndexOf('.'))]).sort()
    .map(name => ({name, mime: MIME[name.slice(name.lastIndexOf('.'))], bytes: readFileSync(new URL(name, IMAGES_DIR))}));
}

/** The species keys the Worker would send for a region (regions/<id>/region.json `species`; every key when the region is unknown). */
export function regionSpeciesKeys(region) {
  let targets = null;
  try { targets = JSON.parse(readFileSync(new URL(`regions/${region}/region.json`, root), 'utf8')).species ?? null; } catch { targets = null; }
  return speciesForTargets(targets).map(s => s.key);
}

// ---- Shape checks (strict: the Worker clamps, but a service that needs clamping is out of contract) ----

const isObj = v => v !== null && typeof v === 'object' && !Array.isArray(v);
const conf = v => typeof v === 'number' && Number.isFinite(v) && v >= 0 && v <= 1;
const strOrNull = v => v === null || typeof v === 'string';
const intOrNull = v => v === null || (Number.isInteger(v) && v >= 0);

/** Contract problems in a Classification body: [] when it conforms. */
export function classificationProblems(b) {
  if (!isObj(b)) return ['the body is not a JSON object'];
  const p = [];
  if (!IMAGE_KINDS.includes(b.kind)) p.push(`kind ${JSON.stringify(b.kind)} is not one of ${IMAGE_KINDS.join(', ')}`);
  for (const k of ['kind_confidence', 'person_confidence']) if (!conf(b[k])) p.push(`${k} ${JSON.stringify(b[k])} is not a number in 0..1`);
  for (const k of ['has_person', 'has_fish', 'text_present', 'nsfw']) if (typeof b[k] !== 'boolean') p.push(`${k} is not a boolean`);
  return p;
}

/** Contract problems in a CountBoardReading body. */
export function countBoardProblems(b) {
  if (!isObj(b)) return ['the body is not a JSON object'];
  const p = [];
  for (const k of ['boat_name', 'date_text', 'date_iso', 'trip_type', 'notes']) if (!strOrNull(b[k])) p.push(`${k} is not a string or null`);
  if (typeof b.date_iso === 'string' && !/^\d{4}-\d{2}-\d{2}$/.test(b.date_iso)) p.push(`date_iso ${JSON.stringify(b.date_iso)} is not YYYY-MM-DD`);
  for (const k of ['date_confidence', 'overall_confidence']) if (!conf(b[k])) p.push(`${k} ${JSON.stringify(b[k])} is not a number in 0..1`);
  if (!intOrNull(b.anglers)) p.push('anglers is not a non-negative integer or null');
  if (!Array.isArray(b.lines)) p.push('lines is not an array');
  else b.lines.forEach((l, i) => {
    if (!isObj(l)) { p.push(`lines[${i}] is not an object`); return; }
    if (typeof l.label !== 'string' || !l.label.trim()) p.push(`lines[${i}].label is empty`);
    for (const k of ['count', 'released']) if (!intOrNull(l[k])) p.push(`lines[${i}].${k} is not a non-negative integer or null`);
    if (!conf(l.confidence)) p.push(`lines[${i}].confidence is not a number in 0..1`);
  });
  return p;
}

/** Contract problems in a FishId body, given the species keys sent in meta.species_keys. */
export function fishIdProblems(b, keys) {
  if (!isObj(b)) return ['the body is not a JSON object'];
  const p = [], allowed = new Set(keys);
  if (!Array.isArray(b.candidates)) p.push('candidates is not an array');
  else {
    if (b.candidates.length > 3) p.push(`${b.candidates.length} candidates (at most 3)`);
    b.candidates.forEach((c, i) => {
      if (!isObj(c)) { p.push(`candidates[${i}] is not an object`); return; }
      if (!(c.species_key === null || (typeof c.species_key === 'string' && allowed.has(c.species_key)))) p.push(`candidates[${i}].species_key ${JSON.stringify(c.species_key)} is not one of the keys sent (or null)`);
      if (typeof c.label !== 'string' || !c.label.trim()) p.push(`candidates[${i}].label is empty`);
      if (!conf(c.confidence)) p.push(`candidates[${i}].confidence is not a number in 0..1`);
      if (!Array.isArray(c.cues) || c.cues.some(q => typeof q !== 'string')) p.push(`candidates[${i}].cues is not an array of strings`);
    });
  }
  if (typeof b.needs_better_photo !== 'boolean') p.push('needs_better_photo is not a boolean');
  if (!strOrNull(b.reason)) p.push('reason is not a string or null');
  return p;
}

/** Soft problems (WARN): more than 3 cues, candidates not sorted by confidence. */
function fishIdWarnings(b) {
  const w = [];
  const c = Array.isArray(b?.candidates) ? b.candidates.filter(isObj) : [];
  if (c.some(x => Array.isArray(x.cues) && x.cues.length > 3)) w.push('a candidate has more than 3 cues (the Worker keeps 3)');
  if (c.some((x, i) => i && conf(x.confidence) && conf(c[i - 1].confidence) && x.confidence > c[i - 1].confidence)) w.push('candidates are not sorted by confidence (the Worker sorts them)');
  return w;
}

// ---- Runner ---------------------------------------------------------------------------

/** A base URL the Worker would accept (https, no credentials, query or fragment); http only for a loopback host (the mock). */
export function checkBase(raw) {
  let url;
  try { url = new URL(raw); } catch { return {ok: false, detail: `not a URL: ${raw}`}; }
  const loopback = ['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname);
  if (url.username || url.password || url.search || url.hash) return {ok: false, detail: 'the URL must not carry credentials, a query or a fragment'};
  if (url.protocol !== 'https:' && !(loopback && url.protocol === 'http:')) return {ok: false, detail: 'the Worker accepts only an https HERMES_VISION_URL'};
  return {ok: true, base: (url.origin + url.pathname).replace(/\/+$/, '')};
}

/**
 * Run every check against `base` with `token`. Returns {results: [{status, check, detail}], failed}.
 * `fetcher` and `clock` are injectable (tests); defaults: fetch, performance.now.
 */
export async function runConformance({base, token, region = 'morro-bay', fetcher = fetch, clock = () => performance.now(), images = fixtureImages()}) {
  const results = [];
  const add = (status, check, detail = '') => results.push({status, check, detail});
  const keys = regionSpeciesKeys(region);
  const auth = {authorization: `Bearer ${token}`, accept: 'application/json'};
  const timed = async (url, init) => {
    const t = clock();
    try {
      const response = await fetcher(url, {...init, signal: AbortSignal.timeout(LATENCY_LIMIT_MS + 5000)});
      const text = await response.text();
      return {response, text, ms: clock() - t};
    } catch (error) { return {error, ms: clock() - t}; }
  };
  const json = text => { try { return JSON.parse(text); } catch { return undefined; } };

  // Health.
  const h = await timed(`${base}/v1/health`, {method: 'GET', headers: auth});
  if (h.error) add('FAIL', 'GET /v1/health', `no answer (${h.error.name === 'TimeoutError' ? 'timeout' : h.error.message})`);
  else {
    const body = json(h.text);
    if (h.response.status !== 200) add('FAIL', 'GET /v1/health', `HTTP ${h.response.status}`);
    else if (!isObj(body) || body.ok !== true) add('FAIL', 'GET /v1/health', 'the body is not {ok: true, ...}');
    else if (!isObj(body.models)) add('WARN', 'GET /v1/health', 'ok, but no models object');
    else add('PASS', 'GET /v1/health', `ok (${Object.entries(body.models).map(([k, v]) => `${k}=${v}`).join(', ') || 'no models listed'})`);
  }

  // The token is required.
  const first = images[0];
  if (first) {
    const form = formFor(first, {media_id: 'conformance-noauth', region: null});
    const r = await timed(`${base}${ENDPOINTS.classify}`, {method: 'POST', headers: {accept: 'application/json'}, body: form});
    if (r.error) add('WARN', 'a request without the token is refused', `no answer (${r.error.message})`);
    else if (r.response.status === 401 || r.response.status === 403) add('PASS', 'a request without the token is refused', `HTTP ${r.response.status}`);
    else add('FAIL', 'a request without the token is refused', `HTTP ${r.response.status}: the service must require Authorization: Bearer <HERMES_VISION_TOKEN>`);
  }

  // Every image, every endpoint.
  const seen = {};
  for (const image of images) {
    for (const [method, path] of Object.entries(ENDPOINTS)) {
      const meta = {media_id: `conformance-${image.name.replace(/\.\w+$/, '')}`, region: method === 'fish_id' ? region : null, ...(method === 'fish_id' ? {species_keys: keys} : {})};
      const check = `${method} ${image.name}`;
      const r = await timed(`${base}${path}`, {method: 'POST', headers: auth, body: formFor(image, meta)});
      if (r.error) { add('FAIL', check, r.error.name === 'TimeoutError' ? `no answer within ${LATENCY_LIMIT_MS / 1000} s` : `no answer (${r.error.message})`); continue; }
      if (r.response.status === 503) { add('FAIL', check, 'HTTP 503 (busy or over the deadline; the Worker falls back to Claude)'); continue; }
      if (r.response.status !== 200) { add('FAIL', check, `HTTP ${r.response.status}`); continue; }
      if (r.ms >= LATENCY_LIMIT_MS) { add('FAIL', check, `took ${Math.round(r.ms)} ms (limit ${LATENCY_LIMIT_MS} ms)`); continue; }
      const body = json(r.text);
      if (body === undefined) { add('FAIL', check, 'the body is not JSON'); continue; }
      const problems = method === 'classify' ? classificationProblems(body) : method === 'count_board' ? countBoardProblems(body) : fishIdProblems(body, keys);
      if (problems.length) { add('FAIL', check, problems.join('; ')); continue; }
      const warnings = method === 'fish_id' ? fishIdWarnings(body) : [];
      const model = r.response.headers.get('x-vision-model');
      if (!model) warnings.push('no X-Vision-Model header (the Worker records "unknown")');
      add(warnings.length ? 'WARN' : 'PASS', check, [`${Math.round(r.ms)} ms`, ...warnings].join('; '));
      (seen[image.name] ??= {})[method] = body;
    }
  }

  // Loose sense checks on the images whose content is known.
  const board = seen['count-board.png'], fish = seen['fish.png'], blank = seen['blank.png'];
  if (board?.classify) {
    const ok = board.classify.kind === 'count_board' || board.classify.text_present === true;
    add(ok ? 'PASS' : 'WARN', 'count-board.png classifies as a count board', `kind ${board.classify.kind} (${board.classify.kind_confidence}), text_present ${board.classify.text_present}`);
  }
  if (board?.count_board) add(board.count_board.lines.length ? 'PASS' : 'WARN', 'count-board.png reads at least one line', `${board.count_board.lines.length} lines, overall ${board.count_board.overall_confidence}`);
  if (fish?.classify) {
    const ok = fish.classify.kind === 'fish' || fish.classify.has_fish === true;
    add(ok ? 'PASS' : 'WARN', 'fish.png classifies as a fish', `kind ${fish.classify.kind} (${fish.classify.kind_confidence}), has_fish ${fish.classify.has_fish}`);
  }
  if (blank?.fish_id) {
    const ok = blank.fish_id.needs_better_photo === true || !blank.fish_id.candidates.some(c => c.confidence >= 0.6);
    add(ok ? 'PASS' : 'WARN', 'blank.png names no fish with confidence', ok ? 'needs_better_photo or no candidate at 0.6 or above' : 'a candidate at 0.6 or above on a blank image: is the confidence calibrated?');
  }
  return {results, failed: results.some(r => r.status === 'FAIL')};
}

/** The multipart body the Worker sends: `image` (the file) and `meta` (a JSON text field). */
export function formFor(image, meta) {
  const form = new FormData();
  form.append('image', new Blob([image.bytes], {type: image.mime}), image.name);
  form.append('meta', JSON.stringify(meta));
  return form;
}

// ---- Mock service ---------------------------------------------------------------------

const fixtureInput = name => JSON.parse(readFileSync(new URL(name, FIXTURES_DIR), 'utf8')).content.find(b => b.type === 'tool_use').input;
/** Which recorded response the mock answers for an image (by its fixture name); anything else gets the empty answer. */
const MOCK_ANSWERS = {
  classify: {'count-board.png': 'classify-count-board.json', 'fish.png': 'classify-fish.json', 'blank.png': 'classify-blank.json', 'deck-person.png': 'classify-deck-person.json'},
  count_board: {'count-board.png': 'count-board.json'},
  fish_id: {'fish.png': 'fish-id.json'},
};
const EMPTY = {
  classify: {kind: 'unknown', kind_confidence: 0.2, has_person: false, person_confidence: 0, has_fish: false, text_present: false, nsfw: false},
  count_board: {boat_name: null, date_text: null, date_iso: null, date_confidence: 0, trip_type: null, anglers: null, lines: [], notes: null, overall_confidence: 0.1},
  fish_id: {candidates: [], needs_better_photo: true, reason: 'no_fish'},
};
/** What the deliberately broken mock answers: out-of-contract values in every method. */
const BROKEN = {
  classify: {kind: 'selfie', kind_confidence: 1.7, has_person: 'yes', person_confidence: 0.1, has_fish: false, text_present: false, nsfw: false},
  count_board: {boat_name: 'X', lines: [{label: '', count: -2, confidence: 2}], overall_confidence: 0.9},
  fish_id: {candidates: [1, 2, 3, 4].map(i => ({species_key: `not-a-species-${i}`, label: 'Fish', confidence: 0.5, cues: []})), needs_better_photo: false, reason: null},
};

/**
 * A local mock of the Hermes service on 127.0.0.1 (a random port). `broken: false`
 * answers within the contract (the recorded responses for the fixture images by
 * their SHA-256, the empty answer otherwise) and requires the token; `broken: true`
 * ignores the token, fails health and answers out of contract.
 * Returns {url, token, close()}.
 */
export async function startMock({broken = false, token = randomBytes(16).toString('hex'), model = 'mock-vision-1'} = {}) {
  const byHash = new Map(fixtureImages().map(i => [createHash('sha256').update(i.bytes).digest('hex'), i.name]));
  const routes = Object.fromEntries(Object.entries(ENDPOINTS).map(([m, p]) => [p, m]));
  const server = createServer(async (req, res) => {
    const send = (status, body, headers = {}) => { res.writeHead(status, {'content-type': 'application/json', ...headers}); res.end(JSON.stringify(body)); };
    try {
      if (!broken && req.headers.authorization !== `Bearer ${token}`) return send(401, {error: 'unauthorized'});
      if (req.method === 'GET' && req.url === '/v1/health') return broken ? send(200, {ok: false}) : send(200, {ok: true, models: {classify: model, fish_id: model}});
      const method = req.method === 'POST' ? routes[req.url] : undefined;
      if (!method) return send(404, {error: 'not found'});
      const chunks = [];
      for await (const c of req) chunks.push(c);
      const form = await new Request('http://mock/', {method: 'POST', headers: {'content-type': req.headers['content-type'] ?? ''}, body: Buffer.concat(chunks)}).formData();
      const image = form.get('image'), meta = JSON.parse(String(form.get('meta') ?? 'null'));
      if (!(image instanceof Blob) || !meta || typeof meta.media_id !== 'string') return send(400, {error: 'image and meta.media_id are required'});
      if (method === 'fish_id' && !Array.isArray(meta.species_keys)) return send(400, {error: 'meta.species_keys is required'});
      if (broken) return send(200, BROKEN[method]);
      const name = byHash.get(createHash('sha256').update(Buffer.from(await image.arrayBuffer())).digest('hex'));
      const fixture = name && MOCK_ANSWERS[method][name];
      const answer = fixture ? fixtureInput(fixture) : structuredClone(EMPTY[method]);
      if (method === 'fish_id') answer.candidates = answer.candidates.map(c => ({...c, species_key: meta.species_keys.includes(c.species_key) ? c.species_key : null}));
      return send(200, answer, {'x-vision-model': model});
    } catch (error) { return send(500, {error: String(error?.message ?? error)}); }
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const {port} = server.address();
  return {url: `http://127.0.0.1:${port}`, token, close: () => new Promise(resolve => server.close(() => resolve()))};
}

// ---- CLI ------------------------------------------------------------------------------

export async function main(argv, {env = process.env, log = console.log, fetcher} = {}) {
  let args;
  try { args = parseArgs(argv); } catch (e) { log(e.message); return 2; }
  let mock = null, base, token;
  if (args.mock) {
    mock = await startMock();
    base = mock.url; token = mock.token;
    log(`Mock Hermes service at ${base}`);
  } else {
    const checked = checkBase(args.url);
    if (!checked.ok) { log(`FAIL  HERMES_VISION_URL  ${checked.detail}`); return 1; }
    base = checked.base; token = (env.HERMES_VISION_TOKEN ?? '').trim();
    if (!token) { log('HERMES_VISION_TOKEN is not set in the environment.'); return 2; }
  }
  try {
    const {results, failed} = await runConformance({base, token, region: args.region, ...(fetcher ? {fetcher} : {})});
    for (const r of results) log(`${r.status.padEnd(4)}  ${r.check}${r.detail ? `  ${r.detail}` : ''}`);
    const n = s => results.filter(r => r.status === s).length;
    log(`${failed ? 'FAIL' : 'PASS'}: ${n('PASS')} passed, ${n('WARN')} warnings, ${n('FAIL')} failed against ${base}`);
    return failed ? 1 : 0;
  } finally { await mock?.close(); }
}

if (import.meta.url === pathToFileURL(process.argv[1] ?? '').href) {
  try { process.exit(await main(process.argv.slice(2))); }
  catch (e) { console.error(String(e?.message ?? e)); process.exit(1); }
}
