// Offline C3 integration: adapt a C5 rights inventory (schema_version=1) into a
// C3 presentation manifest. No network, raster reads or C5 file writes.
// See README-viewer.md "Rights adapter".
import {createHash} from 'node:crypto';
import {existsSync, readFileSync, renameSync, rmSync, writeFileSync} from 'node:fs';
import {dirname, resolve} from 'node:path';
import {parseArgs} from 'node:util';
import {adaptC5Rights} from '../../../packages/coast/src/coast3d/mvp-rights.ts';

const {values: a} = parseArgs({options: {
  inventory: {type: 'string'}, 'tile-base': {type: 'string'},
  'rights-page': {type: 'string'}, output: {type: 'string'},
}});
try {
  for (const k of ['inventory', 'tile-base', 'rights-page', 'output']) if (!a[k]) throw Error(`--${k} is required`);
  const output = resolve(a.output);
  if ([resolve(a.inventory), resolve(a['tile-base'])].includes(output)) throw Error('output must not overwrite an input');
  // The complete C5 page must already sit beside the manifest; the viewer only links it.
  if (!existsSync(resolve(dirname(output), a['rights-page']))) throw Error('rights page not found beside the output manifest');
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
