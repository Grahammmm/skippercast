// RF1130-8: web/units.ts is the only web file that may spell a ft/m/kt/nmi conversion
// factor. Comments are ignored; a literal inside a longer number is not the factor.
// RF1949-1: the same holds for the hand-written dist/*.js modules (top level only; dist/data/
// and other sub-folders are data or vendored bundles, not code we wrote).
import assert from 'node:assert/strict';
import {mkdirSync, mkdtempSync, readdirSync, readFileSync, writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join, relative, sep} from 'node:path';
import test from 'node:test';
import util from 'node:util';
import {fileURLToPath} from 'node:url';

const WEB = fileURLToPath(new URL('../web', import.meta.url));
const DIST = fileURLToPath(new URL('../dist', import.meta.url));
const LITERAL =
  /(?<![\w.])(?:3\.2808\d*|1\.9438\d*|0?\.5144\d*|0?\.30480*|1\.8520*|1852(?:\.0*)?|6076(?:\.\d+)?)(?![\w.])/;

const strip = (src) =>
  src.replace(/\/\*[\s\S]*?\*\//g, (m) => m.replace(/[^\n]/g, ' ')).replace(/\/\/.*$/gm, '');

// RF0325-7: compare on a copy with digit_digit separators removed (1_852 -> 1852); no newline is removed.
const unseparate = (src) => src.replace(/(?<=[0-9])_(?=[0-9])/g, '');

const hitsIn = (root, names, skip) => {
  const hits = [];
  for (const name of names) {
    if (name === skip) continue;
    const lines = unseparate(strip(readFileSync(join(root, name), 'utf8'))).split('\n');
    lines.forEach((line, i) => {
      if (LITERAL.test(line)) hits.push(`${relative(root, join(root, name)).split(sep).join('/')}:${i + 1}`);
    });
  }
  return hits;
};

/** Every `file:line` under `root` (a web/ tree) with a conversion literal, except root/units.ts. */
export function scan(root) {
  const names = readdirSync(root, {recursive: true}).map(String).sort();
  return hitsIn(root, names.filter((n) => /\.tsx?$/.test(n)), 'units.ts');
}

/** Same for the `*.js` files directly in `root` (a dist/ folder); sub-folders are not scanned. */
export function scanDist(root) {
  const names = readdirSync(root, {withFileTypes: true})
    .filter((e) => e.isFile() && e.name.endsWith('.js'))
    .map((e) => e.name)
    .sort();
  return hitsIn(root, names, null);
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

test('units guard: no conversion literal in dist/*.js', () => {
  assert.deepEqual(scanDist(DIST), []);
});

test('units guard: dist planted, comment, longer-number and dist/data cases', () => {
  const root = mkdtempSync(join(tmpdir(), 'units-guard-dist-'));
  mkdirSync(join(root, 'data'));
  writeFileSync(join(root, 'x.js'), 'export const kt = (v) => v * 1.943844;\n');
  writeFileSync(
    join(root, 'quiet.js'),
    '// v * 1.943844\nexport const a = 11.943844;\n/* 3.28084 */ export const b = 1;\n',
  );
  writeFileSync(join(root, 'data/feed.js'), 'export const c = 3.28084;\n');
  writeFileSync(join(root, 'notes.txt'), '1.943844\n');
  assert.deepEqual(scanDist(root), ['x.js:1']);
});

// RF0325-7: numeric separators (1_852, 1.943_844) are the same literal; compare on a copy with
// digit_digit underscores removed. Line numbers and file bytes are unchanged.
const SEPARATED = [
  'export const a = 1.943_844;\n',
  'export const b = 3.280_84 + 0.51_44;\n',
  'export const c = [0.30_48, 1.8_52, 1_852, 6_076.12];\n',
  'export const d = 1_8_5_2;\n',
  'export const e = 0.30_480_0 + 1_852.0_0;\n',
  'export const f = 3.280_841;\n',
];
const NEAR_MISS = [
  '// 1_852 and 1.943_844\n/* 3.280_84\n 0.30_48 */ export const a = 1;\n',
  'export const b = [11.852_0, 0.304_81, 18_520, 13.280_84, v1_852, 1_852n, 0x7_3c, 1_852e2, 1__852, 1_ 852, 1 _852];\n',
  'const _1_852 = 1;\nconst x1_852 = 2;\n',
];

const plantSeparators = (root, ext) => {
  SEPARATED.forEach((src, i) => writeFileSync(join(root, `sep${i}.${ext}`), `\n${src}`));
  NEAR_MISS.forEach((src, i) => writeFileSync(join(root, `quiet${i}.${ext}`), src));
  writeFileSync(join(root, `ws.${ext}`), 'const k = 1_852 ;\n/* x\n y */ const m = 6_076;\n');
};
const SEP_HITS = (ext) => [
  ...[0, 1, 2, 3, 4, 5].map((i) => `sep${i}.${ext}:2`),
  `ws.${ext}:1`,
  `ws.${ext}:3`,
];

test('units guard: numeric-separator spellings are caught in web/ and dist/, one hit per line', () => {
  const web = mkdtempSync(join(tmpdir(), 'units-guard-sep-web-'));
  mkdirSync(join(web, 'map'));
  plantSeparators(web, 'ts');
  writeFileSync(join(web, 'units.ts'), 'export const M_PER_NMI = 1_852;\n');
  writeFileSync(join(web, 'map/units.ts'), 'export const FT = 3.280_84;\n');
  writeFileSync(join(web, 'v.tsx'), 'export const kt = 1.943_844;\n');
  assert.ok(
    util.isDeepStrictEqual(scan(web), [...SEP_HITS('ts'), 'map/units.ts:1', 'v.tsx:1'].sort()),
    `web hits: ${JSON.stringify(scan(web))}`,
  );
  const dist = mkdtempSync(join(tmpdir(), 'units-guard-sep-dist-'));
  mkdirSync(join(dist, 'data'));
  plantSeparators(dist, 'js');
  writeFileSync(join(dist, 'data/feed.js'), 'export const c = 3.280_84;\n');
  writeFileSync(join(dist, 'notes.txt'), '1_852\n');
  const before = readFileSync(join(dist, 'sep0.js'), 'utf8');
  assert.ok(util.isDeepStrictEqual(scanDist(dist), SEP_HITS('js').sort()), `dist hits: ${JSON.stringify(scanDist(dist))}`);
  assert.equal(readFileSync(join(dist, 'sep0.js'), 'utf8'), before);
});
