#!/usr/bin/env node
// Offline audit. Rebuild only the Vite client in memory to recover source-module
// names (the saved manifest has chunk names, not source-module membership).
import {readFile, writeFile} from 'node:fs/promises';
import {join, relative, resolve} from 'node:path';
import {gzipSync} from 'node:zlib';
import {transform} from 'esbuild';
import {build, parseAst} from 'vite';
import {clientConfig} from '../../vite.config.mjs';
import {APP_EARLY, appStartup} from '../../scripts/precache.mjs';

const [clientDir, reportPath, ...extra] = process.argv.slice(2);
if (!clientDir || !reportPath || extra.length) {
  throw Error('Usage: node research/scripts/catalogue_first_paint_ids.mjs <pnpm-build-client-dir> <new-report.json>');
}
const root = resolve(import.meta.dirname, '../..');
const read = file => readFile(join(root, file), 'utf8');
const manifest = JSON.parse(await readFile(join(clientDir, '.vite/manifest.json'), 'utf8'));
const bytes = text => Buffer.byteLength(text);
const sizes = data => ({rawBytes: bytes(data), gzipBytes: gzipSync(data, {level: 9}).length});
const sorted = xs => [...xs].sort();
const enPath = 'web/strings.en.generated.json';
const esPath = 'web/strings.es.generated.json';
const landingPath = 'web/landing/strings.generated.json';
const en = JSON.parse(await read(enPath));
const es = JSON.parse(await read(esPath));
const allIds = Object.keys(en);
const entryBytes = (id, value) => bytes(JSON.stringify(id)) + 1 + bytes(JSON.stringify(value));

function staticJs(roots) {
  const seen = new Set(), files = new Set();
  function visit(key) {
    if (seen.has(key)) return;
    seen.add(key);
    const entry = manifest[key];
    if (!entry) throw Error(`Missing manifest entry: ${key}`);
    if (entry.file.endsWith('.js')) files.add(entry.file);
    for (const next of entry.imports ?? []) visit(next);
  }
  roots.forEach(visit);
  return sorted(files);
}

const roots = appStartup(manifest);
if (!roots.includes('../web/app/main.tsx')) throw Error('Mandatory app shell is missing from the build');
const startup = staticJs(roots);
const rawBudgetGraph = staticJs(roots.filter(root => root !== APP_EARLY));
const spanish = staticJs(['../web/strings.es.generated.json']);
const chartHint = staticJs(['../web/map/maplibre.js']);
const config = clientConfig({root: join(root, 'dist')});
const chunkMembers = new Map();
const built = await build({configFile: false, ...config, logLevel: 'silent',
  build: {...config.build, write: false}, plugins: [...config.plugins, {
    name: 'catalogue-audit-chunk-members',
    generateBundle(_, bundle) {
      for (const item of Object.values(bundle)) {
        if (item.type === 'chunk') chunkMembers.set(item.fileName, item.moduleIds);
      }
    },
  }],
});
const output = new Map(built.output.map(item => [item.fileName, item.type === 'chunk' ? item.code : item.source]));
const replicaManifest = JSON.parse(output.get('.vite/manifest.json').toString());
if (JSON.stringify(replicaManifest) !== JSON.stringify(manifest)) throw Error('Manifest differs from source replay; run pnpm build again');
const chunkSizes = {};
for (const file of sorted(new Set([...startup, ...spanish, ...chartHint]))) {
  const actual = await readFile(join(clientDir, file));
  if (!actual.equals(Buffer.from(output.get(file)))) throw Error(`Built bytes differ from source replay: ${file}`);
  chunkSizes[file] = sizes(actual);
}

// Count each source module once per startup set, even if shared by both roots.
// themeBoot() emits a classic JS asset independently of the Vite module graph.
const sourcesFor = files => sorted(new Set(files.flatMap(file => {
  const ids = chunkMembers.get(file) ?? (file.startsWith('assets/theme-boot.') ? [join(root, 'web/theme-boot.ts')] : []);
  return ids.map(id => relative(root, id.split('?')[0])).filter(id =>
    /^(web|dist|packages)\//.test(id) && !id.split('/').includes('node_modules'));
})));
const modulePaths = sourcesFor(startup);
const chartOnly = chartHint.filter(file => !startup.includes(file));
const chartModules = sourcesFor(chartOnly).filter(path => !modulePaths.includes(path));

function walk(node, visit) {
  if (!node || typeof node !== 'object') return;
  if (typeof node.type === 'string') visit(node);
  for (const value of Object.values(node)) {
    if (Array.isArray(value)) value.forEach(child => walk(child, visit));
    else if (value?.type) walk(value, visit);
  }
}

// Catalogue IDs can be passed through a descriptor or lookup object, not just
// directly to t(). Take all exact code literals, and surface computed call
// arguments for review rather than silently treating them as zero IDs.
async function references(path) {
  const source = await read(path);
  const ts = /\.tsx?$/.test(path);
  const code = ts ? (await transform(source, {loader: path.endsWith('x') ? 'tsx' : 'ts'})).code : source;
  const ast = parseAst(code);
  const translators = new Set();
  const ids = new Set(), computed = new Set(), templates = new Map(), tableReaders = new Set();
  walk(ast, node => {
    if (node.type === 'ImportDeclaration' && /(?:^|\/)i18n\.ts$/.test(node.source.value)) {
      for (const spec of node.specifiers) {
        if (spec.imported?.name === 't') translators.add(spec.local.name);
        if (spec.imported?.name === 'STRINGS') tableReaders.add(spec.local.name);
      }
    }
  });
  walk(ast, node => {
    if (node.type === 'Literal' && typeof node.value === 'string' && Object.hasOwn(en, node.value)) ids.add(node.value);
    if (node.type === 'TemplateLiteral') {
      const prefix = node.quasis[0].value.cooked;
      if (!node.expressions.length && Object.hasOwn(en, prefix)) ids.add(prefix);
      if (node.expressions.length && prefix) {
        const candidates = allIds.filter(id => id.startsWith(prefix));
        if (candidates.length) templates.set(code.slice(node.start, node.end), sorted(candidates));
      }
    }
    if (node.type === 'CallExpression' && translators.has(node.callee.name) && node.arguments[0]) {
      const arg = node.arguments[0];
      if (arg.type !== 'Literal' || !Object.hasOwn(en, arg.value)) computed.add(code.slice(arg.start, arg.end));
    }
  });
  return {literalIds: sorted(ids), computed: sorted(computed), templateCandidates: Object.fromEntries(templates),
    tableReaders: sorted(tableReaders)};
}

async function inventory(paths) {
  const modules = {};
  for (const path of paths.filter(path => /\.[jt]sx?$/.test(path))) {
    modules[path] = await references(path);
  }
  return modules;
}
const modules = await inventory(modulePaths);
const conditionalChartModules = await inventory(chartModules);
const union = new Set(Object.values(modules).flatMap(row => row.literalIds));
const withTemplates = new Set([...union, ...Object.values(modules).flatMap(row => Object.values(row.templateCandidates).flat())]);
// Audited separately from literals: account-copy.ts:12–17 enumerates this
// namespace only when one of account.ts's two deferred dialog paths calls it.
const account = new Set(allIds.filter(id => id.startsWith('account.')));
const accountDialog = await references('dist/account.js');
function projection(ids) {
  return Object.fromEntries(allIds.filter(id => ids.has(id)).map(id => [id, en[id]]));
}
const english = ids => ({ids: ids.size, ...sizes(JSON.stringify(projection(ids)))});
const entries = Object.fromEntries(sorted(Object.keys(en)).map(id => [id,
  {enEntryBytes: entryBytes(id, en[id]), esEntryBytes: entryBytes(id, es[id])}]));
function sum(files) {
  return files.reduce((total, file) => ({rawBytes: total.rawBytes + chunkSizes[file].rawBytes,
    gzipBytes: total.gzipBytes + chunkSizes[file].gzipBytes}), {rawBytes: 0, gzipBytes: 0});
}
const report = {
  roots, startup: {...sum(startup), files: startup, sources: modulePaths},
  rawBudgetStartup: {rawBytes: sum(rawBudgetGraph).rawBytes, files: rawBudgetGraph},
  conditionalSpanish: {...sum(spanish.filter(file => !startup.includes(file))), files: spanish.filter(file => !startup.includes(file))},
  conditionalChartHint: {...sum(chartOnly), files: chartOnly, modules: conditionalChartModules},
  chunkSizes, englishPlacement: Object.fromEntries([enPath, esPath, landingPath].map(path =>
    [path, sorted([...chunkMembers].filter(([, ids]) => ids.includes(join(root, path))).map(([file]) => file))])),
  compactEnglish: {full: english(new Set(allIds)), startupLiterals: english(union),
    startupLiteralsAndTemplateCandidates: english(withTemplates),
    account: english(account), withoutAccount: english(new Set(allIds.filter(id => !account.has(id))))},
  accountSlice: {ids: sorted(account),
    startupLiteralOrTemplateOverlap: sorted([...account].filter(id => withTemplates.has(id))),
    idsNotFoundInDialog: sorted([...account].filter(id => !accountDialog.literalIds.includes(id)))},
  modules, entries,
};
for (const module of [...Object.values(modules), ...Object.values(conditionalChartModules)]) {
  const ids = new Set([...module.literalIds, ...Object.values(module.templateCandidates).flat()]);
  module.enLiteralEntryBytes = module.literalIds.reduce((n, id) => n + entries[id].enEntryBytes, 0);
  module.esLiteralEntryBytes = module.literalIds.reduce((n, id) => n + entries[id].esEntryBytes, 0);
  module.enWithTemplateCandidateEntryBytes = [...ids].reduce((n, id) => n + entries[id].enEntryBytes, 0);
  module.esWithTemplateCandidateEntryBytes = [...ids].reduce((n, id) => n + entries[id].esEntryBytes, 0);
}
const text = JSON.stringify(report, null, 2) + '\n';
await writeFile(reportPath, text, {flag: 'wx'});
console.log(text.trimEnd());
