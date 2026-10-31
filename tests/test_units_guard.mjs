// RF1130-8: web/units.ts is the only web file that may spell a ft/m/kt/nmi conversion
// factor. Comments are ignored; a literal inside a longer number is not the factor.
import assert from 'node:assert/strict';
import {mkdirSync, mkdtempSync, readdirSync, readFileSync, writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join, relative, sep} from 'node:path';
import test from 'node:test';
import {fileURLToPath} from 'node:url';

const WEB = fileURLToPath(new URL('../web', import.meta.url));
const LITERAL =
  /(?<![\w.])(?:3\.2808\d*|1\.9438\d*|0?\.5144\d*|0?\.30480*|1\.8520*|1852(?:\.0*)?|6076(?:\.\d+)?)(?![\w.])/;

const strip = (src) =>
  src.replace(/\/\*[\s\S]*?\*\//g, (m) => m.replace(/[^\n]/g, ' ')).replace(/\/\/.*$/gm, '');

/** Every `file:line` under `root` (a web/ tree) with a conversion literal, except root/units.ts. */
export function scan(root) {
  const hits = [];
  for (const name of readdirSync(root, {recursive: true}).map(String).sort()) {
    if (!/\.tsx?$/.test(name) || name === 'units.ts') continue;
    const lines = strip(readFileSync(join(root, name), 'utf8')).split('\n');
    lines.forEach((line, i) => {
      if (LITERAL.test(line)) hits.push(`${relative(root, join(root, name)).split(sep).join('/')}:${i + 1}`);
    });
  }
  return hits;
}

test('units guard: no conversion literal in web/ outside web/units.ts', () => {
  assert.deepEqual(scan(WEB), []);
});

test('units guard: planted, comment, longer-number, units.ts and .tsx cases', () => {
  const root = mkdtempSync(join(tmpdir(), 'units-guard-'));
  mkdirSync(join(root, 'map'));
  const contrast = readFileSync(join(WEB, 'map/contrast.ts'), 'utf8');
  const planted = contrast.replace('1.8 * (M_PER_NMI / 1000)', '1.8 * 1.852');
  assert.notEqual(planted, contrast);
  writeFileSync(join(root, 'map/contrast.ts'), planted);
  const line = planted.split('\n').findIndex((l) => l.includes('1.8 * 1.852')) + 1;
  writeFileSync(join(root, 'units.ts'), 'export const M_PER_FT = 0.3048;\nexport const M_PER_NMI = 1852;\n');
  writeFileSync(join(root, 'map/units.ts'), 'export const FT = 1 / 0.3048;\n');
  writeFileSync(join(root, 'view.tsx'), 'export const kt = (ms: number) => ms * 1.943844;\n');
  writeFileSync(
    join(root, 'quiet.ts'),
    '// 1.852 km per nmi\n/* 3.28084\n 1852 */ export const a = 11.8520;\nexport const b = 0.30481 + 18520 + 21852;\n',
  );
  writeFileSync(join(root, 'loud.ts'), 'export const c = [3.280839895, .5144, 6076.12, 1852.0, 0.30480];\n');
  assert.deepEqual(scan(root), ['loud.ts:1', `map/contrast.ts:${line}`, 'map/units.ts:1', 'view.tsx:1']);
});
