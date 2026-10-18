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
import {BASELINE, COAST_BASELINE, SCOPES, collectCoastRoleCoverage, compare, formatBaseline, grown, lint, lintFile, readBaseline, sourceFiles, tally} from '../scripts/check_tokens.mjs';
import {BRIDGE, FILES, check, checkBridge} from '../scripts/check_contrast.mjs';

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
  const bridged = ['packages/coast/coast.css', 'packages/coast/panel.css', 'packages/coast/tokens-bridge.css', 'packages/coast/src/palette.ts',
    'packages/coast/src/coast3d/viewer.ts', 'packages/coast/src/charts/series.ts'];
  for (const file of bridged) {
    assert.deepEqual(findings.filter(f => f.file === file), [], file);
    assert.ok(![...baseline.keys()].some(k => JSON.parse(k)[0] === file), file);
  }
  assert.ok(SCOPES.some(s => s.dir === 'packages/coast' && s.baseline === COAST_BASELINE));
});

test('packages/coast/panel.css declares no custom property and reads only bridged roles (FE-77)', () => {
  const css = readFileSync(join(ROOT, 'packages/coast/panel.css'), 'utf8');
  assert.deepEqual(css.match(/(?:^|[{;\s])--[\w-]+\s*:/g) ?? [], []);
  const mapped = new Set([...readFileSync(join(ROOT, BRIDGE), 'utf8').matchAll(/^\s*(--coast-[\w-]+):/gm)].map(m => m[1]));
  // Legend ramps of layers v2 does not draw have no web/tokens.css ramp yet (tokens-bridge.css says so).
  const unmapped = [...new Set([...css.matchAll(/var\((--coast-[\w-]+),/g)].map(m => m[1]))].filter(role => !mapped.has(role));
  assert.deepEqual(unmapped.filter(role => !/^--coast-(?:reef|reef-fit|shore|current|wave|bathy)-\d$/.test(role)), []);
});

test('bridged coast text pairs reach 4.5:1 under the opt-in in both web/tokens.css themes', () => {
  const bridge = readFileSync(join(ROOT, BRIDGE), 'utf8'), tokens = readFileSync(join(ROOT, 'web/tokens.css'), 'utf8');
  assert.deepEqual(checkBridge(bridge, tokens).failures, []);
  const dim = bridge.replace('--coast-hover: color-mix(in srgb, var(--panel-2) 88%, var(--muted));', '--coast-hover: color-mix(in srgb, var(--panel-2) 60%, var(--muted));');
  assert.match(checkBridge(dim, tokens).failures.join('\n'), /dark: --coast-muted #[0-9a-f]{6} on --coast-hover/);
  assert.match(checkBridge(bridge.replace('--coast-coral: var(--coral);', ''), tokens).failures.join('\n'), /--coast-coral or --coast-panel does not resolve/);
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


test('auxiliary source CSS inventory covers advisor and coast-readable without generated assets or legacy JS', () => {
  const scopes = SCOPES.filter(s => s.cssOnly);
  assert.deepEqual(scopes.map(s => s.dir), ['dist/advisor', 'dist/coast-readable.css']);
  assert.ok(scopes.every(s => s.baseline === null));
  for (const scope of scopes) assert.deepEqual(lint(ROOT, scope.dir, scope.cssOnly), [], scope.dir);
  assert.deepEqual(scopes.flatMap(s => sourceFiles(ROOT, s.dir, s.cssOnly)), [
    'dist/advisor/admin.css', 'dist/advisor/chat.css', 'dist/advisor/pages.css',
    'dist/advisor/upload.css', 'dist/coast-readable.css',
  ]);
});

for (const file of ['dist/advisor/admin.css', 'dist/advisor/chat.css', 'dist/advisor/pages.css',
  'dist/advisor/upload.css', 'dist/advisor/nested/future.css', 'dist/coast-readable.css']) {
  test(`${file}: CLI rejects literals and fonts, accepts tokens, and --update cannot grandfather findings`, () => {
    const root = mkdtempSync(join(tmpdir(), 'token-lint-aux-'));
    try {
      mkdirSync(join(root, file, '..'), {recursive: true});
      mkdirSync(join(root, 'scripts'), {recursive: true});
      const empty = formatBaseline(new Map());
      writeFileSync(join(root, BASELINE), empty);
      writeFileSync(join(root, COAST_BASELINE), empty);
      // Nearby legacy JavaScript and generated client CSS are outside this scope.
      mkdirSync(join(root, 'dist/advisor'), {recursive: true});
      mkdirSync(join(root, 'dist/client/assets'), {recursive: true});
      writeFileSync(join(root, 'dist/advisor/legacy.js'), 'const color = "#fff";');
      writeFileSync(join(root, 'dist/client/assets/generated.css'), 'a{color:#fff}');
      const run = (...args) => spawnSync(process.execPath, [SCRIPT, ...args], {
        env: {...process.env, TOKEN_LINT_ROOT: root}, encoding: 'utf8', timeout: 10000,
      });
      for (const css of ['a{color:#fff}', 'a{font-family:Arial}']) {
        writeFileSync(join(root, file), css);
        const bad = run('--update');
        assert.equal(bad.status, 1, bad.stderr);
        assert.ok(bad.stderr.includes(`${file}:1`), bad.stderr);
        assert.match(bad.stderr, /has no baseline; fix the source/);
        assert.equal(readFileSync(join(root, BASELINE), 'utf8'), empty);
        assert.equal(readFileSync(join(root, COAST_BASELINE), 'utf8'), empty);
        assert.deepEqual(sourceFiles(root, 'scripts'), []);
      }
      writeFileSync(join(root, file), 'a{color:var(--text);font:var(--font-sans)}');
      const good = run();
      assert.equal(good.status, 0, good.stderr);
    } finally {
      rmSync(root, {recursive: true, force: true});
    }
  });
}

// N05 synthetic coverage only. The CLI intentionally does not invoke this helper
// until the sole integrator admits production composition and finite execution.
const coverageBridge = body => `[data-coast-theme="tokens"],\n:host([data-coast-theme="tokens"]) {\n${body}\n}`;
const coverageFixture = (source, bridge = '', file = 'packages/coast/a.css') => collectCoastRoleCoverage({
  [file]: source, 'packages/coast/tokens-bridge.css': bridge,
});

test('coast coverage requires declarations even when a required role has a fallback', () => {
  for (const value of ['var(--coast-missing)', 'var(--coast-missing,#fff)']) {
    const source = `.a{color:${value}}`;
    const missing = coverageFixture(source);
    assert.deepEqual(missing.uses.map(use => use.classification), ['unresolved']);
    assert.deepEqual(missing.findings, [{file: 'packages/coast/a.css', line: 1,
      rule: 'coast-role-undeclared', role: '--coast-missing', text: source}]);
    const covered = coverageFixture(source, coverageBridge('--coast-missing:var(--text);'));
    assert.deepEqual(covered.findings, []);
    assert.deepEqual(covered.uses.map(use => use.classification), ['declared']);
  }
});

test('coast coverage blanks comments and preserves each original use location', () => {
  const result = coverageFixture('/* var(--coast-comment)\nvar(--coast-comment) */\n  // var(--coast-comment)\n.a{color:var(--coast-missing)}',
    coverageBridge('/* --coast-missing:var(--text); */'));
  assert.equal(result.uses.length, 1);
  assert.equal(result.uses[0].line, 4);
  assert.equal(result.uses[0].column, 10);
  assert.equal(result.findings[0].role, '--coast-missing');
});

test('coast coverage ignores declaration LHS but checks its RHS var() reads', () => {
  assert.deepEqual(coverageFixture('', coverageBridge('--coast-unused:var(--text);')), {uses: [], findings: []});
  const result = coverageFixture('', coverageBridge('--coast-a:var(--coast-b);'));
  assert.deepEqual(result.uses.map(use => [use.role, use.classification]), [['--coast-b', 'unresolved']]);
  assert.equal(result.findings[0].file, 'packages/coast/tokens-bridge.css');
  assert.equal(result.findings[0].line, 3);
});

test('coast coverage declarations apply only in the canonical bridge opt-in block', () => {
  const use = '.a{color:var(--coast-missing)}';
  for (const bridge of [':root{--coast-missing:var(--text)}',
    '.other{--coast-missing:var(--text)}',
    '[data-coast-theme="tokens"], .other{--coast-missing:var(--text)}']) {
    assert.equal(coverageFixture(use, bridge).findings.length, 1);
  }
  const result = collectCoastRoleCoverage({
    'packages/coast/a.css': use,
    'packages/coast/other.css': coverageBridge('--coast-missing:var(--text);'),
    'web/tokens-bridge.css': coverageBridge('--coast-missing:var(--text);'),
  });
  assert.equal(result.findings.length, 1);
  assert.equal(result.findings[0].role, '--coast-missing');
});

// All 26 exact P09 allowances, retaining the six existing ramp families.
const coverageFallbackRoles = [
  '--coast-bathy-0', '--coast-bathy-1', '--coast-bathy-2', '--coast-bathy-3',
  '--coast-bathy-4', '--coast-bathy-5', '--coast-bathy-6',
  '--coast-current-0', '--coast-current-1', '--coast-current-2',
  '--coast-current-3', '--coast-current-4', '--coast-current-5',
  '--coast-reef-0', '--coast-reef-1', '--coast-reef-2', '--coast-reef-3', '--coast-reef-4',
  '--coast-reef-fit-0', '--coast-reef-fit-1',
  '--coast-shore-0', '--coast-shore-1', '--coast-shore-2',
  '--coast-wave-0', '--coast-wave-1', '--coast-wave-2',
];

test('coast coverage permits exactly the recorded panel ramps with nonempty fallbacks', () => {
  for (const role of coverageFallbackRoles) {
    const source = `.a{color:var(${role},#fff)}`;
    const result = coverageFixture(source, '', 'packages/coast/panel.css');
    assert.deepEqual(result.findings, [], role);
    assert.equal(result.uses[0].classification, 'explicitfallback', role);
    assert.equal(result.uses[0].hasFallback, true, role);
    assert.equal(coverageFixture(source).findings.length, 1, role);
    for (const value of [`var(${role})`, `var(${role},)`, `var(${role}, /* empty */ )`]) {
      const missing = coverageFixture(`.a{color:${value}}`, '', 'packages/coast/panel.css');
      assert.equal(missing.uses[0].classification, 'unresolved', value);
      assert.equal(missing.findings.length, 1, value);
    }
    assert.equal(coverageFixture(source, coverageBridge(`${role}:var(--text);`), 'packages/coast/panel.css')
      .uses[0].classification, 'declared', role);
  }
  for (const role of ['--coast-reef-9', '--coast-reef-10', '--coast-other-0']) {
    assert.equal(coverageFixture(`.a{color:var(${role},#fff)}`, '', 'packages/coast/panel.css').findings.length, 1, role);
  }
  const nested = coverageFixture('.a{color:var(--coast-reef-0,rgb(1 2 3))}', '', 'packages/coast/panel.css');
  assert.equal(nested.uses[0].classification, 'explicitfallback');
  const rhs = coverageFixture('.a{color:var(--coast-reef-0,var(--coast-missing))}', '', 'packages/coast/panel.css');
  assert.deepEqual(rhs.uses.map(use => use.classification), ['explicitfallback', 'unresolved']);
  assert.equal(rhs.findings[0].role, '--coast-missing');
});

test('coast coverage includes TS/TSX template reads and excludes the web scope', () => {
  for (const file of ['packages/coast/src/a.ts', 'packages/coast/src/a.tsx']) {
    const source = '`<rect style="fill:var(--coast-missing,#fff)"/>`';
    assert.equal(coverageFixture(source, '', file).findings.length, 1);
    assert.deepEqual(coverageFixture(source, coverageBridge('--coast-missing:var(--text);'), file).findings, []);
  }
  assert.deepEqual(collectCoastRoleCoverage({'web/a.css': '.a{color:var(--coast-missing)}',
    'packages/coast/a.json': 'var(--coast-missing)'}), {uses: [], findings: []});
});

test('coast coverage orders repeated diagnostics by path then source position', () => {
  const sources = {
    'packages/coast/z.css': '\n.z{color:var(--coast-z)}',
    'packages/coast/a.css': '.a{color:var(--coast-z);border:var(--coast-a)}\n.b{color:var(--coast-z)}',
  };
  const result = collectCoastRoleCoverage(sources);
  assert.deepEqual(result.uses.map(({file, line, column, role}) => [file, line, column, role]), [
    ['packages/coast/a.css', 1, 10, '--coast-z'],
    ['packages/coast/a.css', 1, 32, '--coast-a'],
    ['packages/coast/a.css', 2, 10, '--coast-z'],
    ['packages/coast/z.css', 2, 10, '--coast-z'],
  ]);
  assert.deepEqual(collectCoastRoleCoverage(Object.fromEntries(Object.entries(sources).reverse())), result);
});

test('coast coverage helper is independent of literal lint and baseline accounting', () => {
  const source = '.a{color:var(--coast-missing,#fff)}';
  const result = coverageFixture(source);
  assert.deepEqual(lintFile('packages/coast/a.css', source), []);
  const matchingBaseline = readBaseline(formatBaseline(tally(result.findings)));
  assert.deepEqual(compare(tally(result.findings), matchingBaseline), {added: [], stale: []});
  // Baseline acceptance cannot change helper classifications. CLI enforcement,
  // including --update non-bypass, remains deferred with the production gate.
  assert.deepEqual(coverageFixture(source), result);
  assert.equal(result.findings.length, 1);
});

// New retained-inventory composition controls. Existing helper/scanner tests
// remain unchanged; the focused pattern does not repeat their qualification.
import {createHash} from 'node:crypto';
import {checkCoastInventory, runCoastInventoryGate} from '../scripts/check_tokens.mjs';
const coverageDigest = text => createHash('sha256').update(text).digest('hex');
function inventoryCompositionFixture(role, binding = '--coast-text: var(--text);') {
  const file = 'packages/coast/example.css', bridge = 'packages/coast/tokens-bridge.css';
  const sources = {[file]: `var(${role}, #fff)`, [bridge]: `[data-coast-theme="tokens"], :host([data-coast-theme="tokens"]) {${binding}}`};
  const inventory = {production_inventory: {evidence: [{path: file, sha256: coverageDigest(sources[file])}]},
    evidence: [{path: bridge, sha256: coverageDigest(sources[bridge])}],
    production_used_role_matrix: [{role, classification: 'declared', occurrences: [{file, line: 1, column: 1, has_fallback: true}]}]};
  return {sources, inventory, file};
}
test('production inventory: declared occurrence passes; unsupported fallback reports path and role', () => {
  const good = inventoryCompositionFixture('--coast-text');
  assert.deepEqual(checkCoastInventory(good.sources, good.inventory).failures, []);
  const bad = inventoryCompositionFixture('--coast-unbound');
  assert.deepEqual(checkCoastInventory(bad.sources, bad.inventory).failures,
    [{file: bad.file, line: 1, column: 1, role: '--coast-unbound', rule: 'coast-role-undeclared'}]);
});
test('production inventory: stale source and unapproved inventory fail closed', () => {
  const {sources, inventory, file} = inventoryCompositionFixture('--coast-text');
  sources[file] += ' /* changed */';
  const result = checkCoastInventory(sources, inventory);
  assert.equal(result.failures[0].rule, 'coast-inventory-stale');
  assert.equal(result.uses.length, 0);
  assert.equal(runCoastInventoryGate(ROOT, JSON.stringify(inventory)).failures[0].rule, 'coast-inventory-unapproved');
});
test('production inventory: pinned production CLI pass/fail without baseline writes', {skip: !process.env.COAST_INVENTORY_FIXTURE}, () => {
  const inventoryPath = process.env.COAST_INVENTORY_FIXTURE;
  const before = [BASELINE, COAST_BASELINE].map(p => readFileSync(join(ROOT, p), 'utf8'));
  const invoke = args => spawnSync(process.execPath, [SCRIPT, ...args], {cwd: ROOT, env: {...process.env, TOKEN_LINT_ROOT: ROOT}, encoding: 'utf8'});
  const good = invoke(['--coast-inventory', inventoryPath]);
  assert.equal(good.status, 0, good.stderr + good.stdout);
  const result = JSON.parse(good.stdout);
  assert.equal(result.occurrences, 530);
  assert.deepEqual(result.failures, []);
  console.log('production inventory gate ' + good.stdout.trim());
  const temp = mkdtempSync(join(tmpdir(), 'coast-inventory-cli-'));
  try {
    const stale = join(temp, 'inventory.json');
    writeFileSync(stale, readFileSync(inventoryPath, 'utf8') + ' ');
    const bad = invoke(['--coast-inventory', stale]);
    assert.equal(bad.status, 1);
    assert.equal(JSON.parse(bad.stdout).failures[0].rule, 'coast-inventory-unapproved');
    const update = invoke(['--coast-inventory', inventoryPath, '--update']);
    assert.equal(update.status, 1);
    assert.match(update.stderr, /baselines are never updated/);
  } finally { rmSync(temp, {recursive: true, force: true}); }
  assert.deepEqual([BASELINE, COAST_BASELINE].map(p => readFileSync(join(ROOT, p), 'utf8')), before);
});
