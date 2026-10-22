import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {spawnSync} from 'node:child_process';
import {copyFileSync, mkdirSync, mkdtempSync, readFileSync, rmSync, symlinkSync, writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {fileURLToPath} from 'node:url';
import {adaptC5Rights} from '../packages/coast/src/coast3d/mvp-rights.ts';
import {CSUMB_NOTICE, GEBCO_CAVEAT, NO_ENDORSEMENT, NOT_FOR_NAVIGATION, RIGHTS_REVIEW, isLocalAssetPath, localAsset, validateMvpManifest} from '../packages/coast/src/coast3d/mvp.ts';

const dir = new URL('../research/scripts/coast_mvp/fixtures/', import.meta.url);
const raw = readFileSync(new URL('rights-adapter/inventory.json', dir));
const inventory = JSON.parse(raw);
const base = JSON.parse(readFileSync(new URL('rights-adapter/tile-base.json', dir)));
const sha = createHash('sha256').update(raw).digest('hex');
const link = {page: 'rights.html', inventorySha256: sha};
const adapt = (inv = inventory, b = base, l = link) => adaptC5Rights(structuredClone(inv), structuredClone(b), l);
const row = (inv, id) => inv.sources.find(s => s.source_id === id);

test('C5 inventory adapts to a C3 manifest keeping only actual contributors and every rights field', () => {
  const m = adapt();
  assert.deepEqual(m.sources.map(s => s.id), ['c3fx-csumb-usgs-release', 'c3fx-gebco-grid', 'c3fx-noaa-cc0']);
  for (const s of m.sources) {
    const c5 = row(inventory, s.id);
    assert.equal(s.label, c5.name); assert.equal(s.url, c5.source_url);
    assert.equal(s.attribution, c5.rights.attribution); assert.equal(s.license, c5.rights.license);
    assert.equal(s.rights.sha256, c5.sha256); assert.equal(s.rights.termsUrl, c5.rights.terms_url);
    assert.equal(s.rights.contributedCells, c5.contributed_cells);
    assert.equal(s.datum, null); assert.equal(s.resolutionM, null);
  }
  assert.equal(m.synthetic, true);
  assert.deepEqual(m.rightsInventory, {schemaVersion: 1, sha256: sha, page: 'rights.html', status: 'review_required',
    caveats: [NOT_FOR_NAVIGATION, RIGHTS_REVIEW, NO_ENDORSEMENT, CSUMB_NOTICE, GEBCO_CAVEAT]});
  assert.deepEqual(m.mosaic, base.mosaic);
});

test('commercial permission is never inferred: only CSUMB is held, nothing is cleared', () => {
  const m = adapt();
  const status = Object.fromEntries(m.sources.map(s => [s.id, [s.rights.status, s.permissionRequired]]));
  assert.deepEqual(status, {'c3fx-csumb-usgs-release': ['needs_permission', true],
    'c3fx-gebco-grid': ['review_required', false], 'c3fx-noaa-cc0': ['review_required', false]});
  assert.doesNotMatch(JSON.stringify(m), /cleared"|"approved|"granted/);
  // The C5 backstop: an obvious CSUMB source wrongly tagged false still gets the hold.
  for (const credit of ['CSUMB', 'Seafloor Mapping Lab', 'California State University, Monterey Bay', 'california state university monterey bay']) {
    const inv = structuredClone(inventory);
    const r = row(inv, 'c3fx-noaa-cc0'); r.rights.attribution = 'Credit: ' + credit; r.rights.csumb_involved = false;
    const s = adapt(inv).sources.find(x => x.id === 'c3fx-noaa-cc0');
    assert.equal(s.rights.status, 'needs_permission', credit); assert.equal(s.permissionRequired, true);
  }
  // No CSUMB contributor: no CSUMB notice; GEBCO only when GEBCO contributes.
  const inv = structuredClone(inventory);
  row(inv, 'c3fx-csumb-usgs-release').contributed_cells = 0; row(inv, 'c3fx-gebco-grid').contributed_cells = 0;
  const m2 = adapt(inv);
  assert.deepEqual(m2.rightsInventory.caveats, [NOT_FOR_NAVIGATION, RIGHTS_REVIEW, NO_ENDORSEMENT]);
});

test('negative controls: missing rights or usage fails the whole adaptation', () => {
  const cases = {
    'missing rights': inv => delete row(inv, 'c3fx-noaa-cc0').rights,
    'rights not object': inv => { row(inv, 'c3fx-noaa-cc0').rights = 'CC0'; },
    'missing licence': inv => delete row(inv, 'c3fx-gebco-grid').rights.license,
    'blank licence': inv => { row(inv, 'c3fx-gebco-grid').rights.license = '  '; },
    'missing attribution': inv => delete row(inv, 'c3fx-gebco-grid').rights.attribution,
    'missing terms': inv => delete row(inv, 'c3fx-noaa-cc0').rights.terms_url,
    'http terms': inv => { row(inv, 'c3fx-noaa-cc0').rights.terms_url = 'http://example.org/terms'; },
    'credential url': inv => { row(inv, 'c3fx-noaa-cc0').source_url = 'https://u:p@example.org/'; },
    'javascript url': inv => { row(inv, 'c3fx-noaa-cc0').source_url = 'javascript:alert(1)'; },
    'missing csumb flag': inv => delete row(inv, 'c3fx-csumb-usgs-release').rights.csumb_involved,
    'string csumb flag': inv => { row(inv, 'c3fx-csumb-usgs-release').rights.csumb_involved = 'false'; },
    'missing usage': inv => delete row(inv, 'c3fx-noaa-cc0').contributed_cells,
    'missing usage on unused row': inv => delete row(inv, 'c3fx-unused-bare').contributed_cells,
    'boolean usage': inv => { row(inv, 'c3fx-noaa-cc0').contributed_cells = true; },
    'string usage': inv => { row(inv, 'c3fx-noaa-cc0').contributed_cells = '450'; },
    'fractional usage': inv => { row(inv, 'c3fx-noaa-cc0').contributed_cells = 1.5; },
    'negative usage': inv => { row(inv, 'c3fx-noaa-cc0').contributed_cells = -1; },
    'missing hash': inv => delete row(inv, 'c3fx-noaa-cc0').sha256,
    'uppercase hash': inv => { row(inv, 'c3fx-noaa-cc0').sha256 = 'C'.repeat(64); },
    'missing name': inv => delete row(inv, 'c3fx-noaa-cc0').name,
    'duplicate id': inv => { inv.sources.push(structuredClone(inv.sources[0])); },
    'schema version': inv => { inv.schema_version = 2; },
    'no contributors': inv => inv.sources.forEach(s => { s.contributed_cells = 0; }),
  };
  for (const [name, change] of Object.entries(cases)) {
    const inv = structuredClone(inventory); change(inv);
    assert.throws(() => adapt(inv), undefined, name);
  }
  assert.throws(() => adapt(inventory, base, {page: 'rights.html', inventorySha256: 'x'}));
  assert.throws(() => adapt(inventory, {...base, mosaic: undefined}));
  assert.throws(() => adapt(inventory, base, {page: 'https://remote.example/rights.html', inventorySha256: sha}));
  assert.throws(() => adapt(inventory, base, {page: '/rights.html', inventorySha256: sha}));
});

test('negative controls: an adapted manifest that loses a hold, hash or caveat is rejected by the viewer', () => {
  const good = adapt();
  const csumb = m => m.sources.find(s => s.id === 'c3fx-csumb-usgs-release');
  const cases = {
    'CSUMB permission flipped': m => { csumb(m).permissionRequired = false; },
    'CSUMB status cleared': m => { csumb(m).rights.status = 'review_required'; },
    'CSUMB status invented value': m => { csumb(m).rights.status = 'cleared'; },
    'CSUMB flag dropped': m => { csumb(m).rights.csumbInvolved = false; },
    'hold invented for non-CSUMB': m => { m.sources[2].rights.status = 'needs_permission'; },
    'CSUMB caveat removed': m => { m.rightsInventory.caveats = m.rightsInventory.caveats.filter(c => c !== CSUMB_NOTICE); },
    'GEBCO caveat removed': m => { m.rightsInventory.caveats = m.rightsInventory.caveats.filter(c => c !== GEBCO_CAVEAT); },
    'no-endorsement removed': m => { m.rightsInventory.caveats = m.rightsInventory.caveats.filter(c => c !== NO_ENDORSEMENT); },
    'review status changed': m => { m.rightsInventory.status = 'accepted'; },
    'rights page dropped': m => { delete m.rightsInventory; },
    'rights page remote': m => { m.rightsInventory.page = 'https://remote.example/rights'; },
    'source hash dropped': m => { delete m.sources[1].rights.sha256; },
    'terms link dropped': m => { delete m.sources[1].rights.termsUrl; },
    'zero contributor smuggled': m => { m.sources[1].rights.contributedCells = 0; },
    'unadapted source mixed in': m => { delete m.sources[1].rights; },
    'mosaic dropped': m => { delete m.mosaic; },
  };
  assert.doesNotThrow(() => validateMvpManifest(structuredClone(good)));
  for (const [name, change] of Object.entries(cases)) {
    const m = structuredClone(good); change(m);
    assert.throws(() => validateMvpManifest(m), undefined, name);
  }
});

test('committed adapted fixture and C5 rights page match the task-owned inventory', () => {
  const committed = JSON.parse(readFileSync(new URL('viewer-demo/rights-adapted.json', dir)));
  assert.deepEqual(committed, adapt());
  validateMvpManifest(committed);
  const page = readFileSync(new URL('viewer-demo/rights.html', dir), 'utf8');
  assert.ok(page.includes(sha), 'C5 page pins the same inventory bytes');
  assert.match(page, /SYNTHETIC FIXTURE ONLY/); assert.match(page, /needs_permission/);
  assert.doesNotMatch(page, /c3fx-unused/);
  for (const s of committed.sources) assert.ok(page.includes(s.rights.sha256), s.id);
});

test('adapter CLI pins the inventory bytes and leaves the previous manifest on failure', () => {
  const work = mkdtempSync(join(process.env.TMPDIR || tmpdir(), 'c3-rights-'));
  try {
    const cli = fileURLToPath(new URL('../research/scripts/coast_mvp/adapt_rights.mjs', import.meta.url));
    const inv = join(work, 'inventory.json'), out = join(work, 'manifest.json');
    copyFileSync(new URL('rights-adapter/inventory.json', dir), inv);
    writeFileSync(join(work, 'rights.html'), 'page');
    const run = () => spawnSync(process.execPath, [cli, '--inventory', inv, '--tile-base',
      fileURLToPath(new URL('rights-adapter/tile-base.json', dir)), '--rights-page', 'rights.html', '--output', out], {encoding: 'utf8'});
    let r = run();
    assert.equal(r.status, 0, r.stderr); assert.match(r.stdout, /needs_permission: c3fx-csumb-usgs-release/);
    const before = readFileSync(out);
    assert.equal(JSON.parse(before).rightsInventory.sha256, sha);
    const broken = structuredClone(inventory); delete row(broken, 'c3fx-noaa-cc0').rights;
    writeFileSync(inv, JSON.stringify(broken));
    r = run();
    assert.equal(r.status, 2); assert.match(r.stderr, /rights object is required/);
    assert.deepEqual(readFileSync(out), before);
    rmSync(join(work, 'rights.html'));
    copyFileSync(new URL('rights-adapter/inventory.json', dir), inv);
    r = run();
    assert.equal(r.status, 2); assert.match(r.stderr, /rights page not found/);
  } finally { rmSync(work, {recursive: true, force: true}); }
});

// Review round 1: the rights page must obey the viewer's own containment rules at every boundary.
const BAD_PAGES = ['../rights.html', '%2e%2e/rights.html', '.%2e/rights.html', '%2E%2E/rights.html', 'sub/../../rights.html',
  'sub/%2e%2e/%2e%2e/rights.html', '%252e%252e/rights.html', 'sub%2f..%2f..%2frights.html', '..\\rights.html', 'sub\\rights.html',
  'rights.html?x=1', 'rights.html#x', 'rights.html?', 'https://remote.example/rights.html', '//remote.example/rights.html',
  '/rights.html', 'file:///tmp/rights.html', 'javascript:alert(1)', 'data:text/html,x', 'user:pw@rights.html',
  '', ' ', '.', './', 'sub/', '..', null, 42];
const GOOD_PAGES = ['rights.html', './rights.html', 'sub/rights.html', 'sub/../rights.html'];

test('rights page path: adapter, validator and viewer share one containment rule', () => {
  const viewerBase = new URL('http://127.0.0.1:5179/research/scripts/coast_mvp/fixtures/viewer-demo/');
  for (const page of GOOD_PAGES) {
    assert.ok(isLocalAssetPath(page), page);
    assert.doesNotThrow(() => localAsset(page, viewerBase), page);
    assert.equal(adapt(inventory, base, {page, inventorySha256: sha}).rightsInventory.page, page);
  }
  const good = adapt();
  for (const page of BAD_PAGES) {
    const label = JSON.stringify(page);
    assert.equal(isLocalAssetPath(page), false, label);
    assert.throws(() => adapt(inventory, base, {page, inventorySha256: sha}), undefined, label);
    const m = structuredClone(good); m.rightsInventory.page = page;
    assert.throws(() => validateMvpManifest(m), /Incomplete rights inventory link/, label);
    // Every rejected path is also one the viewer refuses, except the few the offline rule refuses more strictly
    // (directories, and an empty query whose URL path would differ from the on-disk file name).
    if (typeof page === 'string' && page.trim() && !['.', './', 'sub/', 'rights.html?'].includes(page)) {
      assert.throws(() => localAsset(page, viewerBase), undefined, label);
    }
  }
});

test('adapter CLI rejects unsafe rights-page paths and output aliasing without touching any file', () => {
  const work = mkdtempSync(join(process.env.TMPDIR || tmpdir(), 'c3-rights-alias-'));
  try {
    const cli = fileURLToPath(new URL('../research/scripts/coast_mvp/adapt_rights.mjs', import.meta.url));
    const tileBase = fileURLToPath(new URL('rights-adapter/tile-base.json', dir));
    const inv = join(work, 'inventory.json'), outDir = join(work, 'out'), out = join(outDir, 'manifest.json');
    mkdirSync(join(outDir, 'sub'), {recursive: true});
    copyFileSync(new URL('rights-adapter/inventory.json', dir), inv);
    const pageBytes = Buffer.from('<!doctype html><title>complete C5 rights page</title>\n');
    // Real files exist at the traversal targets, so only the path rule can stop them.
    for (const p of [join(work, 'rights.html'), join(outDir, 'rights.html'), join(outDir, 'sub', 'rights.html')]) writeFileSync(p, pageBytes);
    const run = (page, output = out) => spawnSync(process.execPath,
      [cli, '--inventory', inv, '--tile-base', tileBase, '--rights-page', page, '--output', output], {encoding: 'utf8'});
    let r = run('rights.html');
    assert.equal(r.status, 0, r.stderr);
    const before = readFileSync(out);
    for (const page of ['sub/rights.html', './rights.html']) {
      r = run(page, join(outDir, 'other.json'));
      assert.equal(r.status, 0, `${page}: ${r.stderr}`);
    }
    for (const page of BAD_PAGES.filter(p => typeof p === 'string' && p.trim() && !p.startsWith('-'))) {
      r = run(page);
      assert.equal(r.status, 2, page); assert.match(r.stderr, /rights page must be a relative file inside the manifest directory/, page);
      assert.deepEqual(readFileSync(out), before, page);
    }
    // Output aliasing the linked page: refused before writing; the page stays byte-identical.
    for (const [page, output] of [['rights.html', join(outDir, 'rights.html')], ['./rights.html', join(outDir, 'rights.html')],
      ['rights.html', join(outDir, 'sub', '..', 'rights.html')], ['rights.html', join(outDir, 'sub', 'rights.html')]]) {
      r = run(page, output);
      assert.equal(r.status, 2, page); assert.match(r.stderr, /must not overwrite the linked rights page/, page);
    }
    symlinkSync(join(outDir, 'rights.html'), join(outDir, 'alias.json'));
    r = run('rights.html', join(outDir, 'alias.json'));
    assert.equal(r.status, 2); assert.match(r.stderr, /must not overwrite the linked rights page/);
    for (const p of [join(work, 'rights.html'), join(outDir, 'rights.html'), join(outDir, 'sub', 'rights.html')]) {
      assert.deepEqual(readFileSync(p), pageBytes, p);
    }
    assert.deepEqual(readFileSync(out), before);
    // Existing input protections still hold.
    r = run('rights.html', inv);
    assert.equal(r.status, 2); assert.match(r.stderr, /must not overwrite an input/);
  } finally { rmSync(work, {recursive: true, force: true}); }
});
