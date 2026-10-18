// The required contrast CI step runs this focused gate. Keep opaque checks,
// then explicitly invoke the independently reviewed --surface-source proof.
// The generic CLI remains a separate fail-closed interface for unresolved input.
import test from 'node:test';
import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {readFileSync, writeFileSync, mkdirSync, mkdtempSync, realpathSync, rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {dirname, join} from 'node:path';
import {fileURLToPath} from 'node:url';
import {FILES, PAIRS_BRIDGE, check, checkBridge, themes, SURFACE_SOURCE_SHA256} from '../scripts/check_contrast.mjs';

const ROOT = fileURLToPath(new URL('../', import.meta.url));
const SCRIPT = 'scripts/check_contrast.mjs';
const read = path => readFileSync(join(ROOT, path), 'utf8');
const SOURCES = {panelCss: 'packages/coast/panel.css', bridgeCss: 'packages/coast/tokens-bridge.css',
  tokensCss: 'web/tokens.css', appCss: 'web/app/app.css', legendTsx: 'web/app/Legend.tsx'};
const cli = (cwd, args) => {
  const result = spawnSync(process.execPath, [SCRIPT, ...args], {cwd, encoding: 'utf8', timeout: 10000});
  assert.equal(result.error, undefined);
  assert.equal(result.signal, null);
  return result;
};

// One sequential case: the first failed assertion aborts all later phases.
test('required contrast CI adopts pinned surface proof and keeps every failure gate', () => {
  const workflow = read('.github/workflows/ci.yml');
  assert.match(workflow, /- name: Design token contrast \(WCAG 4\.5:1, light and dark\)\n\s+run: node --test tests\/test_contrast_ci_adoption\.mjs\n/);

  let opaquePairs = 0;
  for (const [file, spec] of Object.entries(FILES)) {
    const css = read(file), result = check(css, spec);
    assert.deepEqual(result.failures, [], file);
    assert.equal(result.rows.length, 2 * spec.pairs.length);
    opaquePairs += result.rows.length;
    // Keep real source checks sensitive to a foreground/background equality.
    const [foreground, background] = spec.pairs[0];
    const colors = themes(css, spec)[spec.base];
    const bad = css.replace(new RegExp(`(--${foreground}:\\s*)#[0-9a-fA-F]{6}`), `$1${colors[background]}`);
    assert.notEqual(bad, css);
    assert.ok(check(bad, spec).failures.length > 0, file + ' equality must fail');
  }
  const bridge = read(SOURCES.bridgeCss), tokens = read(SOURCES.tokensCss);
  const bridged = checkBridge(bridge, tokens);
  assert.deepEqual(bridged.failures, []);
  assert.equal(bridged.rows.length, 2 * PAIRS_BRIDGE.length);
  opaquePairs += bridged.rows.length;
  assert.equal(opaquePairs, 112);
  assert.ok(checkBridge(bridge.replace('--coast-text: var(--text);', '--coast-text: var(--panel);'), tokens).failures.length > 0);

  // Run the real approved explicit CLI, without importing/rerunning its math suite.
  const accepted = cli(ROOT, ['--surface-source']);
  assert.equal(accepted.status, 0, accepted.stderr);
  const proof = JSON.parse(accepted.stdout);
  assert.deepEqual(proof.hashes, SURFACE_SOURCE_SHA256);
  assert.deepEqual(proof.failures, []);
  assert.equal(proof.rendered, false);
  assert.equal(proof.results.length, 12);
  assert.equal(new Set(proof.results.map(r => r.theme + ':' + r.id)).size, 12);
  assert.ok(proof.results.every(r => r.status === 'source_pass' && r.lowerBound >= 4.5));
  console.log('CI adoption accepted: ' + JSON.stringify({opaquePairs, sourceCases: proof.results.length, sourceHashes: proof.hashes}));

  const scratch = realpathSync(mkdtempSync(join(tmpdir(), 'contrast-ci-adoption-')));
  try {
    for (const path of [SCRIPT, ...Object.values(SOURCES), 'dist/tokens.css']) {
      mkdirSync(dirname(join(scratch, path)), {recursive: true});
      writeFileSync(join(scratch, path), read(path));
    }
    // Current source files alone never make the generic unresolved CLI pass.
    const unresolved = cli(scratch, []);
    assert.equal(unresolved.status, 1);
    assert.equal(unresolved.stdout, '');
    assert.match(unresolved.stderr, /Transparent contrast check failed/);
    assert.equal((unresolved.stderr.match(/missing_background_evidence/g) || []).length, 8);
    assert.doesNotMatch(unresolved.stderr, /measured_failure|resolution_error|below 4\.5/);
    console.log('CI adoption negative: generic unresolved CLI exits1 with eight missing-evidence results');

    // Whole-file binding includes new later CSS overrides, not only known roles.
    writeFileSync(join(scratch, SOURCES.appCss), read(SOURCES.appCss) + '\n.app-legend {opacity:.1}\n');
    const changed = cli(scratch, ['--surface-source']);
    assert.equal(changed.status, 1);
    const rejected = JSON.parse(changed.stdout);
    assert.equal(rejected.failures.length, 1);
    assert.equal(rejected.results.length, 1);
    assert.equal(rejected.failures[0].status, 'resolution_error');
    assert.match(rejected.failures[0].reason, /Surface source binding changed: appCss/);
    assert.equal(rejected.results.some(r => r.status === 'source_pass'), false);
    console.log('CI adoption negative: changed source binding exits1 without source_pass');

    // Missing inputs must fail, with no fallback to a subset or old pass receipt.
    rmSync(join(scratch, SOURCES.appCss));
    const missing = cli(scratch, ['--surface-source']);
    assert.equal(missing.status, 1);
    assert.equal(missing.stdout, '');
    assert.match(missing.stderr, /ENOENT/);
    console.log('CI adoption negative: missing required source exits1 without output');
  } finally {
    rmSync(scratch, {recursive: true, force: true});
  }
});
