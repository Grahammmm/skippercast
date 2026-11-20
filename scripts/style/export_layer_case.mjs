// Local, offline bridge. Cases delegate colour, sampling and age to the web code.
import {readFile, readdir, writeFile} from 'node:fs/promises';
import {join} from 'node:path';
import {parseArgs} from 'node:util';
import {readPalette, PALETTE_TOKENS} from '../../web/map/palette.ts';

const {values: args} = parseArgs({options: {
  case: {type: 'string'}, in: {type: 'string'}, out: {type: 'string'}, now: {type: 'string'},
  'palette-override': {type: 'string', multiple: true},
}});
const folder = new URL('./export_cases/', import.meta.url);
const module = `${args.case}.mjs`;
if (!args.in || !args.out || !(await readdir(folder)).includes(module)) {
  throw new Error('expected --case <installed case> --in <input directory> --out <output directory>');
}
const css = await readFile(new URL('../../web/tokens.css', import.meta.url), 'utf8');
// All SKL declarations are in :root. The other tokens are unused by the case,
// but reading them still exercises the normal CSS-to-palette validation.
const tokens = new Map([...css.matchAll(/^\s*--([\w-]+):\s*([^;]+);/gm)].map(([, k, v]) => [k, v.trim()]));
for (const override of args['palette-override'] ?? []) {
  const match = /^(--skl-[\w-]+)=(#[0-9a-f]{6})$/i.exec(override);
  if (!match || !Object.values(PALETTE_TOKENS).includes(match[1].slice(2))) throw new Error('invalid palette override');
  tokens.set(match[1].slice(2), match[2]);
}
const palette = readPalette(name => tokens.get(name) ?? '');
const input = JSON.parse(await readFile(join(args.in, 'case.json'), 'utf8'));
const readGrid = async name => {
  if (!/^[\w-]+\.f32$/.test(name)) throw new Error('invalid float32 grid name');
  const bytes = await readFile(join(args.in, name));
  if (bytes.length % 4) throw new Error('misaligned float32 grid');
  return Float32Array.from({length: bytes.length / 4}, (_, i) => bytes.readFloatLE(i * 4));
};
const {render} = await import(new URL(module, folder));
const {metrics, rgba} = await render(input, {palette, readGrid, now: args.now});
await writeFile(join(args.out, 'metrics.json'), JSON.stringify(metrics, null, 2) + '\n');
if (rgba) await writeFile(join(args.out, 'field.rgba'), new Uint8Array(rgba.buffer, rgba.byteOffset, rgba.byteLength));
