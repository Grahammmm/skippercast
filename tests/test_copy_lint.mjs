// Copy lint (P4-04, scripts/check_copy.mjs): the rules, the disclosure
// containers, and the baseline that only shrinks.
import test from 'node:test';
import assert from 'node:assert/strict';
import {execFileSync, spawnSync} from 'node:child_process';
import {mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {
  BASELINE, compare, formatBaseline, grown, htmlUnits, lint, lintFile, literals, readBaseline, sentences, tally, unitFindings,
} from '../scripts/check_copy.mjs';

const SCRIPT = new URL('../scripts/check_copy.mjs', import.meta.url).pathname;
const rules = findings => findings.map(f => f.rule);

test('two consecutive "not" sentences are flagged; one, or two apart, are not', () => {
  assert.deepEqual(rules(unitFindings('This is not a chart. It is not a route.')), ['consecutive-not']);
  assert.deepEqual(rules(unitFindings('This is not a chart. Check your chart. It is not a route.')), []);
  assert.deepEqual(rules(unitFindings('Knots are shown. Nothing is hidden.')), []);
  assert.deepEqual(sentences('One. Two? 3 three! “Four.”'), ['One.', 'Two?', '3 three!', '“Four.”']);
});

test('method names are flagged outside disclosures only', () => {
  assert.deepEqual(rules(unitFindings('Depths are in MLLW here.')), ['method-name']);
  assert.deepEqual(rules(unitFindings('The source datum shown on this map.')), ['method-name']);
  // A caveat that names a method is allowed (see the caveat test below).
  assert.deepEqual(rules(unitFindings('The source datum is unverified today.')), []);
  assert.deepEqual(rules(unitFindings('GFS and ECMWF agree on wind.')), ['method-name']);
  assert.deepEqual(rules(unitFindings('Depths are in MLLW here.', {disclosure: true})), []);
  assert.deepEqual(rules(unitFindings('Depths are in MLLW here.', {methodsAllowed: true})), []);
  // Lower-case identifiers such as model ids are not copy.
  assert.deepEqual(rules(unitFindings('uses the gfs025 grid today')), []);
});

test('<details> bodies and confidence-why are disclosures; <summary> is not', () => {
  const units = htmlUnits('<p>Depths use MLLW here.</p><details><summary>How MLLW works here</summary><p>Depths use MLLW here.</p></details><span class="confidence-why">Vertical datum is MLLW here.</span>');
  assert.deepEqual(units.map(u => [u.text, u.disclosure]), [
    ['Depths use MLLW here.', false], ['How MLLW works here', false], ['Depths use MLLW here.', true], ['Vertical datum is MLLW here.', true],
  ]);
  // Inline tags do not split a unit; block tags do.
  assert.deepEqual(htmlUnits('<p><strong>Lead.</strong> Then more.</p><p>Next</p>').map(u => u.text), ['Lead. Then more.', 'Next']);
  assert.deepEqual(htmlUnits('<script>const datum = "MLLW here and there";</script><p>Fine words here</p>').map(u => u.text), ['Fine words here']);
});

test('literals come out of strings and templates, not comments or regular expressions', () => {
  const values = literals(`// "comment text is not copy"
const a = 'it\\'s one', b = /"not a string"/g, c = \`two \${'inner'} three\`;
/* 'nor this' */ const d = "Morro\\u2013Avila";`).map(l => l.value);
  assert.deepEqual(values, ["it's one", 'two  X  three', 'inner', 'Morro–Avila']);
});

test('legal pages are skipped; disclosure pages allow method names but not "not" pairs', () => {
  const copy = '<p>Depths are in MLLW here. This is not a chart. It is not a route.</p>';
  assert.deepEqual(lintFile('dist/terms.html', copy), []);
  assert.deepEqual(rules(lintFile('dist/sources.html', copy)), ['consecutive-not']);
  assert.deepEqual(rules(lintFile('dist/index.html', copy)), ['consecutive-not', 'method-name']);
  assert.deepEqual(rules(lintFile('web/disclaimers.ts', `export const X = '${'Depths are in MLLW here.'}';`)), []);
  // Developer messages are not user copy.
  assert.deepEqual(lintFile('dist/x.js', `console.error('GFS data is not ready. It is not loaded.');`), []);
});

test('the committed baseline matches the repository exactly', () => {
  const {added, stale} = compare(tally(lint()), readBaseline(readFileSync(new URL(`../${BASELINE}`, import.meta.url), 'utf8')));
  assert.deepEqual(added, [], 'new copy findings: fix the copy, do not add them to the baseline');
  assert.deepEqual(stale, [], 'fixed findings still listed: run node scripts/check_copy.mjs --update');
});

test('the moved spot-sheet caveat is no longer a finding', () => {
  const baseline = readFileSync(new URL(`../${BASELINE}`, import.meta.url), 'utf8');
  assert.doesNotMatch(baseline, /The displayed depths are not chart depths/);
  assert.doesNotMatch(baseline, /"file":"web\/disclaimers\.ts"/);
});

test('caveats may name methods; generated region data is not app copy', () => {
  assert.deepEqual(unitFindings('Their source depth datum is unverified.'), []);
  assert.deepEqual(unitFindings('Validate the original source datum before fishing-target promotion.'), []);
  assert.deepEqual(unitFindings('NOAA GFS forecast unavailable here.'), []);
  assert.equal(unitFindings('NOAA GFS and ECMWF IFS at regional sea-grid samples.').length, 1);
  assert.deepEqual(lintFile('dist/region-default.js', 'const n = "NOAA GFS and ECMWF IFS at regional sea-grid samples.";'), []);
});

test('an edited sentence pairs with its stale entry in the same file and rule only', () => {
  const old = tally([{file: 'a', rule: 'r', text: 'old'}]);
  const edited = tally([{file: 'a', rule: 'r', text: 'new'}]);
  const elsewhere = tally([{file: 'b', rule: 'r', text: 'new'}]);
  assert.deepEqual(compare(edited, old).added, []);
  assert.equal(compare(edited, old).replaced.length, 1);
  assert.equal(compare(elsewhere, old).added.length, 1);
  assert.deepEqual(grown(edited, old), []);
});

test('compare and grown report additions and removals as multisets', () => {
  const one = tally([{file: 'a', rule: 'r', text: 't'}]);
  const two = tally([{file: 'a', rule: 'r', text: 't'}, {file: 'a', rule: 'r', text: 't'}]);
  assert.equal(compare(two, one).added.length, 1);
  assert.equal(compare(one, two).stale.length, 1);
  assert.deepEqual(grown(one, two), []);
  assert.equal(grown(two, one).length, 1);
  assert.deepEqual(readBaseline(formatBaseline(two)), two);
});

test('the baseline only shrinks: new findings fail, fixes must be removed, --update never adds, --base catches growth', () => {
  const root = mkdtempSync(join(tmpdir(), 'copy-lint-'));
  try {
    mkdirSync(join(root, 'dist')); mkdirSync(join(root, 'web')); mkdirSync(join(root, 'scripts'));
    const page = body => writeFileSync(join(root, 'dist', 'index.html'), `<main>${body}</main>`);
    const run = (...args) => spawnSync(process.execPath, [SCRIPT, ...args], {env: {...process.env, COPY_LINT_ROOT: root}, encoding: 'utf8'});
    const baseline = () => readBaseline(readFileSync(join(root, BASELINE), 'utf8'));
    const git = (...args) => execFileSync('git', ['-c', 'user.name=t', '-c', 'user.email=t@example.com', ...args], {cwd: root, stdio: 'ignore'});

    // Today's copy: one old finding, listed in the baseline.
    page('<p>Old copy mentions MLLW depths.</p>');
    writeFileSync(join(root, BASELINE), formatBaseline(tally([{file: 'dist/index.html', rule: 'method-name', text: 'Old copy mentions MLLW depths.'}])));
    assert.equal(run().status, 0);
    git('init', '-q'); git('add', '-A'); git('commit', '-qm', 'base');

    // A new finding fails, and --update does not add it.
    page('<p>Old copy mentions MLLW depths.</p><p>New copy is not great. It is not short.</p>');
    const added = run();
    assert.equal(added.status, 1);
    assert.match(added.stderr, /1 new finding\(s\)[\s\S]*dist\/index\.html:1 \[consecutive-not\]/);
    assert.equal(run('--update').status, 1);
    assert.equal(baseline().size, 1);

    // Adding it to the baseline by hand passes the local check but fails against the base branch.
    const grownBaseline = formatBaseline(tally([
      {file: 'dist/index.html', rule: 'method-name', text: 'Old copy mentions MLLW depths.'},
      {file: 'dist/index.html', rule: 'consecutive-not', text: 'New copy is not great. It is not short.'},
    ]));
    writeFileSync(join(root, BASELINE), grownBaseline);
    assert.equal(run().status, 0);
    const base = run('--base', 'HEAD');
    assert.equal(base.status, 1);
    assert.match(base.stderr, /more entries than at HEAD for 1 file\/rule pair[\s\S]*dist\/index\.html \[consecutive-not\] \+1/);

    // Fixing copy leaves a stale entry, which fails until --update removes it.
    page('<p>Depths are from the survey.</p>');
    writeFileSync(join(root, BASELINE), formatBaseline(tally([{file: 'dist/index.html', rule: 'method-name', text: 'Old copy mentions MLLW depths.'}])));
    const stale = run();
    assert.equal(stale.status, 1);
    assert.match(stale.stderr, /no longer occurs; the baseline only shrinks/);
    assert.equal(run('--update').status, 0);
    assert.equal(baseline().size, 0);
    assert.equal(run('--base', 'HEAD').status, 0);
    git('add', '-A'); git('commit', '-qm', 'fixed');

    // Editing a baselined sentence (typo, number) is a replacement: no new-finding failure,
    // --update records the new wording, and the per-file count does not grow against the base.
    page('<p>Old copy mentions MLLW depths.</p>');
    writeFileSync(join(root, BASELINE), formatBaseline(tally([{file: 'dist/index.html', rule: 'method-name', text: 'Old copy mentions MLLW depths.'}])));
    git('add', '-A'); git('commit', '-qm', 'restore');
    page('<p>Old copy mentions MLLW depth.</p>');
    const edited = run();
    assert.equal(edited.status, 1);
    assert.doesNotMatch(edited.stderr, /new finding/);
    assert.match(edited.stderr, /1 edited in place/);
    assert.equal(run('--update').status, 0);
    assert.deepEqual([...baseline().keys()], [JSON.stringify(['dist/index.html', 'method-name', 'Old copy mentions MLLW depth.'])]);
    assert.equal(run('--base', 'HEAD').status, 0);
    // A second, unrelated finding in the same file is still new.
    page('<p>Old copy mentions MLLW depth.</p><p>Winds from GFS look calm today.</p>');
    assert.match(run().stderr, /1 new finding/);
  } finally {
    rmSync(root, {recursive: true, force: true});
  }
});
