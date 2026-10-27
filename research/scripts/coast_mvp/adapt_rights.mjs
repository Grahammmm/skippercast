// Offline C3 integration: adapt a C5 rights inventory (schema_version=1) into a
// C3 presentation manifest. No network, raster reads or C5 file writes.
// See README-viewer.md "Rights adapter".
import {createHash} from 'node:crypto';
import {existsSync, readFileSync, realpathSync, renameSync, rmSync, statSync, writeFileSync} from 'node:fs';
import {basename, dirname, join, resolve} from 'node:path';
import {parseArgs} from 'node:util';
import {adaptC5Rights} from '../../../packages/coast/src/coast3d/mvp-rights.ts';
import {isLocalAssetPath} from '../../../packages/coast/src/coast3d/mvp.ts';

// The file a path names after following every symlink, including symlinked parent directories.
// A missing leaf is joined to its real parent; a missing parent throws, which refuses the run.
function canonical(path) {
  const abs = resolve(path);
  return existsSync(abs) ? realpathSync(abs) : join(realpathSync(dirname(abs)), basename(abs));
}
// True when two paths name one file: same canonical path, or (for hard links) same device and inode.
function sameFile(x, y) {
  if (canonical(x) === canonical(y)) return true;
  if (!existsSync(x) || !existsSync(y)) return false;
  const [s, t] = [statSync(x), statSync(y)];
  return s.dev === t.dev && s.ino === t.ino;
}

const {values: a} = parseArgs({options: {
  inventory: {type: 'string'}, 'tile-base': {type: 'string'},
  'rights-page': {type: 'string'}, output: {type: 'string'},
}});
try {
  for (const k of ['inventory', 'tile-base', 'rights-page', 'output']) if (!a[k]) throw Error(`--${k} is required`);
  const output = resolve(a.output);
  // Same containment rules as the viewer, checked before any filesystem access.
  if (!isLocalAssetPath(a['rights-page'])) throw Error('rights page must be a relative file inside the manifest directory');
  const page = resolve(dirname(output), a['rights-page']);
  // Compare real files, not lexical paths: a symlinked parent or file, or a hard link, must not alias an input.
  if (sameFile(output, a.inventory) || sameFile(output, a['tile-base'])) throw Error('output must not overwrite an input');
  if (page === output || sameFile(output, page)) {
    throw Error('output must not overwrite the linked rights page');
  }
  // The complete C5 page must already sit beside the manifest; the viewer only links it.
  if (!existsSync(page)) throw Error('rights page not found beside the output manifest');
  const raw = readFileSync(a.inventory);
  const manifest = adaptC5Rights(JSON.parse(raw.toString('utf8')), JSON.parse(readFileSync(a['tile-base'], 'utf8')),
    {page: a['rights-page'], inventorySha256: createHash('sha256').update(raw).digest('hex')});
  // Atomic replace: a failed build leaves any previous manifest untouched.
  const tmp = output + '.tmp-' + process.pid;
  try { writeFileSync(tmp, JSON.stringify(manifest, null, 2) + '\n', {flag: 'wx'}); renameSync(tmp, output); }
  finally { rmSync(tmp, {force: true}); }
  const held = manifest.sources.filter(s => s.rights.status === 'needs_permission').map(s => s.id);
  console.log(`Built ${a.output}: ${manifest.sources.length} contributing sources; review_required; ` +
    `needs_permission: ${held.length ? held.join(', ') : 'none'}; not for navigation`);
} catch (error) {
  console.error('adapt_rights: ' + error.message);
  process.exit(2);
}
