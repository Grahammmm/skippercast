// Copy lint (P4-04, scripts/check_copy.mjs): the rules, the disclosure
// containers, and the baseline that only shrinks.
import test from 'node:test';
import assert from 'node:assert/strict';
import {execFileSync, spawnSync} from 'node:child_process';
import {mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import util from 'node:util';
import {
  BASELINE, COVERED, NOT_COVERED, catalogueProblems, compare, coverageProblems, formatBaseline, grown, htmlUnits, lint, lintFile, literals, readBaseline, sentences, tally, unitFindings,
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

// SC0707-03: the two "not checked for this spot" lines are each ONE literal that the unchanged lint can read whole.
// The expected lines are written here independently of the product constants.
const UNCHECKED = [
  {file: 'dist/account.js', catalogue: 'account.spots.unchecked', line: 'Protected areas not checked for this spot: outside coverage or check unavailable; not exported.', old: 'Protected areas not checked for this spot: outside coverage or check unavailable. Not exported.'},
  {file: 'web/saved-spots.ts', catalogue: 'mark.save.notChecked', line: 'Protected areas not checked for this spot: outside coverage or check unavailable; not saved.', old: 'Protected areas not checked for this spot. Not saved.'},
];

test('unchecked_copy_is_one_complete_linted_literal', () => {
  for (const {file, line, catalogue} of UNCHECKED) {
    const source = readFileSync(new URL(`../${file}`, import.meta.url), 'utf8');
    // Each caveat: not checked, why, and the refused action.
    for (const part of ['not checked for this spot', 'outside coverage', 'check unavailable']) assert.ok(line.includes(part), `${file}: ${part}`);
    assert.ok(/not (?:exported|saved)\.$/.test(line), `${file}: the refused action closes the line`);
    if (catalogue) {
      // SC0922-09: the line moved to the string catalogue, where it is one complete English value (the unchanged lint reads it whole).
      const strings = JSON.parse(readFileSync(new URL('../catalog/app/strings.json', import.meta.url), 'utf8')).strings;
      assert.equal(strings[catalogue].en, line, `${catalogue}: the whole line is one catalogue value`);
      assert.ok(!source.includes('not checked for this spot'), `${file}: no copy of it left in the module`);
      assert.deepEqual(unitFindings(line), []);
      continue;
    }
    // Exactly one literal holds the whole line, and no other literal carries a half of it.
    assert.equal(literals(source).filter(l => l.value === line).length, 1, `${file}: the whole line is one literal`);
    assert.equal(literals(source).filter(l => l.value.includes('not checked for this spot')).length, 1, `${file}: no split half`);
    // That literal stands alone: not joined to another by + and not built at runtime.
    const quoted = `'${line}'`;
    const at = source.indexOf(quoted);
    assert.ok(at >= 0 && source.indexOf(quoted, at + 1) < 0, `${file}: the quoted line occurs once`);
    assert.match(source.slice(Math.max(0, at - 3), at), /[:=]\s*$/, `${file}: not concatenated before`);
    assert.match(source.slice(at + quoted.length, at + quoted.length + 3), /^\s*[,;]/, `${file}: not concatenated after`);
    assert.doesNotMatch(source, /lint[^\n]*two literals|two literals[^\n]*lint|reads each literal alone/i, `${file}: no lint-evasion comment`);
    // The unchanged lint reads it whole and finds nothing.
    assert.deepEqual(unitFindings(line), []);
    assert.deepEqual(lintFile(file, source), []);
  }
});

test('the old joined unchecked sentences still read as consecutive-not', () => {
  for (const {old} of UNCHECKED) assert.deepEqual(rules(unitFindings(old)), ['consecutive-not'], old);
  // A semicolon keeps one sentence only when it really is one: a stray full stop brings the finding back.
  assert.deepEqual(rules(unitFindings('Protected areas not checked for this spot: outside coverage or check unavailable. Not saved.')), ['consecutive-not']);
});

// SC0452-11: seven caveats that the baseline once excused are now plain copy, and the baseline keeps only the five
// method-name entries (published model, survey and datum labels in source lines).
const read = path => readFileSync(new URL(`../${path}`, import.meta.url), 'utf8');
const SEVEN = [
  {file: 'dist/bite-evidence.js',
    old: 'A regulation-page check detects access and changes, not permission to fish. Harbor information is not live entrance clearance.',
    now: 'A regulation-page check detects access and changes, not permission to fish. Harbor information provides no live entrance clearance.'},
  {file: 'dist/charter-grounds.js',
    old: 'Captains named “${esc(g.reported_ground)}”; they did not publish GPS positions or fishing depths. Purple shows our approximate search water, not a boat track or a confirmed reef.',
    now: 'Captains named “${esc(g.reported_ground)}” without publishing GPS positions or fishing depths. Purple shows our approximate search water, not a boat track or a confirmed reef.'},
  {file: 'dist/commercial-ais.html',
    old: 'AIS does not cover every boat; detection and classification errors remain possible.',
    now: 'AIS coverage omits some boats; detection and classification errors remain possible.'},
  {file: 'dist/species-research.html',
    old: 'Essential habitat is not a hotspot. The app does not assign a tuna school to a management polygon.',
    now: 'Essential habitat is not a hotspot. The app assigns no tuna school to a management polygon.'},
  {file: 'dist/species-research.html',
    old: 'It is presented as dated context, not mapped as a present hotspot. Named features such as White Rocks must not be confused with a similarly named reef near Cayucos.',
    now: 'It is presented as dated context, not mapped as a present hotspot. Keep named features such as White Rocks distinct from a similarly named reef near Cayucos.'},
  {file: 'dist/species-research.html',
    old: 'They are not a local adult-Chinook catch-temperature model. Freshwater spawning or egg-survival temperatures are not used as ocean-fishing targets.',
    now: 'They are not a local adult-Chinook catch-temperature model. Freshwater spawning or egg-survival temperatures are excluded as ocean-fishing targets.'},
  {file: 'dist/trip-export.js',
    old: 'This file does not update offline. The planned date is a label, not a future clearance.',
    now: 'This file stays unchanged offline. The planned date is a label, not a future clearance.'},
];
const METHOD_LABELS = [
  {file: 'dist/charter-grounds.js', rule: 'method-name', text: 'Outline survey depths X ft X · MLLW'},
  {file: 'dist/forecast.js', rule: 'method-name', text: 'NOAA GFS Wave 0.16°'},
  {file: 'dist/live-conditions.js', rule: 'method-name', text: 'X ft MLLW'},
  {file: 'dist/tomorrow.js', rule: 'method-name', text: 'GFS and ECMWF agree'},
  {file: 'dist/tomorrow.js', rule: 'method-name', text: 'GFS and ECMWF disagree'},
];
const notRule = findings => findings.filter(f => f.rule === 'consecutive-not');
// Entities and the escape boundary are the source's own; the lint sees the same text the person reads.
const plain = html => html.replace(/&#x27;/g, "'").replace(/&amp;/g, '&');

test('seven_caveats_are_present_and_lint_clean: each new span is in its file, the old one is gone, and the files lint clean', () => {
  for (const {file, old, now} of SEVEN) {
    const source = read(file);
    assert.ok(source.includes(now), `${file} says: ${now}`);
    assert.ok(!source.includes(old), `${file} no longer says: ${old}`);
    assert.deepEqual(notRule(lintFile(file, source)), [], `${file} has no consecutive-not finding`);
    // Positive control: restoring the old wording in that file is a finding again.
    assert.equal(notRule(lintFile(file, source.replace(now, old))).length, 1, `${file} with the old wording is flagged`);
  }
  assert.deepEqual(rules(unitFindings(SEVEN[6].old)), ['consecutive-not']);
  assert.deepEqual(rules(unitFindings(SEVEN[6].now)), []);
});

test('baseline_keeps_five_method_labels_exactly: only the five method-name entries remain, unchanged', () => {
  const entries = JSON.parse(read(BASELINE)).entries;
  assert.equal(entries.length, 5);
  assert.ok(util.isDeepStrictEqual(entries, METHOD_LABELS), 'the baseline is exactly the five original method-name entries');
  assert.ok(entries.every(e => e.rule === 'method-name'));
});

test('offline_notes_keep_date_and_clearance_limits: static offline statement, date label, four checks, chart and sounder', async () => {
  const {offlineNotes} = await import('../dist/trip-export.js');
  const result = {created_at: '2026-09-22T18:00:00.000Z', boundary_checked_at: null, counts: {waypoints: 0, tracks: 0},
    features: {selected: []}, exclusions: [], contours: [], layers: {}, avoid_bounds: [], source_validation_date: null};
  const region = {id: 'test-coast', name: 'Test Coast', regulations_url: 'https://example.org/rules'};
  const html = offlineNotes(result, region, {name: 'Plan', date: '2030-01-02'});
  const text = html.replace(/<[^>]+>/g, ' ');
  assert.match(text, /Planned date 2030-01-02/);
  assert.match(text, /check current regulations, closures, marine conditions and harbor access\. This file stays unchanged offline\. The planned date is a label, not a future clearance\. Follow your official navigation chart and sounder\./);
  assert.doesNotMatch(html, /does not update offline/);
  assert.deepEqual(rules(unitFindings(text.replace(/\s+/g, ' '))).filter(r => r === 'consecutive-not'), []);
  // The separate protected-boundary report keeps its own sentence byte for byte.
  assert.ok(read('dist/trip-export.js').includes('Recheck before departure; this file does not update offline.</p>'));
});

test('bite_evidence_html_keeps_access_and_clearance_limits: the emitted evidence says what a page check cannot show', async () => {
  const {evidenceHTML} = await import('../dist/bite-evidence.js');
  const html = evidenceHTML({sources: {}, generated_at: new Date().toISOString(), reports: [], status: {}}, 'reef',
    {name: 'Test point', latitude: 35.3, longitude: -120.9});
  assert.ok(html.includes('A regulation-page check detects access and changes, not permission to fish. Harbor information provides no live entrance clearance.'));
  assert.ok(!html.includes('Harbor information is not live entrance clearance'));
});

test('published_ground_name_stays_escaped: the ground card keeps the esc call, the esc implementation and every qualification', () => {
  const source = read('dist/charter-grounds.js');
  const escSource = source.match(/const esc = \(s\) =>[\s\S]*?\n  \);\n/)?.[0] ?? '';
  assert.equal(escSource, [
    'const esc = (s) =>', '  String(s ?? "").replace(', '    /[&<>"\']/g,', '    (c) =>',
    '      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", \'"\': "&quot;", "\'": "&#39;" })[', '        c', '      ],', '  );', ''].join('\n'));
  const paragraph = source.match(/<p class="evidence-note charter-note">[\s\S]*?<\/p>/)?.[0] ?? '';
  assert.ok(paragraph.includes('<strong>Reported area, exact stops unknown.</strong><br>Captains named “${esc(g.reported_ground)}” without publishing GPS positions or fishing depths. Purple shows our approximate search water, not a boat track or a confirmed reef.'));
  assert.equal((paragraph.match(/\$\{/g) || []).length, 1, 'the ground name is the only interpolation');
  // Render the paragraph from the file's own text with a hostile name: the escape boundary holds.
  const esc = new Function(`${escSource}; return esc;`)();
  const render = new Function('esc', 'g', `return \`${paragraph}\`;`);
  const out = render(esc, {reported_ground: '<b>Pecho & “Rock”</b> Café'});
  assert.ok(out.includes('Captains named “&lt;b&gt;Pecho &amp; “Rock”&lt;/b&gt; Café”'));
  assert.ok(!out.includes('<b>'));
  // The qualifications: unpublished positions AND depths, approximate search water, neither a track nor a confirmed reef.
  assert.match(out, /without publishing GPS positions or fishing depths/);
  assert.match(out, /approximate search water, not a boat track or a confirmed reef/);
});

test('research_caveats_keep_distinctions: salmon, tuna, dated charter and AIS pages keep every limit and link', () => {
  const research = plain(read('dist/species-research.html'));
  for (const s of [
    'concern food-web conditions and survival. They are not a local adult-Chinook catch-temperature model. Freshwater spawning or egg-survival temperatures are excluded as ocean-fishing targets.',
    'are broad management habitat descriptions. Essential habitat is not a hotspot. The app assigns no tuna school to a management polygon.',
    'starting in 280 ft before moving shallower. It is outside the requested bottom-fishing area/depth and provides no reusable exact GPS stops. It is presented as dated context, not mapped as a present hotspot. Keep named features such as White Rocks distinct from a similarly named reef near Cayucos.',
  ]) assert.ok(research.includes(s), s);
  for (const href of ['local-physical-indicators', 'inport/item/80237', 'inport/item/80247', 'wonews.com/a-trip-to-lingcod-alley']) assert.ok(research.includes(href), href);
  const ais = read('dist/commercial-ais.html');
  assert.ok(ais.includes('2024 vessel classification is provisional. AIS coverage omits some boats; detection and classification errors remain possible. Apparent fishing effort is not proof of fishing or catches.'));
});

// SC0922-15: every .tsx screen is classified. Synthetic trees only (COPY_LINT_ROOT for the CLI).
const mkTree = files => {
  const root = mkdtempSync(join(tmpdir(), 'copy-cover-'));
  mkdirSync(join(root, 'dist')); mkdirSync(join(root, 'scripts'));
  writeFileSync(join(root, 'dist', 'index.html'), '<main><p>Hello.</p></main>');
  writeFileSync(join(root, BASELINE), formatBaseline(new Map()));
  for (const [path, text] of Object.entries(files)) { mkdirSync(join(root, path, '..'), {recursive: true}); writeFileSync(join(root, path), text); }
  return root;
};
const runIn = (root, ...args) => spawnSync(process.execPath, [SCRIPT, ...args], {env: {...process.env, COPY_LINT_ROOT: root}, encoding: 'utf8'});

test('coverage: an unlisted .tsx fails by path in each root and a nested view; .ts, admin and symlinks are not screens', () => {
  const paths = ['web/app/New.tsx', 'web/app/views/NewView.tsx', 'web/brief/New.tsx', 'web/landing/New.tsx', 'web/app/views/deep/er/New.tsx'];
  const root = mkTree({...Object.fromEntries(paths.map(p => [p, ''])), 'web/app/helper.ts': '', 'web/admin/Panel.tsx': ''});
  try {
    assert.deepEqual(coverageProblems(root, [], {}), paths.slice().sort().map(p => `${p}: copy-lint coverage missing; add to COVERED or NOT_COVERED with a reason`));
    assert.deepEqual(coverageProblems(mkdtempSync(join(tmpdir(), 'copy-cover-empty-')), [], {}), [], 'missing roots are empty');
  } finally { rmSync(root, {recursive: true, force: true}); }
});

test('coverage: a listed file passes; bad reasons, overlap, duplicates and odd paths fail', () => {
  const root = mkTree({'web/app/New.tsx': '', 'web/brief/Other.tsx': ''});
  try {
    assert.deepEqual(coverageProblems(root, ['web/app/New.tsx'], {'web/brief/Other.tsx': 'data only'}), []);
    const bad = coverageProblems(root, ['web/app/New.tsx', 'web/app/New.tsx', '/abs.tsx', 'web/../x.tsx'], {'web/app/New.tsx': 'x', 'web/brief/Other.tsx': ' ', 'web/a.tsx': 'two\nlines'}).join('\n');
    assert.match(bad, /web\/app\/New\.tsx: listed twice in COVERED/);
    assert.match(bad, /web\/app\/New\.tsx: listed in both COVERED and NOT_COVERED/);
    assert.match(bad, /\/abs\.tsx: COVERED path must be repository-relative/);
    assert.match(bad, /web\/\.\.\/x\.tsx: COVERED path must be repository-relative/);
    assert.match(bad, /web\/brief\/Other\.tsx: NOT_COVERED needs a one-line reason/);
    assert.match(bad, /web\/a\.tsx: NOT_COVERED needs a one-line reason/);
  } finally { rmSync(root, {recursive: true, force: true}); }
});

test('coverage: the repository lists classify every screen exactly once, with a reason for each exception', () => {
  assert.deepEqual(coverageProblems(), []);
  for (const [path, reason] of Object.entries(NOT_COVERED)) assert.ok(!COVERED.includes(path) && reason.trim(), path);
});

test('coverage_is_real_not_exempt: the private device log is covered once, not exempt, and has no bare prose or missing id', () => {
  const path = 'web/app/PrivateMapLog.tsx';
  assert.equal(COVERED.filter(p => p === path).length, 1);
  assert.ok(!Object.hasOwn(NOT_COVERED, path));
  assert.deepEqual(catalogueProblems().filter(p => p.includes(path) || p.includes('privateMapLog.')), []);
});

test('coverage CLI: an unlisted screen fails with and without a catalogue, in every mode; lists and baseline are never rewritten', () => {
  const root = mkTree({'web/app/views/NewEnglishScreen.tsx': 'export const V = () => <p>Hello there.</p>;\n'});
  try {
    for (const withCatalogue of [false, true]) {
      if (withCatalogue) { mkdirSync(join(root, 'catalog/app'), {recursive: true}); writeFileSync(join(root, 'catalog/app/strings.json'), JSON.stringify({strings: {}})); }
      const res = runIn(root);
      assert.equal(res.status, 1, `catalogue=${withCatalogue}`);
      assert.match(res.stderr, /Copy coverage: 1 problem\(s\)\n {2}web\/app\/views\/NewEnglishScreen\.tsx: copy-lint coverage missing/);
    }
    const git = (...args) => execFileSync('git', ['-c', 'user.name=t', '-c', 'user.email=t@example.com', ...args], {cwd: root, stdio: 'ignore'});
    git('init', '-q'); git('add', '-A'); git('commit', '-qm', 'base');
    const before = readFileSync(join(root, BASELINE), 'utf8'), script = readFileSync(SCRIPT, 'utf8');
    assert.equal(runIn(root, '--update').status, 1);
    assert.equal(runIn(root, '--base', 'HEAD').status, 1);
    assert.equal(readFileSync(join(root, BASELINE), 'utf8'), before, 'the baseline is untouched');
    assert.equal(readFileSync(SCRIPT, 'utf8'), script, 'the lists are not rewritten');
  } finally { rmSync(root, {recursive: true, force: true}); }
});

test('coverage CLI: a listed screen passes; listed bare prose still fails the catalogue; an excluded screen still meets the ordinary rules', () => {
  const clean = mkTree({'web/app/FirstAnswerLine.tsx': "import {t} from '../i18n.ts';\nexport const A = ({lang}) => <p>{t('x.ok', lang)}</p>;\n", 'catalog/app/strings.json': JSON.stringify({strings: {'x.ok': {en: 'One', es: 'Uno'}}})});
  try {
    const res = runIn(clean);
    assert.equal(res.status, 0, res.stderr);
    writeFileSync(join(clean, 'web/app/FirstAnswerLine.tsx'), 'export const A = () => <p>This screen is English only</p>;\n');
    const bare = runIn(clean);
    assert.equal(bare.status, 1);
    assert.match(bare.stderr, /FirstAnswerLine\.tsx:1 bare literal "This screen is English only"/);
  } finally { rmSync(clean, {recursive: true, force: true}); }
  const excluded = mkTree({'web/app/App.tsx': 'export const A = () => <p>Plain words here.</p>;\n'});
  try {
    assert.equal(runIn(excluded).status, 0, 'an excluded screen with clean copy passes');
    writeFileSync(join(excluded, 'web/app/App.tsx'), 'export function A() {\n  return <p>This is not a chart. It is not a route.</p>;\n}\n');
    const res = runIn(excluded);
    assert.equal(res.status, 1);
    assert.match(res.stderr, /web\/app\/App\.tsx:2 \[consecutive-not\]/);
  } finally { rmSync(excluded, {recursive: true, force: true}); }
});
