// Full staged modules, not a copied implementation or planner-extracted function.
import './offline.mjs';
import {readFileSync} from 'node:fs';
import {createHash} from 'node:crypto';
const fixture = process.argv[2];
if (!fixture) throw Error('fixture path required');
const ids = await import('../../../server/fleet/ids.ts');
const rows = [];
for (const item of JSON.parse(readFileSync(fixture, 'utf8')).cases) {
  const text = ids.canonicalJson(item.value);
  rows.push({id: item.id, text, utf8_hex: Buffer.from(text, 'utf8').toString('hex'), value_key: await ids.valueKey(item.value)});
}
console.log(JSON.stringify({runtime: {version: process.version, executable: process.execPath},
  source: 'server/fleet/ids.ts', source_sha256: createHash('sha256').update(readFileSync(new URL('../../../server/fleet/ids.ts', import.meta.url))).digest('hex'), rows}));
