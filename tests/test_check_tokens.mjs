// Token lint (FE-02, scripts/check_tokens.mjs): literals fail outside
// web/tokens.css, web/map/palette.ts is the only CSS-to-JS bridge, web/ is
// clean, and the baseline only shrinks. Also the v2 token file itself:
// contrast in both themes, self-hosted fonts with font-display: swap.
import test from 'node:test';
import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {BASELINE, COAST_BASELINE, SCOPES, compare, formatBaseline, grown, lint, lintFile, readBaseline, tally} from '../scripts/check_tokens.mjs';
import {FILES, check} from '../scripts/check_contrast.mjs';

const SCRIPT = new URL('../scripts/check_tokens.mjs', import.meta.url).pathname;
const ROOT = new URL('../', import.meta.url).pathname;
const rules = findings => findings.map(f => f.rule);

test('hex, rgb() and hsl() literals fail in CSS and TypeScript; comments are ignored', () => {
  assert.deepEqual(rules(lintFile('web/app/app.css', '.a { color: #fff; background: rgb(0 0 0 / 0.5); }')), ['colour-literal', 'colour-literal']);
  assert.deepEqual(rules(lintFile('web/app/App.tsx', "const fill = '#07131d'; const edge = `hsl(200 50% 50%)`;")), ['colour-literal', 'colour-literal']);
  assert.deepEqual(lintFile('web/app/App.tsx', "// bg is #07131d\n/* rgb(1 2 3) */ const id = '#map';"), []);
  assert.deepEqual(lintFile('web/app/app.css', '.a { color: var(--text); border: 1px solid var(--line); }'), []);
});

test('named colours fail only as CSS values; font-family only outside the tokens file', () => {
  assert.deepEqual(rules(lintFile('web/app/app.css', '.a { color: white; border: 1px solid red; }')), ['colour-literal', 'colour-literal']);
  assert.deepEqual(lintFile('web/app/app.css', '.a { stroke: currentColor; background: transparent; }'), []);
  assert.deepEqual(lintFile('web/brief/Brief.tsx', "const species = ['black rockfish', 'white seabass'];"), []);
  assert.deepEqual(rules(lintFile('web/app/app.css', '.a { font-family: Inter, sans-serif; }')), ['font-family']);
  assert.deepEqual(rules(lintFile('web/app/App.tsx', 'const s = {fontFamily: "Inter"};')), ['font-family']);
  assert.deepEqual(lintFile('web/tokens.css', ':root { --bg: #07131d; --font-sans: "DM Sans", sans-serif; }'), []);
  assert.deepEqual(lintFile('web/data.json', '{"c": "#fff"}'), []);
});

test('web/map/palette.ts is the only module that reads tokens into JavaScript', () => {
  const read = "export const bg = () => getComputedStyle(document.documentElement).getPropertyValue('--bg').trim();";
  assert.deepEqual(lintFile('web/map/palette.ts', read), []);
  assert.deepEqual(rules(lintFile('web/map/style.ts', read)), ['token-bridge']);
});

test('web/ passes with an empty baseline, and the baseline only shrinks', () => {
  const findings = lint(ROOT);
  assert.deepEqual(findings, []);
  const baseline = readBaseline(readFileSync(join(ROOT, BASELINE), 'utf8'));
  assert.equal(baseline.size, 0);
  const one = tally([{file: 'web/a.css', rule: 'colour-literal', text: 'color: #fff;'}]);
  assert.deepEqual(compare(one, new Map()).added, [...one.keys()]);
  assert.deepEqual(compare(new Map(), one).stale, [...one.keys()]);
  assert.deepEqual(grown(one, new Map()), [...one.keys()]);
  assert.deepEqual(grown(new Map(), one), []);
  assert.deepEqual(readBaseline(formatBaseline(one)), one);
});

test('the script fails on a fixture tree with a hex literal and passes once it uses a token', () => {
  const root = mkdtempSync(join(tmpdir(), 'token-lint-'));
  try {
    mkdirSync(join(root, 'web/app'), {recursive: true});
    mkdirSync(join(root, 'scripts'), {recursive: true});
    writeFileSync(join(root, BASELINE), formatBaseline(new Map()));
    writeFileSync(join(root, 'web/tokens.css'), ':root { --bg: #07131d; }\n');
    writeFileSync(join(root, 'web/app/app.css'), '.a { background: #07131d; }\n');
    const run = () => spawnSync(process.execPath, [SCRIPT], {env: {...process.env, TOKEN_LINT_ROOT: root}, encoding: 'utf8'});
    const bad = run();
    assert.equal(bad.status, 1);
    assert.match(bad.stderr, /web\/app\/app\.css:1 \[colour-literal\] \.a \{ background: #07131d; \}/);
    writeFileSync(join(root, 'web/app/app.css'), '.a { background: var(--bg); }\n');
    const good = run();
    assert.equal(good.status, 0, good.stderr);
    assert.match(good.stdout, /Token lint passed: 2 files, 0 finding\(s\)/);
  } finally {
    rmSync(root, {recursive: true, force: true});
  }
});

test('packages/coast: a literal passes only as a var(--coast-…) fallback or in src/palette.ts', () => {
  const css = 'packages/coast/coast.css';
  assert.deepEqual(rules(lintFile(css, '.a{color:#173b45;border:1px solid white;background:rgb(0 0 0)}')), ['colour-literal', 'colour-literal', 'colour-literal']);
  assert.deepEqual(lintFile(css, '.a{color:var(--coast-text,#173b45);border:1px solid var(--coast-line, white);box-shadow:0 1px var(--coast-shadow,rgb(0 0 0 / .2))}'), []);
  assert.deepEqual(rules(lintFile(css, '.a{color:var(--text,#173b45);background:var(--coast-panel,#fff) #000}')), ['colour-literal', 'colour-literal']);
  assert.deepEqual(rules(lintFile('web/app/app.css', '.a{color:var(--coast-text,#173b45)}')), ['colour-literal']);
  assert.deepEqual(lintFile(css, "@font-face{font-family:DM;src:url('a.woff2')}body{font-family:var(--coast-sans,DM,Arial,sans-serif)}"), []);
  assert.deepEqual(rules(lintFile(css, 'body{font-family:DM,Arial,sans-serif}')), ['font-family']);
  assert.deepEqual(rules(lintFile('web/app/app.css', '@font-face{font-family:DM}')), ['font-family']);
  assert.deepEqual(lintFile('packages/coast/src/palette.ts', "export const P = {ground: '#dce8e7'};"), []);
  assert.deepEqual(rules(lintFile('packages/coast/src/coast3d/viewer.ts', "new T.Color('#dce8e7')")), ['colour-literal']);
  assert.deepEqual(lintFile('packages/coast/src/charts/series.ts', '`<rect style="fill:var(--coast-night,#030d17)"/>`'), []);
});

test('packages/coast matches its seeded baseline; the bridged files have no findings and no entries', () => {
  const findings = lint(ROOT, 'packages/coast');
  const baseline = readBaseline(readFileSync(join(ROOT, COAST_BASELINE), 'utf8'));
  assert.deepEqual(compare(tally(findings), baseline), {added: [], stale: []});
  const bridged = ['packages/coast/coast.css', 'packages/coast/tokens-bridge.css', 'packages/coast/src/palette.ts',
    'packages/coast/src/coast3d/viewer.ts', 'packages/coast/src/charts/series.ts'];
  for (const file of bridged) {
    assert.deepEqual(findings.filter(f => f.file === file), [], file);
    assert.ok(![...baseline.keys()].some(k => JSON.parse(k)[0] === file), file);
  }
  assert.ok(SCOPES.some(s => s.dir === 'packages/coast' && s.baseline === COAST_BASELINE));
});

test('the script fails on a new literal in packages/coast and passes once it is a fallback', () => {
  const root = mkdtempSync(join(tmpdir(), 'token-lint-coast-'));
  try {
    mkdirSync(join(root, 'web'), {recursive: true});
    mkdirSync(join(root, 'packages/coast/src'), {recursive: true});
    mkdirSync(join(root, 'scripts'), {recursive: true});
    writeFileSync(join(root, BASELINE), formatBaseline(new Map()));
    writeFileSync(join(root, COAST_BASELINE), formatBaseline(new Map()));
    writeFileSync(join(root, 'packages/coast/coast.css'), 'body{background:#dce8eb}\n');
    const run = () => spawnSync(process.execPath, [SCRIPT], {env: {...process.env, TOKEN_LINT_ROOT: root}, encoding: 'utf8'});
    const bad = run();
    assert.equal(bad.status, 1);
    assert.match(bad.stderr, /packages\/coast\/coast\.css:1 \[colour-literal\] body\{background:#dce8eb\}/);
    writeFileSync(join(root, 'packages/coast/coast.css'), 'body{background:var(--coast-ground,#dce8eb)}\n');
    const good = run();
    assert.equal(good.status, 0, good.stderr);
    assert.match(good.stdout, /Token lint passed: 1 files, 0 finding\(s\).*\[packages\/coast\]/);
  } finally {
    rmSync(root, {recursive: true, force: true});
  }
});

test('web/tokens.css: every documented pair reaches 4.5:1 in dark and light; fonts are self-hosted and swap', () => {
  const css = readFileSync(join(ROOT, 'web/tokens.css'), 'utf8');
  const spec = FILES['web/tokens.css'];
  assert.deepEqual(check(css, spec).failures, []);
  const broken = css.replace('--muted: #8ba5b7;', '--muted: #5a7585;');
  assert.match(check(broken, spec).failures.join('\n'), /dark: --muted #5a7585 on --panel-2/);
  const faces = [...css.matchAll(/@font-face \{([\s\S]*?)\}/g)].map(m => m[1]);
  assert.equal(faces.length, 2);
  for (const face of faces) {
    assert.match(face, /font-display: swap;/);
    assert.match(face, /src: url\("\.\/fonts\/[a-z-]+\.woff2"\) format\("woff2"\);/);
  }
  assert.doesNotMatch(css, /fonts\.(?:googleapis|gstatic)\.com|https?:/);
});
