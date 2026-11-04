import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import test from 'node:test';
import {build} from 'esbuild';
import {rendererPlugins} from './helpers/esbuild-url.mjs';
import {planView, sourceLinks, PLAN_COPY} from '../web/plan.ts';
const ROOT = new URL('..', import.meta.url).pathname;
const json = path => JSON.parse(readFileSync(new URL(`../${path}`, import.meta.url), 'utf8'));
const INDEX = json('dist/regions/morro-bay/search-plan-index.json'), PLANS = INDEX.profiles;
const UNAVAILABLE = json('dist/regions/morro-bay/region.json').map.unavailable_targets;
const FIXTURE = json('tests/fixtures/regulations/fe61-v1.json');
const NOW = new Date('2026-09-21T18:00:00Z');
const pairs = [['What to search for','search_for'], ['Habitat','habitat'], ['How to fish it','presentation'], ['How to fish it','method'], ['Timing','timing'], ['When conditions change','condition_response'], ['Caution','caution']];
test('committed halibut and reef sections, confirmation, evidence and review date are verbatim', () => {
  for (const id of ['halibut', 'reef']) {
    const p = PLANS[id], v = planView(PLANS, id, 'plan', {}, INDEX.reviewed_at);
    assert.equal(v.kind, 'plan');
    assert.deepEqual(v.sections, pairs.filter(([,k]) => typeof p[k] === 'string' && p[k].trim()).map(([title,k]) => ({title, text:p[k]})));
    assert.deepEqual(v.confirm, p.required_to_confirm);
    assert.equal(v.evidence.basis, p.tactics_basis);
    assert.equal(v.reviewedAt, INDEX.reviewed_at);
    assert.equal('thermal_range_c' in v, false);
  }
});
test('unresearched and hostile/inherited IDs never borrow a plan or imply illegality', () => {
  const unavailable = UNAVAILABLE;
  assert.deepEqual(planView(PLANS, 'lobster', 'unresearched', unavailable), {kind:'unresearched', reason:unavailable.lobster});
  assert.deepEqual(planView({}, 'surfperch', 'unresearched'), {kind:'unresearched', reason:PLAN_COPY.unresearched});
  for (const id of ['__proto__','constructor','toString','','  ']) assert.deepEqual(planView(PLANS, id, 'unresearched'), {kind:'unknown',id});
  assert.equal(planView(Object.create({borrowed:PLANS.reef}), 'borrowed', null).kind, 'unknown');
  assert.equal(planView(null, 'reef', 'plan').kind, 'loading');
  assert.doesNotMatch(JSON.stringify(PLAN_COPY), /prohibit|illegal|not allowed/i);
});
test('numeric or missing model declaration withholds every search section; unsafe evidence is dropped', () => {
  for (const numeric_bite_model of [true, undefined, 'false', null]) {
    const v = planView({x:{...PLANS.reef,numeric_bite_model}}, 'x', 'plan');
    assert.equal(v.kind, 'withheld'); assert.equal('sections' in v, false); assert.equal('evidence' in v, false);
  }
  const bad = ['http://example.test','javascript:alert(1)','https://user:pass@example.test','https://user@example.test','bad'];
  const source_links = [...bad.map(url => ({title:'Unsafe',url})), {title:' ',url:'https://example.test'}, {title:'Official',url:'https://example.test/path'}];
  const v = planView({x:{...PLANS.reef,source_links}}, 'x', 'plan');
  assert.deepEqual(v.evidence.links, [{title:'Official',href:'https://example.test/path'}]);
  assert.equal(planView({x:{...PLANS.reef,source_links:source_links.slice(0,-1)}}, 'x', 'plan').evidence.links.length, 0);
});
// SC2207-01: the expected links come from the committed files' own {title, url} shape, not from a hand-written fixture.
const FULL = json('dist/regions/morro-bay/search-plans.json').profiles;
const expectedLinks = p => p.source_links.map(({title, url}) => ({title, href: url}));
test('committed source URLs survive both plan inputs', () => {
  let checked = 0;
  for (const profiles of [FULL, PLANS]) for (const [id, p] of Object.entries(profiles)) {
    if (p.numeric_bite_model !== false) continue;
    assert.ok(Array.isArray(p.source_links) && p.source_links.length > 0, `${id} has committed sources`);
    for (const l of p.source_links) assert.deepEqual(Object.keys(l).sort(), ['title', 'url'], id);
    const before = structuredClone(p.source_links), v = planView(profiles, id, 'plan');
    assert.deepEqual(v.evidence.links, expectedLinks(p), id);
    assert.deepEqual(p.source_links, before, `${id} input unchanged`);
    checked++;
  }
  assert.ok(checked >= 2);
});
test('source URL reader rejects malformed siblings without losing safe links', () => {
  const ok = {title: 'Okay', url: 'https://example.test/path?q=1#part'};
  for (const none of [undefined, null, 'x', 7, {}, {title: 'a', url: 'https://example.test'}]) assert.deepEqual(sourceLinks(none), []);
  const hostile = {title: 'Hostile', url: 'https://example.test/safe', href: 'javascript:alert(1)'};
  const rejected = [null, 'x', 7, [], {}, {title: 'No url'}, {url: 'https://example.test'}, {title: '  ', url: 'https://example.test'},
    {title: 'Blank', url: ' '}, {title: 5, url: 'https://example.test'}, {title: 'Num', url: 5}, {title: 'Href only', href: 'https://example.test'},
    ...['/relative', '//example.test/x', 'not a url', 'http://example.test', 'javascript:alert(1)', 'data:text/html,x', 'ftp://example.test/f',
      'https://user:pass@example.test', 'https://user@example.test', 'https://:pass@example.test'].map(url => ({title: 'Bad', url}))];
  const input = [rejected[0], ok, ...rejected, hostile, ok];
  const before = structuredClone(input), out = sourceLinks(input);
  assert.deepEqual(out, [{title: 'Okay', href: ok.url}, {title: 'Hostile', href: 'https://example.test/safe'}, {title: 'Okay', href: ok.url}]);
  assert.deepEqual(input, before, 'input is not mutated');
  assert.notEqual(out[0], input[1], 'fresh objects');
  assert.equal(sourceLinks([{title: ' Spaced ', url: 'HTTPS://Example.test/A b'}])[0].href, 'HTTPS://Example.test/A b', 'bytes preserved');
});
let module;
async function ui() {
  if (module) return module;
  const out = join(await mkdtemp(join(tmpdir(), 'plan-view-')), 'ui.mjs');
  await build({stdin:{resolveDir:ROOT,loader:'ts',contents:`
    export {PlanView, TargetRules, targetRules, PlanLink} from './web/app/PlanView.tsx';
    export {Conditions} from './web/app/views/Conditions.tsx';
    export {DensityRow} from './web/app/Legend.tsx';
    export {markData, markScreen} from './web/map/marks.ts';
    export {camera} from './web/map/stage.ts';
    export {ViewNav} from './web/app/Masthead.tsx';
    export {regionInfo} from './web/app/App.tsx';
    export {regionPlans, regionUnavailable, loadPlans} from './web/species.ts';
    export {regsData, regulationState} from './web/regs.ts';
    export * as state from './web/state.ts';
    export {render} from 'preact-render-to-string'; export {h} from 'preact';`},
    bundle:true,format:'esm',platform:'node',outfile:out,logLevel:'silent',jsx:'automatic',jsxImportSource:'preact',plugins:rendererPlugins});
  module = await import(pathToFileURL(out).href); return module;
}
const htmlOf = (m, C) => m.render(m.h(C,{now:NOW}));
function setup(m, target='halibut') {
  m.state.configureStore({v2:true,storage:null});
  m.state.syncFromURL(`https://s.test/map?region=morro-bay&profile=boat&view=plan&target=${encodeURIComponent(target)}`);
  m.regionPlans.value = {region:'morro-bay',plans:PLANS,reviewedAt:INDEX.reviewed_at};
  m.regionUnavailable.value = {region:'morro-bay',targets:UNAVAILABLE};
  m.regionInfo.value = {id:'morro-bay',name:'Morro Bay',timezone:'America/Los_Angeles',center:[35,-121],rules:FIXTURE.region};
  m.regsData.value = null;
  m.camera.value = {latitude:35,longitude:-121,zoom:9}; m.state.presentation.value='chart';
  m.markData.value = {region:FIXTURE.region,atlas:null};
  m.markScreen.value = {status:'ready',boundaries:[],until:Infinity};
}
const plain = html => html.replace(/<[^>]*>/g,' ').replace(/&amp;/g,'&').replace(/&#39;|&#x27;/g,"'").replace(/&quot;/g,'"');
test('render preserves source text, drops empty evidence lists and never exposes withheld sections', async () => {
  const m = await ui(); setup(m,'reef');
  const html = htmlOf(m,m.PlanView), text = plain(html);
  for (const s of planView(PLANS,'reef','plan').sections) assert.ok(text.includes(s.text), s.title);
  assert.match(html, /Plan reviewed/); assert.match(html, /How it&#39;s built|How it's built|How it&#x27;s built/);
  for (const numeric_bite_model of [true,undefined]) {
    m.regionPlans.value = {region:'morro-bay',plans:{reef:{...PLANS.reef,numeric_bite_model}}};
    const held = htmlOf(m,m.PlanView); assert.match(held,/This plan carries a numeric model/); assert.doesNotMatch(held,/What to search for|Confirm on the day|<h3>Evidence/);
  }
  m.regionPlans.value = {region:'morro-bay',plans:{reef:{...PLANS.reef,source_links:[],required_to_confirm:[]}}};
  assert.doesNotMatch(htmlOf(m,m.PlanView), /<ul/);
});
test('plan page renders reviewed source anchors as escaped text', async () => {
  const m = await ui();
  for (const id of ['reef', 'halibut']) {
    setup(m, id);
    const html = htmlOf(m, m.PlanView);
    assert.ok(PLANS[id].source_links.length > 0);
    for (const {title, url} of PLANS[id].source_links) {
      const esc = s => s.replace(/&/g, '&amp;').replace(/</g, '&lt;');
      assert.ok(html.includes(`<a href="${url}" target="_blank" rel="noopener" aria-label="${esc(title)} (opens in a new tab)">${esc(title)}</a>`), `${id} ${url}`);
    }
  }
  const title = '<img src=x onerror=alert(1)> & source';
  setup(m, 'reef');
  m.regionPlans.value = {region: 'morro-bay', plans: {reef: {...PLANS.reef, source_links: [{title, url: 'https://example.test/s'}, {title: 'Unsafe', url: 'http://example.test/s'}]}}};
  const html = htmlOf(m, m.PlanView);
  assert.doesNotMatch(html, /<img/); assert.match(html, /&lt;img src=x onerror=alert\(1\)(?:&gt;|>) &amp; source/);
  assert.doesNotMatch(html, /http:\/\/example\.test/); assert.equal((html.match(/<a href="https:\/\/example\.test\/s"/g) ?? []).length, 1);
  for (const source_links of [[], [{title: 'Unsafe', url: 'javascript:alert(1)'}], [{title: 'Old shape', href: 'https://example.test/s'}]]) {
    m.regionPlans.value = {region: 'morro-bay', plans: {reef: {...PLANS.reef, source_links, required_to_confirm: []}}};
    assert.doesNotMatch(htmlOf(m, m.PlanView), /<ul/);
  }
  m.regionPlans.value = {region: 'morro-bay', plans: {reef: {...PLANS.reef, numeric_bite_model: true}}};
  assert.doesNotMatch(htmlOf(m, m.PlanView), /Evidence|<a href="https:\/\/www\.fisheries/);
  setup(m, 'lobster'); assert.doesNotMatch(htmlOf(m, m.PlanView), /Evidence|ecological evidence/);
});
test('unresearched, unknown and region switches show only their own reason and rules', async () => {
  const m = await ui(); setup(m,'lobster');
  let html = htmlOf(m,m.PlanView); assert.ok(plain(html).includes(UNAVAILABLE.lobster));
  assert.match(html, /<h3>Rules/); assert.doesNotMatch(html, /What to search for|\b(?:prohibit|illegal|not allowed)\b/i);
  m.state.species.value = '<img onerror>';
  html = htmlOf(m,m.PlanView); assert.doesNotMatch(html, /<img/); assert.match(html, /&lt;img/);
  m.state.species.value = 'halibut'; m.state.region.value = 'other';
  html = htmlOf(m,m.PlanView); assert.match(html,/Loading this region/); assert.doesNotMatch(html,/What to search for|Plan reviewed/);
  m.regionPlans.value = {region:'other',plans:{halibut:{...PLANS.halibut,search_for:'New region text'}}};
  assert.match(htmlOf(m,m.PlanView),/New region text/);
  m.regionPlans.value = {region:'other',plans:{}};
  assert.match(htmlOf(m,m.PlanView), /This region has no researched plan/);
});
function fresh() {
  const d = structuredClone(FIXTURE.regulations); d.reviewed_at = NOW.toISOString(); d.rules_review_status='reviewed';
  for (const [id,s] of Object.entries(d.sources)) {
    s.approved_content_sha256='a'.repeat(64);
    d.checks[id]={url:s.url,normalization:s.normalization,status:'unchanged',source_status:'ok',content_sha256:'a'.repeat(64),data_retrieved_at:NOW.toISOString()};
  }
  return d;
}
test('rules use dock day, reef worse member and fail closed on missing, invalid or stale registry', async () => {
  const m = await ui(); setup(m,'reef');
  for (const data of [null,{}, {...fresh(),rules_review_status:'pending'}]) {
    m.regsData.value = {region:'morro-bay',data};
    const html = htmlOf(m,m.TargetRules); assert.match(html,/Check rules/); assert.match(html,/https:\/\/wildlife.ca.gov/); assert.doesNotMatch(html,/Season open/);
  }
  const d = fresh(); d.species.lingcod.windows=[];
  m.regsData.value = {region:'morro-bay',data:d};
  assert.equal(m.targetRules(NOW).state.status,'closed');
  assert.match(htmlOf(m,m.TargetRules),/>Closed</); assert.match(htmlOf(m,m.TargetRules),/Outside the reviewed local season/);
  m.state.species.value='halibut';
  d.species.halibut.windows=[{start:'2026-09-21',end:'2026-09-21'}];
  m.state.hour.value='2026-09-22T18:00:00Z';
  assert.equal(m.targetRules(NOW).state.today,'2026-09-22'); assert.equal(m.targetRules(NOW).state.status,'closed');
  m.state.hour.value=null; d.checks[Object.keys(d.checks)[0]].status='changed';
  d.rules_review_status='pending'; assert.equal(m.targetRules(NOW).state.status,'unknown');
});
test('selector changes all three surfaces without stale prior target; URL plan round trips; nav stays link-only', async () => {
  const m = await ui(); setup(m);
  const surfaces = () => [m.Conditions,m.DensityRow,m.PlanView].map(C => plain(htmlOf(m,C)));
  assert.ok(surfaces().every(s => /halibut/i.test(s)));
  m.state.species.value='reef';
  const rendered=surfaces(); assert.ok(rendered.every(s => s.includes('Lingcod & rockfish') && !/halibut/i.test(s)));
  m.state.syncFromURL(m.state.withParams('https://s.test/map',{view:'plan'})); assert.equal(m.state.appView.value,'plan');
  m.state.syncFromURL('https://s.test/map?view=not-a-view'); assert.equal(m.state.appView.value,'coast');
  const nav = htmlOf(m,m.ViewNav);
  assert.deepEqual([...nav.matchAll(/data-view="([^"]+)"/g)].map(x=>x[1]),['coast','conditions','history','fleet','reports']);
});
test('UI-authored plan copy avoids prediction language while source warnings stay intact', () => {
  const source=readFileSync(new URL('../web/app/PlanView.tsx',import.meta.url),'utf8');
  const uiText=[...Object.values(PLAN_COPY),...pairs.map(([s])=>s),'Confirm on the day','Evidence','Plan reviewed','Rules',"How it's built",'Plan for'];
  assert.doesNotMatch(uiText.join(' '), /\b(?:best|hot|bite|biting|guarantee|likely|chance|odds|confidence|go)\b/i);
  assert.doesNotMatch(source,/thermal_range_c/);
});
test('plan review date is retained by index load without accepting another region', async () => {
  const m=await ui(); setup(m); m.regionPlans.value=null;
  await m.loadPlans('morro-bay',async()=>({ok:true,json:async()=>INDEX}));
  assert.equal(m.regionPlans.value.reviewedAt,INDEX.reviewed_at);
  await m.loadPlans('other',async()=>({ok:true,json:async()=>INDEX}));
  assert.equal(m.regionPlans.value.region,'morro-bay');
});
