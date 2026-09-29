#!/usr/bin/env node
// After `pnpm build`: every page, script and stylesheet in dist/client must be
// fingerprinted, and every local reference between them must resolve.
import {readdir, readFile} from 'node:fs/promises';
import {join} from 'node:path';
import {STABLE} from './fingerprint.mjs';

const dir = process.argv[2] || 'dist/client';
const files = (await readdir(dir, {withFileTypes: true})).filter(e => e.isFile()).map(e => e.name);
const assets = files.filter(n => /\.(?:js|css|html)$/.test(n));
const problems = [];
const hashedName = n => /\.[0-9a-f]{10}\.(?:js|css|html)$/.test(n);
const unhashed = assets.filter(n => !hashedName(n) && !STABLE.has(n));
// Original names that were renamed, e.g. app.js -> app.0123456789.js.
const renamed = new Set(assets.filter(hashedName).map(n => n.replace(/\.[0-9a-f]{10}(\.(?:js|css|html))$/, '$1')));
if (unhashed.length) problems.push(`not fingerprinted: ${unhashed.join(', ')}`);
const present = new Set(files);
for (const name of assets) {
  const text = await readFile(join(dir, name), 'utf8');
  for (const [, ref] of text.matchAll(/["'`(](?:\.\/)?([A-Za-z0-9_-][A-Za-z0-9_.-]*\.(?:js|css|html))(?:\?[^"'`)]*)?(?=["'`)#])/g)) {
    const hashed = /\.[0-9a-f]{10}\.(?:js|css|html)$/.test(ref);
    if (hashed && !present.has(ref)) problems.push(`${name} -> ${ref} (missing)`);
    if (!hashed && present.has(ref) && !STABLE.has(ref)) problems.push(`${name} -> ${ref} (unhashed reference)`);
  }
  // Root-relative references ('/app.js') are not rewritten by the fingerprint
  // step, so one pointing at a renamed file would 404 in production.
  for (const [, ref] of text.matchAll(/["'`(]\/([A-Za-z0-9_-][A-Za-z0-9_.-]*\.(?:js|css|html))(?:\?[^"'`)]*)?(?=["'`)#])/g)) {
    if (!present.has(ref) && renamed.has(ref)) problems.push(`${name} -> /${ref} (root-relative reference to a fingerprinted file; use a relative name or add it to STABLE)`);
  }
}
const imports = [];
for (const name of assets.filter(n => n.endsWith('.js'))) {
  const text = await readFile(join(dir, name), 'utf8');
  for (const [, spec] of text.matchAll(/(?:from\s*|import\s*\(\s*)["'](\.\/[^"']+)["']/g)) {
    imports.push(spec);
    const file = spec.slice(2).split('?')[0];
    const exists = present.has(file) || (file.includes('/') && await readFile(join(dir, file)).then(() => true, () => false));
    if (!exists) problems.push(`${name} imports ${spec} (missing)`);
  }
}
if (problems.length) {
  console.error(`Client check failed:\n  ${problems.join('\n  ')}`);
  process.exit(1);
}
console.log(`Client check passed: ${assets.length - STABLE.size} fingerprinted assets, ${STABLE.size} stable, ${imports.length} module imports resolve.`);
