// M9: the coast view mounts a C2 release only behind web/map/c2-releases.ts, and only a reviewed, rights-cleared
// manifest (mvp.ts admitRelease); held ones are refused before any tile request. Fake fetch, MapLibre, DOM and terrain.
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {existsSync, readFileSync, readdirSync} from 'node:fs';
import test from 'node:test';
import {CoastMvpViewer, admitRelease, mvpChrome, validateMvpManifest} from '../packages/coast/src/coast3d/mvp.ts';
import {C2_ENABLED, C2_RELEASES} from '../web/map/c2-releases.ts';
import {c2Release, createStage, terrainFailed} from '../web/map/stage.ts';
import {configureStore, navigate, syncFromURL} from '../web/state.ts';

const ROOT = new URL('../', import.meta.url);
const w11a = JSON.parse(readFileSync(new URL('research/scripts/coast_mvp/fixtures/w11a-viewer-manifest.json', ROOT)));
const MORRO = '/data/coast-c2/morro-bay/release-manifest.json', ORIGIN = 'https://s.test/map';
const ON = {enabled: true, releases: {'morro-bay': MORRO}};
/** Acceptance 3's cleared manifest, built in memory and never committed. */
const cleared = () => { const m = structuredClone(w11a); delete m.publicationHeld; Object.assign(m, {status: 'reviewed', synthetic: false});
  for (const s of m.sources) Object.assign(s, {permissionRequired: false, rightsStatus: 'cleared', csumbInvolved: false, catalogId: 'usgs-san-simeon'}); return m; };
const settle = async () => { for (let i = 0; i < 12; i++) await new Promise(resolve => setTimeout(resolve, 0)); };
/** A document whose elements keep text only; any HTML write throws. */
const fakeDoc = () => ({createTextNode: data => ({data}), createElement(tag) {
  const el = {tag, children: [], attrs: {}, textContent: '', append: (...nodes) => el.children.push(...nodes), setAttribute: (k, v) => { el.attrs[k] = v; },
    remove: () => { el.removed = true; }, insertAdjacentHTML() { throw Error('HTML write'); }};
  for (const name of ['innerHTML', 'outerHTML']) Object.defineProperty(el, name, {set() { throw Error('HTML write'); }});
  return el; }});
const texts = el => [el.textContent, ...el.children.flatMap(c => ('data' in c ? [c.data] : texts(c)))].filter(Boolean);

test('admitRelease refuses held and uncleared manifests with the first decision-2 reason', () => {
  assert.deepEqual(admitRelease(w11a), {refused: 'publication held'});
  assert.equal(admitRelease(cleared()).manifest.region, w11a.region);
  assert.throws(() => validateMvpManifest(cleared()), 'the preview never loads a release manifest');
  const rights = 'rights not cleared: fixture', src = m => m.sources[0];
  const cases = [[m => delete m.status, 'not reviewed'], [m => m.status = 'Reviewed', 'not reviewed'], [m => m.status = 'review_required', 'not reviewed'],
    [m => src(m).permissionRequired = true, rights], [m => src(m).rightsStatus = 'review_required', rights], [m => src(m).rightsStatus = 'Cleared', rights],
    [m => src(m).csumbInvolved = true, rights], [m => delete src(m).csumbInvolved, rights], [m => delete src(m).termsUrl, rights],
    [m => src(m).termsUrl = 'http://example.org/terms', rights], [m => delete src(m).catalogId, rights], [m => src(m).catalogId = ' ', rights],
    [m => delete src(m).sha256, rights], [m => src(m).contributedCells = 0, rights], [m => delete src(m).datumNote, rights],
    [m => m.sources.push({...src(m), id: 'second', permissionRequired: true}), 'rights not cleared: second'],
    [m => m.synthetic = true, 'synthetic fixture'], [m => delete m.synthetic, 'synthetic fixture'],
    [m => m.publicationHeld = false, 'publication held'], [m => m.publicationHeld = null, 'publication held'],
    [m => { m.publicationHeld = true; delete m.status; }, 'publication held'], [m => { delete m.status; m.synthetic = true; }, 'not reviewed'],
    [m => m.bounds.reverse(), 'invalid manifest: Invalid local coast manifest'], [m => m.sources.push(src(m)), 'invalid manifest: Incomplete source attribution'],
    [m => src(m).url = 'https://a:b@example.org', 'invalid manifest: Invalid source URL'],
    [m => m.terrain = '{z}/{x}/{y}.png', 'invalid tile templates'], [m => m.contours = 'https://x.test/{z}/{x}/{y}.pbf', 'invalid tile templates'],
    [m => m.navigation = 'not for navigation.', 'missing navigation notice'], [m => delete m.navigation, 'missing navigation notice'],
    [m => m.limitations = [], 'missing limitations'], [m => m.limitations = [''], 'missing limitations'],
    [m => delete m.provenance, 'incomplete provenance'], [m => m.provenance.c1Sha256 = 'A'.repeat(64), 'incomplete provenance'],
    [m => m.provenance.assets = {'../x.png': 'a'.repeat(64)}, 'incomplete provenance'], [m => m.provenance.assets = {'terrain/1.png': 'no'}, 'incomplete provenance']];
  for (const [change, reason] of cases) { const m = cleared(); change(m); assert.deepEqual(admitRelease(m), {refused: reason}, String(change)); }
  for (const value of [null, [], 'manifest', 7]) assert.deepEqual(admitRelease(value), {refused: 'invalid manifest'});
});

test('loadRelease requests only the manifest and builds no map until admitted', async () => {
  globalThis.location = new URL(ORIGIN);
  const run = async (body, {ok = true, url = MORRO} = {}) => {
    const requests = [], maps = [];
    const fetch = async (u, init) => { requests.push([String(u), init.redirect]); if (body instanceof Error) throw body; return {ok, json: async () => (typeof body === 'string' ? JSON.parse(body) : body)}; };
    const lib = {Map: class { constructor(o) { maps.push(o); } addControl() {} remove() { maps.removed = true; } }, NavigationControl: class {}};
    return {result: await CoastMvpViewer.loadRelease({append() {}}, url, {fetch, lib}), requests, maps};
  };
  const held = await run(w11a);
  assert.deepEqual(held.result, {refused: 'publication held'}); assert.deepEqual(held.requests, [['https://s.test' + MORRO, 'error']]); assert.equal(held.maps.length, 0);
  const uncleared = cleared(); uncleared.sources[0].rightsStatus = 'needs_permission';
  for (const [body, options, reason] of [[uncleared, {}, 'rights not cleared: fixture'], [cleared(), {ok: false}, 'manifest unavailable'],
    ['{bad json', {}, 'manifest unavailable'], [new Error('redirected'), {}, 'manifest unavailable']]) {
    const r = await run(body, options);
    assert.deepEqual(r.result, {refused: reason}); assert.equal(r.maps.length, 0); assert.equal(r.requests.length, 1);
  }
  await assert.rejects(run(cleared(), {url: 'https://elsewhere.test' + MORRO}), /Local manifest required/);
  globalThis.document = fakeDoc();
  const ok = await run(cleared());
  assert.equal(ok.requests.length, 1); assert.equal(ok.maps.length, 1);
  assert.deepEqual(ok.maps[0].style.sources['mvp-terrain'].tiles, ['https://s.test/data/coast-c2/morro-bay/terrain/{z}/{x}/{y}.png']);
  ok.result.viewer.destroy(); assert.equal(ok.maps.removed, true);
});

test('the release chrome is text nodes: attribution, licence and the not-for-navigation label, no hold line', () => {
  const m = cleared(), chrome = mvpChrome(fakeDoc(), m, 'release'), all = texts(chrome).join('\n');
  assert.equal(chrome.className, 'coast-mvp-chrome');
  assert.equal(chrome.children[0].textContent, 'Not for navigation · Reviewed terrain · source detail varies');
  for (const line of [m.navigation, ...m.limitations, ...m.sources.flatMap(s => [s.attribution, s.license])]) assert.ok(all.includes(line), line);
  assert.doesNotMatch(all, /publication held|No accuracy claim\. Review required/i);
  const preview = texts(mvpChrome(fakeDoc(), w11a, 'preview'));
  assert.equal(preview[0], 'Not for navigation · SYNTHETIC FIXTURE — not measured bathymetry');
  for (const line of ['Publication held · review required', w11a.navigation, ...w11a.limitations, ' Rights review required — publication held. No datum reconciliation',
    'Relief ×3 (display only). Contours: feet below reference; source detail varies. No accuracy claim. Review required.']) assert.ok(preview.includes(line), line);
  assert.ok(preview.some(t => t.endsWith('For-profit permission unresolved — publication held.')));
});

function browser(href) {
  globalThis.location = {href}; globalThis.dispatchEvent = () => true;
  globalThis.history = {state: null, pushState(_s, _t, url) { location.href = url; }, replaceState(_s, _t, url) { location.href = url; }};
  configureStore({v2: true, storage: null}); syncFromURL(href);
}
/** A fake terrain module whose loadC2().mountRelease answers with `release(host, url)`. */
function terrain(release) {
  const fake = {mounts: 0, destroyed: 0, loads: 0, releases: []};
  const handle = new Proxy({load: async () => true, destroy: () => { fake.destroyed++; }}, {get: (t, k) => t[k] ?? (() => true)});
  fake.module = {styles: [], mountCoast() { fake.mounts++; return handle; },
    loadC2: async () => { fake.loads++; return {mountRelease: async (host, url) => { fake.releases.push(url); return release(host, url); }}; }};
  return fake;
}
function stage(fake, c2) {
  const host = {dataset: {}, shadowRoot: {children: [], replaceChildren() {}}}, doc = {hidden: false, addEventListener() {}, removeEventListener() {}};
  terrainFailed.value = false;
  return {host, stage: createStage({host, load: async () => fake.module, center: () => [35.37, -120.86], doc, viewDelay: 0, ...(c2 ? {c2} : {})})};
}
const view = () => { const v = {visible: [], destroyed: 0, setVisible: x => v.visible.push(x), destroy: () => { v.destroyed++; }}; return v; };

test('flag off, an unlisted region or a mismatched path never loads the C2 module or requests a release', async () => {
  assert.equal(C2_ENABLED, false); assert.deepEqual(C2_RELEASES, {}); assert.ok(Object.isFrozen(C2_RELEASES));
  assert.equal(existsSync(new URL('dist/data/coast-c2', ROOT)), false);
  const fetched = []; globalThis.fetch = async url => { fetched.push(String(url)); throw Error('offline'); };
  const cambria = '/data/coast-c2/cambria-san-simeon/release-manifest.json';
  for (const c2 of [undefined, {enabled: false, releases: ON.releases}, {enabled: true, releases: {'cambria-san-simeon': cambria}}, {enabled: true, releases: {'morro-bay': cambria}}]) {
    browser(`${ORIGIN}?region=morro-bay&presentation=3d`);
    const fake = terrain(() => view()), s = stage(fake, c2);
    await settle();
    assert.equal(fake.loads, 0, JSON.stringify(c2)); assert.equal(fake.mounts, 1); assert.equal(s.host.dataset.c2, undefined);
    s.stage.destroy();
  }
  assert.equal(fetched.filter(u => /coast-c2|release-manifest/.test(u)).length, 0);
  assert.equal(c2Release('morro-bay'), null); assert.equal(c2Release(null, ON), null); assert.equal(c2Release('toString', {enabled: true, releases: {}}), null);
  assert.equal(c2Release('morro-bay', ON), MORRO);
});

test('a refused or failing release falls back to the reviewed coast without a graphics failure', async () => {
  for (const [release, reason] of [[() => ({refused: 'publication held'}), 'publication held'], [() => { throw Error('chunk failed'); }, 'unavailable']]) {
    browser(`${ORIGIN}?region=morro-bay&presentation=3d`);
    const fake = terrain(release), s = stage(fake, ON);
    await settle();
    assert.deepEqual(fake.releases, [MORRO]);
    assert.equal(s.host.dataset.c2, 'refused: ' + reason); assert.equal(fake.mounts, 1); assert.equal(terrainFailed.value, false);
    s.stage.destroy();
  }
});

test('a mounted release follows Chart, gives way to a new region and is destroyed with the stage', async () => {
  browser(`${ORIGIN}?region=morro-bay&presentation=3d`);
  const v = view(), fake = terrain(() => v), s = stage(fake, ON);
  await settle();
  assert.equal(fake.mounts, 0); assert.equal(v.visible.at(-1), true);
  navigate(`${ORIGIN}?region=morro-bay&presentation=2d`); await settle();
  assert.equal(fake.loads, 1, 'a mounted view is not mounted again'); assert.equal(fake.mounts, 0);
  navigate(`${ORIGIN}?region=morro-bay&presentation=chart`); await settle();
  assert.equal(v.visible.at(-1), false);
  navigate(`${ORIGIN}?region=cambria-san-simeon&presentation=3d`); await settle();
  assert.equal(v.destroyed, 1); assert.equal(fake.mounts, 1, 'the new region mounts its terrain');
  s.stage.destroy(); assert.equal(fake.destroyed, 1);
  browser(`${ORIGIN}?region=morro-bay&presentation=3d`);
  const kept = view(), again = stage(terrain(() => kept), ON);
  await settle(); again.stage.destroy();
  assert.equal(kept.destroyed, 1, 'destroy() destroys the view');
});

test('region round trips replace legacy terrain with the listed C2 release without remounting the stage', async () => {
  for (const initial of ['cambria-san-simeon', 'morro-bay']) {
    browser(`${ORIGIN}?region=${initial}&presentation=3d`);
    const views = [], fake = terrain(() => { const v = view(); views.push(v); return v; }), s = stage(fake, ON);
    try {
      await settle();
      if (initial === 'morro-bay') {
        navigate(`${ORIGIN}?region=cambria-san-simeon&presentation=3d`); await settle();
        assert.equal(views[0].destroyed, 1);
      }
      assert.equal(fake.mounts, 1);
      for (let trip = 0; trip < 2; trip++) {
        navigate(`${ORIGIN}?region=morro-bay&presentation=3d`); await settle();
        assert.equal(fake.destroyed, trip + 1, 'the legacy renderer gives way to C2');
        assert.equal(fake.releases.length, (initial === 'morro-bay' ? 1 : 0) + trip + 1);
        assert.equal(views.at(-1).visible.at(-1), true);
        assert.equal(terrainFailed.value, false);
        navigate(`${ORIGIN}?region=cambria-san-simeon&presentation=3d`); await settle();
        assert.equal(views.at(-1).destroyed, 1);
        assert.equal(fake.mounts, trip + 2, 'the unlisted region gets legacy terrain again');
      }
      assert.deepEqual(fake.releases, Array(views.length).fill(MORRO));
    } finally { s.stage.destroy(); }
    assert.equal(fake.destroyed, fake.mounts);
    assert.ok(views.every(v => v.destroyed === 1));
  }
});

test('a release answering after the region changed, or after destroy, is dropped', async () => {
  for (const late of ['region', 'destroy']) {
    browser(`${ORIGIN}?region=morro-bay&presentation=3d`);
    let answer; const v = view(), fake = terrain(() => new Promise(resolve => { answer = resolve; })), s = stage(fake, ON);
    await settle();
    if (late === 'region') navigate(`${ORIGIN}?region=cambria-san-simeon&presentation=3d`); else s.stage.destroy();
    answer(v); await settle();
    assert.equal(v.destroyed, 1, late); assert.equal(fake.mounts, late === 'region' ? 1 : 0, late);
    if (late === 'region') s.stage.destroy();
  }
});

test('release binding: every listed release exists, is admitted and names approved, commercially cleared catalog rows', () => {
  const catalog = new Map(JSON.parse(readFileSync(new URL('catalog/sources.json', ROOT))).sources.map(row => [row.id, row]));
  for (const [regionId, path] of Object.entries(C2_RELEASES)) {
    assert.equal(c2Release(regionId, {enabled: true, releases: C2_RELEASES}), path, regionId);
    const file = new URL('dist' + path, ROOT), admitted = existsSync(file) ? admitRelease(JSON.parse(readFileSync(file))) : {refused: 'missing'};
    assert.ok('manifest' in admitted, `${path}: ${admitted.refused}`);
    for (const {catalogId} of admitted.manifest.sources) {
      const row = catalog.get(catalogId);
      assert.equal(row?.review_status, 'approved', catalogId); assert.equal(row?.rights?.commercial_use, 'allowed', catalogId);
    }
    for (const [asset, digest] of Object.entries(admitted.manifest.provenance.assets)) {
      assert.equal(createHash('sha256').update(readFileSync(new URL(asset, file))).digest('hex'), digest, asset);
    }
  }
  const shipped = new URL('dist/data/coast-c2/', ROOT), listed = new Set(Object.values(C2_RELEASES));
  for (const dir of existsSync(shipped) ? readdirSync(shipped) : []) {
    if (existsSync(new URL(`${dir}/release-manifest.json`, shipped))) assert.ok(listed.has(`/data/coast-c2/${dir}/release-manifest.json`), dir);
  }
});
