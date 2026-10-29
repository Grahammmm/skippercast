// Full real Reports, loader and section modules; only App's UI host and the
// Reports useEffect scheduler are injected. No copied product algorithm.
import {build} from 'esbuild';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL, fileURLToPath} from 'node:url';
import {rendererPlugins} from '../../helpers/esbuild-url.mjs';
const ROOT = fileURLToPath(new URL('../../../', import.meta.url));
export const A = 'fixture/grounds-a.json', B = 'fixture/grounds-b.json';
export function grounds(label) {
  return {audit_date: '2026-10-01', grounds: [{label, reported_ground: label,
    precision: 'Named landmark vicinity', reports: [{date: '2026-09-30',
      boat: 'Synthetic Boat', species: ['lingcod', 'halibut'], source_url: 'https://reports.example/synthetic'}]}]};
}
export const response = value => new Response(JSON.stringify(value));
export function transport(calls = []) {
  return async url => {
    calls.push(String(url));
    if (url === A) return response(grounds('Synthetic A'));
    if (url === B) return response(grounds('Synthetic B'));
    if (String(url).startsWith('/feeds/')) return new Response('unavailable', {status: 503});
    throw new Error(`Unadmitted fixture URL: ${url}`);
  };
}
export async function load() {
  const out = join(await mkdtemp(join(tmpdir(), 'sp1605-module-')), 'entry.mjs');
  await build({entryPoints: [join(ROOT, 'tests/fixtures/sp1605_reports_source_key/entry.ts')],
    bundle: true, format: 'esm', platform: 'node', outfile: out, logLevel: 'silent',
    jsx: 'automatic', jsxImportSource: 'preact', plugins: [
      {name: 'sp1605-offline-ui-host', setup(b) {
        b.onResolve({filter: /App\.tsx$/}, args => args.importer.endsWith('/Reports.tsx') || args.importer.endsWith('/entry.ts')
          ? {path: 'app-host', namespace: 'sp1605'} : undefined);
        b.onResolve({filter: /^preact\/hooks$/}, args => args.importer.endsWith('/Reports.tsx')
          ? {path: join(ROOT, 'tests/fixtures/sp1605_reports_source_key/effects.ts')} : undefined);
        b.onLoad({filter: /.*/, namespace: 'sp1605'}, () => ({contents:
          "import {signal} from '@preact/signals'; export const regionInfo = signal(null);", resolveDir: ROOT}));
      }}, ...rendererPlugins]});
  return import(pathToFileURL(out).href);
}
export const labels = m => m.reportsData.peek()?.data.charters?.rows.map(r => r.label) ?? null;
export const flush = () => new Promise(resolve => setImmediate(resolve));
