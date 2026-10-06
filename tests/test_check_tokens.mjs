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
import {BASELINE, compare, formatBaseline, grown, lint, lintFile, readBaseline, tally} from '../scripts/check_tokens.mjs';
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
