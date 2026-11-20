import {execFileSync} from 'node:child_process';
import {createHash} from 'node:crypto';
import {readFile} from 'node:fs/promises';
import {createServer} from 'node:http';
import type {AddressInfo} from 'node:net';
import {fileURLToPath} from 'node:url';
import type {BrowserContext} from '@playwright/test';
import {build} from 'esbuild';
import {rendererPlugins} from '../tests/helpers/esbuild-url.mjs';

const root = new URL('../', import.meta.url);
const region = '/regions/morro-bay/region.json';
const startup = '/regions/morro-bay/atlas-marks.json';
const full = '/data/atlas.json';
const screen = '/data/protected-areas.geojson';
const coverage = '/regions/morro-bay/coverage.json';
const now = '2030-05-10T18:15:00Z';

// Requalification is explicit. A new merge base or any changed input must fail
// before launch, even if the browser would otherwise render something plausible.
const manifest = {
  base: 'ca695254b65dc0c1313f09c7427f98a78ab09c74',
  files: {
    [`dist${region}`]: ['7aa807d9f5b9d13bf4f3ceb8b82acdae9f223ac1', '6bcac86a827ca62a805c1c61bda1f6f1973a1551d5ede42f522c232b978ea466'],
    [`dist${startup}`]: ['ded9d01953b483b50b1c4330660169efb1864fd0', '6677776dec9044c55ae3bed983e4d66a246a5af362963083751d9a86cd8a9e2a'],
    [`dist${full}`]: ['11d0b970c67f374c0d31ee58a7628b38b0195989', '57e35ad2430f6ca48a9d79e4da4fa2db8ce88ab93758e8565d3d2565ec7529dd'],
    'web/map/marks.ts': ['5ed2e11a447917e487abbbaed2549b99c31ab179', '128a9884ab7a14c0e6b285d44d6a4a4d8851a966abfe9ea18106ce2f6c49be70'],
  },
};

export type MarksArm = 'startup' | '4a-i' | '4a-ii' | '4b';

export async function qualifyMarksInputs() {
  const git = (...args: string[]) => execFileSync('git', args, {cwd: fileURLToPath(root), encoding: 'utf8'}).trim();
  if (git('merge-base', 'HEAD', 'origin/main') !== manifest.base) throw new Error('Marks fixture not qualified: base drift');
  const bytes = new Map<string, Buffer>();
  for (const [path, [blob, digest]] of Object.entries(manifest.files)) {
    const file = await readFile(new URL(path, root));
    if (git('rev-parse', `${manifest.base}:${path}`) !== blob || git('rev-parse', `HEAD:${path}`) !== blob ||
        createHash('sha256').update(file).digest('hex') !== digest) throw new Error(`Marks fixture not qualified: ${path} drift`);
    bytes.set(path, file);
  }
  const meta = JSON.parse(bytes.get(`dist${region}`)!.toString('utf8'));
  if (meta.assets?.atlas !== full.slice(1)) throw new Error('Marks fixture not qualified: legacy binding drift');
  return {meta, region: bytes.get(`dist${region}`)!, startup: bytes.get(`dist${startup}`)!, full: bytes.get(`dist${full}`)!};
}

type Inputs = Awaited<ReturnType<typeof qualifyMarksInputs>>;

// All boundary features are invented and far from the admitted atlas. The
// real screen still validates shape, envelope and freshness before admitting marks.
function boundaryFixture(inputs: Inputs) {
  return {type: 'FeatureCollection', checked_at: now,
    source_url: `https://services2.arcgis.com/Uq9r85Potqm3MfRV/arcgis/rest/services/biosds582_fpu/FeatureServer/0/query?geometry=${inputs.meta.mpa.bounds.join(',')}`,
    features: Array.from({length: inputs.meta.mpa.minimum_features}, (_, i) => ({type: 'Feature', properties: {NAME: `Synthetic screen ${i}`},
      geometry: {type: 'Polygon', coordinates: [[[0, i], [1, i], [1, i + 0.5], [0, i]]]}}))};
}

export async function buildMarksProbe() {
  // No renderer mocking at the observed boundary: this probe qualifies the
  // production reader and its outgoing terrain registry only, not GPU rendering.
  const result = await build({bundle: true, write: false, format: 'esm', plugins: rendererPlugins,
    stdin: {resolveDir: fileURLToPath(root), contents: `
      import {configureStore, syncFromURL} from './web/state.ts';
      import {createMarks, markData, marksAvailability} from './web/map/marks.ts';
      import {terrainLayers} from './web/map/layers.ts';
      configureStore({v2: true, storage: null});
      syncFromURL(location.href);
      let errors = 0;
      createMarks({now: () => Date.parse(${JSON.stringify(now)}), liveMpaRead: async () => {
        const response = await fetch(${JSON.stringify(screen)});
        return {data: await response.json(), checkedAt: ${JSON.stringify(now)}};
      }, onError: layer => { if (layer === 'marks') errors++; }});
      window.d3Marks = () => ({verdict: marksAvailability.value,
        targets: markData.value?.atlas?.targets.length ?? 0, drape: terrainLayers.value.marks?.features.length ?? 0, errors});
    `}});
  return result.outputFiles[0]!.text;
}

// Whitespace-only edits preserve valid JSON and pre-admission counts. A
// second different byte pair proves neither valid alternate body can pass 4b.
function mutate(bytes: Buffer, byte: number) {
  const copy = Buffer.from(bytes), index = copy.findIndex(b => b === 10);
  if (index === -1) throw new Error('Missing fixture newline');
  copy[index] = byte;
  return copy;
}

export async function serveMarksArm(inputs: Inputs, arm: MarksArm, probe: string) {
  const paths: string[] = [], violations: string[] = [];
  const entries = new Map<string, [string, string | Buffer, number?]>([
    ['/map', ['text/html', '<!doctype html><script type="module" src="/probe.js"></script>']],
    ['/probe.js', ['text/javascript', probe]],
    [region, ['application/json', inputs.region]],
    [screen, ['application/json', JSON.stringify(boundaryFixture(inputs))]],
    [coverage, ['application/json', '{}']],
    [startup, ['application/json', arm === 'startup' ? inputs.startup : mutate(inputs.startup, arm === '4b' ? 9 : 32)]],
  ]);
  if (arm !== 'startup') entries.set(full, ['application/json', arm === '4b' ? mutate(inputs.full, 9) : arm === '4a-i' ? inputs.full : '', arm === '4a-ii' ? 404 : 200]);
  const server = createServer((req, res) => {
    const path = req.url?.split('?')[0] ?? '';
    paths.push(path);
    const response = req.method === 'GET' && entries.get(path);
    if (!response) {
      violations.push(path);
      return res.writeHead(404).end();
    }
    const [type, body, status = 200] = response;
    res.writeHead(status, {'Content-Type': type, 'Cache-Control': 'no-store'}).end(body);
  });
  try {
    await new Promise<void>((resolve, reject) => server.once('error', reject).listen(0, '127.0.0.1', resolve));
  } catch (error) { server.close(); throw error; }
  const origin = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
  return {origin, paths, violations, atlasPaths: () => paths.filter(p => p === startup || p === full),
    expectedAtlasPaths: arm === 'startup' ? [startup] : [startup, full],
    async fence(context: BrowserContext) {
      await context.route('**/*', route => {
        const url = new URL(route.request().url());
        if (url.origin === origin) return route.continue();
        violations.push('off-origin');
        return route.abort('blockedbyclient');
      });
    },
    close: () => new Promise<void>((resolve, reject) => server.close(error => error ? reject(error) : resolve())),
  };
}
