// SC1407-08 (#1762 M3): web/app/main.tsx starts the Chart's library (web/map/maplibre.js) right after the first render
// on a /map page that opens on the Chart, instead of waiting for the Chart to mount. The real main.tsx is bundled with
// esbuild, every module it imports replaced by a recording stand-in, and the library wrapper by a lazy chunk that records
// its evaluation. web/map/chart.ts is bundled beside it to show both import the one chunk. Each case runs in its own
// Node process with a fake page; nothing is fetched.
import assert from 'node:assert/strict';
import test from 'node:test';
import {spawnSync} from 'node:child_process';
import {mkdtemp, readFile, rm, writeFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {rendererPlugins} from './helpers/esbuild-url.mjs';

const ROOT = new URL('..', import.meta.url).pathname;
const MAIN = join(ROOT, 'web/app/main.tsx');
const CHART = join(ROOT, 'web/map/chart.ts');

// The library stand-in: records each evaluation, settles a little later (as a download would) and fails on request.
const WRAPPER = `globalThis.__events.push('wrapper:evaluate');
await new Promise(resolve => setTimeout(resolve, 5));
if (globalThis.__scenario.reject) throw new Error('wrapper failed');
export const lib = {};
`;
// Every import of main.tsx becomes a stand-in from the page's __stub (below), so the bootstrap runs without the app.
const stubs = {name: 'main-stubs', setup(b) {
  // The real path either importer names (so both resolve to one module), loaded as the stand-in.
  b.onResolve({filter: /(?:^|\/)maplibre\.js$/}, args => ({path: join(args.resolveDir, args.path)}));
  b.onLoad({filter: /\/web\/map\/maplibre\.js$/}, () => ({contents: WRAPPER, loader: 'js'}));
  b.onResolve({filter: /.*/}, args => args.importer === MAIN ? {path: args.path, namespace: 'stub'} : undefined);
  b.onLoad({filter: /.*/, namespace: 'stub'}, async args => {
    const source = await readFile(MAIN, 'utf8');
    const names = args.path.endsWith('jsx-runtime') ? ['jsx', 'jsxs', 'Fragment']
      : [...source.matchAll(/^import \{([^}]+)\} from '([^']+)';$/gm)].filter(m => m[2] === args.path).flatMap(m => m[1].split(',').map(n => n.trim()));
    return {contents: names.map(n => `export const ${n} = globalThis.__stub(${JSON.stringify(args.path)}, ${JSON.stringify(n)});`).join('\n'), loader: 'js'};
  });
}};

// One Node process: the page described by `scenario`, the bootstrap, then (if asked) the Chart's own import of its library.
const RUNNER = `import {registerHooks} from 'node:module';
const scenario = JSON.parse(process.argv[2]);
const events = globalThis.__events = [];
globalThis.__scenario = scenario;
registerHooks({resolve(specifier, context, next) {
  const result = next(specifier, context);
  if (result.url.split('/').pop().startsWith('maplibre-')) events.push('wrapper:import');
  return result;
}});
const rejections = [];
process.on('unhandledRejection', error => rejections.push(String(error)));
const page = new URL(scenario.href);
globalThis.location = {href: page.href, pathname: page.pathname, search: page.search, hash: page.hash, replace() { events.push('location:replace'); }};
globalThis.document = {getElementById: id => id === 'app' && scenario.host ? {replaceChildren() {}} : null};
globalThis.matchMedia = () => ({matches: false, addEventListener() {}});
const state = {region: scenario.region, coast: scenario.coast ?? null, shownPresentation: scenario.presentation, regionInfo: null, regionPlans: null, narrow: false, profile: 'boat', species: null};
globalThis.__stub = (from, name) => {
  if (name in state) return {get value() { return state[name]; }, set value(v) { state[name] = v; }, peek: () => state[name]};
  if (name === 'NARROW_QUERY') return '(max-width: 1023px)';
  if (name === 'savedHomeURL') return () => { events.push('savedHome'); return new Promise(() => {}); };
  return (...args) => { if (['render', 'startTrip'].includes(name)) events.push(name); return () => {}; };
};
await import(scenario.main);
events.push('bootstrap:done');
let chart = null;
if (scenario.chart) {
  try { chart = (await import(scenario.chart)) === (await import(scenario.chart)) ? 'loaded' : 'two modules'; }
  catch (error) { chart = 'failed: ' + error.message; }
}
await new Promise(resolve => setTimeout(resolve, 30));
process.stdout.write(JSON.stringify({events, rejections, chart}));
`;

let bundle;
async function bundled() {
  if (!bundle) {
    const dir = await mkdtemp(join(tmpdir(), 'maplibre-bootstrap-'));
    const out = join(dir, 'out');
    const {metafile} = await build({entryPoints: {main: MAIN, chart: CHART}, bundle: true, splitting: true, format: 'esm', platform: 'browser',
      absWorkingDir: ROOT, outdir: out, chunkNames: '[name]-[hash]', metafile: true, write: true, logLevel: 'silent', plugins: [stubs, ...rendererPlugins]});
    await writeFile(join(dir, 'runner.mjs'), RUNNER);
    const wrapper = Object.entries(metafile.outputs).filter(([, o]) => o.entryPoint === 'web/map/maplibre.js').map(([path]) => path);
    assert.equal(wrapper.length, 1, 'the library wrapper is one lazy chunk');
    bundle = {dir, metafile, main: join(out, 'main.js'), library: join(ROOT, wrapper[0])};
  }
  return bundle;
}
test.after(async () => { if (bundle) await rm(bundle.dir, {recursive: true, force: true}); });

async function page(t, scenario) {
  const b = await bundled();
  const args = {host: true, presentation: 'chart', ...scenario, main: pathToFileURL(b.main).href, chart: scenario.chart ? pathToFileURL(b.library).href : null};
  const result = spawnSync(process.execPath, [join(b.dir, 'runner.mjs'), JSON.stringify(args)], {encoding: 'utf8', cwd: b.dir});
  assert.equal(result.status, 0, result.stderr);
  return JSON.parse(result.stdout);
}
const warms = r => r.events.filter(e => e === 'wrapper:evaluate').length;

test('bootstrap_warms_once_after_render_before_trip_start', async t => {
  for (const href of ['https://s.test/map?region=test-coast', 'https://s.test/map?region=test-coast&view=conditions', 'https://s.test/map?region=test-coast#export']) {
    const r = await page(t, {href, region: 'test-coast'});
    assert.deepEqual(r.events, ['render', 'wrapper:import', 'startTrip', 'bootstrap:done', 'wrapper:evaluate'], href);
    assert.deepEqual(r.rejections, [], href);
  }
});

test('bootstrap_skips_non_chart_or_unresolved_entry', async t => {
  const cases = {
    landing: {href: 'https://s.test/', region: 'test-coast'},
    admin: {href: 'https://s.test/admin', region: 'test-coast'},
    'admin page': {href: 'https://s.test/admin/fleet', region: 'test-coast'},
    'app.html': {href: 'https://s.test/app.html?region=test-coast', region: 'test-coast'},
    'no host': {href: 'https://s.test/map?region=test-coast', region: 'test-coast', host: false},
    'coast without region': {href: 'https://s.test/map?coast=morro', region: null, coast: 'morro'},
    'saved-home redirect': {href: 'https://s.test/map', region: null},
    '2d terrain': {href: 'https://s.test/map?region=test-coast&presentation=2d', region: 'test-coast', presentation: '2d'},
    '3d terrain': {href: 'https://s.test/map?region=test-coast&presentation=3d', region: 'test-coast', presentation: '3d'},
  };
  for (const [name, scenario] of Object.entries(cases)) {
    const r = await page(t, scenario);
    assert.equal(warms(r), 0, name);
    assert.ok(!r.events.includes('wrapper:import'), name);
    assert.equal(r.events.includes('render'), scenario.host !== false, name);
    assert.ok(r.events.includes('startTrip'), name);
  }
  assert.ok((await page(t, cases['saved-home redirect'])).events.includes('savedHome'), 'the saved home still resolves');
});

test('warm_and_chart_share_one_module_evaluation', async t => {
  const b = await bundled();
  // The bootstrap and the Chart (web/map/chart.ts) both import web/map/maplibre.js, and every importer imports it dynamically.
  const library = Object.entries(b.metafile.inputs).flatMap(([from, input]) => input.imports.filter(i => i.path === 'web/map/maplibre.js').map(i => [from, i.kind]));
  for (const from of ['web/app/main.tsx', 'web/map/chart.ts']) assert.ok(library.some(([f]) => f === from), from);
  assert.ok(library.every(([, kind]) => kind === 'dynamic-import'), JSON.stringify(library));
  const r = await page(t, {href: 'https://s.test/map?region=test-coast', region: 'test-coast', chart: true});
  assert.equal(r.chart, 'loaded');
  assert.equal(warms(r), 1, 'one evaluation for the bootstrap and the Chart');
});

test('warm_rejection_does_not_change_chart_error_owner', async t => {
  const r = await page(t, {href: 'https://s.test/map?region=test-coast', region: 'test-coast', reject: true, chart: true});
  assert.deepEqual(r.rejections, [], 'the bootstrap swallows its own failure');
  assert.deepEqual(r.events.slice(0, 3), ['render', 'wrapper:import', 'startTrip'], 'the bootstrap did start the load');
  assert.equal(warms(r), 1, 'the failed module is not evaluated again');
  assert.equal(r.chart, 'failed: wrapper failed', 'the Chart still sees the failure');
});
