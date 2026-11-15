// SCB-17 offline synthetic sites, NEVER live readiness or a legal rules approval.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {spawnSync} from 'node:child_process';
import test from 'node:test';
import {checkRegion, main, reader} from '../scripts/check_region_promotion.mjs';

const NOW = Date.parse('2026-09-21T18:00:00Z'), ISO = new Date(NOW).toISOString();
const BASE = 'https://site.test';
const frozen = JSON.parse(readFileSync(new URL('./fixtures/regulations/fe61-v1.json', import.meta.url)));
const MORRO = JSON.parse(readFileSync(new URL('../regions/morro-bay/region.json', import.meta.url)));
const livePath = id => `/feeds/conditions/regions/${id}/latest.json`;
const dailyPath = id => `/feeds/data/regions/${id}/latest.json`;
const rulesPath = id => `/api/daily?region=${id}&part=regulations`;
const habitatPath = id => `/feeds/tiles/seafloor/manifest-${id}.json`;
const briefPath = id => `/api/daily?region=${id}&part=brief`;

function site(id = 'morro-bay', status = 'active') {
  const region = structuredClone(MORRO);
  region.id = id; region.status = status;
  for (const [field, branch, file] of [['daily_feed','data','latest.json'], ['conditions_feed','conditions','latest.json'], ['intelligence_feed','conditions','intelligence.json']])
    region[field] = `https://raw.githubusercontent.com/Grahammmm/skippercast/${branch}/regions/${id}/${file}`;
  const regulations = structuredClone(frozen.regulations);
  regulations.reviewed_at = new Date(NOW - 3600000).toISOString();
  regulations.rules_review_status = 'reviewed'; regulations.reviewed_regions = [{id, fishing_bounds: region.fishing_bounds}];
  for (const [key, source] of Object.entries(regulations.sources)) {
    source.approved_content_sha256 = 'a'.repeat(64);
    regulations.checks[key] = {url: source.url, normalization: source.normalization, status: 'unchanged', source_status: 'ok', content_sha256: 'a'.repeat(64), data_retrieved_at: ISO};
  }
  const feed = kinds => ({schema_version: 1, region_id: id, generated_at: ISO, sources: Object.fromEntries(kinds.map(kind => [kind, {kind, status: 'ok', data_retrieved_at: ISO}]))});
  const daily = feed(['observation','prediction','advisory','forecast']);
  daily.sources.tides = {kind: 'prediction', status: 'ok', data_retrieved_at: ISO, data: {station: region.stations.tide, datum: 'MLLW', units: 'ft', timezone: 'UTC', coverage_start: new Date(NOW - 3600000).toISOString(), coverage_end: new Date(NOW + 86400000).toISOString(), predictions: [{time: new Date(NOW + 3600000).toISOString(), height_ft: 2, type: 'H'}]}};
  const index = {schema_version: 1, default_region: id, regions: [{id, status, config: `regions/${id}/region.json`}]};
  const files = {
    '/regions/index.json': index, [`/regions/${id}/region.json`]: region,
    [livePath(id)]: feed(['observation']), [dailyPath(id)]: daily,
    [`/feeds/conditions/regions/${id}/intelligence.json`]: feed(['forecast']),
    [`/regions/${id}/regulations-startup.json`]: regulations,
    [rulesPath(id)]: {schema_version: 1, region_id: id, generated_at: ISO, part: 'regulations', catch_probability: null, bite_score: null, regulations},
    [habitatPath(id)]: {schema_version: 1, region: id, status: 'ready', archive_sha256: 'b'.repeat(64), expires_at: '2026-12-31T00:00:00Z'},
    '/api/health': {service: 'SkipperCast', revision: 'c'.repeat(40), revision_dirty: false},
    [`/map?region=${id}`]: '<html><script type="module" src="/client/app.js"></script></html>',
    [briefPath(id)]: {...daily, part: 'brief', reports: [], catch_probability: null, bite_score: null},
  };
  const calls = [];
  const fetchFn = async (url, init) => {
    const u = new URL(url), key = u.pathname + u.search;
    assert.equal(u.origin, BASE); assert.equal(init.method, 'GET'); assert.equal(init.credentials, 'omit'); assert.equal(init.redirect, 'error'); assert.ok(init.signal);
    calls.push(key);
    const body = files[key];
    if (body instanceof Error) throw body;
    if (body instanceof Response) return body.clone();
    return body === undefined ? new Response('', {status: 404}) : typeof body === 'string' ? new Response(body) : Response.json(body);
  };
  return {id, region, regulations, index, daily, files, calls, fetchFn, run: () => checkRegion(id, region, index, reader(BASE, fetchFn), NOW)};
}
const row = (result, name) => result.checks.find(c => c.name === name);

// Positive control meets the original Morro Bay acceptance only in a SYNTHETIC site.
test('synthetic Morro Bay passes all technical checks; preview can pass without a status edit', async () => {
  for (const [id, status] of [['morro-bay','active'], ['cambria-san-simeon','preview']]) {
    const s = site(id, status), result = await s.run();
    assert.equal(result.pass, true, JSON.stringify(result));
    assert.deepEqual(result.checks.map(c => c.name), ['package','feeds','tides','rules','habitat','smoke']);
    assert.equal(s.region.status, status);
    assert.equal(s.calls.length, new Set(s.calls).size, 'one GET per path');
    assert.ok(s.calls.every(p => !p.includes('.pmtiles') && !p.includes('export')));
  }
});

test('draft, unknown, duplicate, mismatched status and unpublished packages fail before feed reads', async () => {
  for (const mutate of [
    s => { s.region.status = 'draft'; }, s => { s.region.id = 'other'; },
    s => { s.index.regions.push(s.index.regions[0]); }, s => { s.index.regions[0].status = 'preview'; },
    s => { s.index.regions = []; }, s => { s.index.regions[0].config = 'https://other.test/region.json'; },
  ]) {
    const s = site(); mutate(s);
    const r = await s.run(); assert.equal(r.pass, false); assert.equal(r.checks.length, 1); assert.equal(row(r,'package').pass, false);
    assert.equal(s.calls.length, 0);
  }
});

test('wrong live region or app feed binding cannot pass using another region\'s fresh feeds', async () => {
  for (const mutate of [s => { s.files['/regions/morro-bay/region.json'] = {...s.region,id:'other'}; }, s => { s.region.daily_feed = s.region.daily_feed.replace('morro-bay','other'); }]) {
    const s=site(); mutate(s); assert.equal(row(await s.run(),'package').pass,false);
  }
});

test('feed identity, missing kinds, stale/invalid/naive/future clocks, transport and malformed JSON fail closed', async () => {
  for (const mutate of [
    s => { s.files[livePath(s.id)].region_id = 'other'; },
    ...['2026-09-21T14:59:59Z','2026-09-21T18:10:01Z','2026-09-21T18:00:00','not-a-date'].map(generated_at => s => { s.files[livePath(s.id)].generated_at = generated_at; }),
    s => { s.files[dailyPath(s.id)].sources = {}; }, s => { delete s.daily.sources.forecast; },
    s => { s.files[livePath(s.id)].sources.observation = {kind:'observation',status:'failed'}; },
    s => { s.files[livePath(s.id)] = new Error('offline'); },
    s => { s.files[livePath(s.id)] = new Response('not JSON'); },
    s => { s.files[livePath(s.id)] = new Response('', {status: 503}); },
    s => { s.files[`/feeds/conditions/regions/${s.id}/intelligence.json`].generated_at = '2026-09-21T14:00:00Z'; },
  ]) {
    const s=site(); mutate(s); const r=await s.run(); assert.equal(row(r,'feeds').pass,false,JSON.stringify(r)); assert.equal(r.pass,false);
  }
});

test('feed boundaries follow fixed catalog caps; declared schedule cannot waive them', async () => {
  for (const [age, pass] of [[3,true],[3.001,false],[-1/6,true],[-0.167,false]]) {
    const s=site(), feed=s.files[livePath(s.id)]; feed.generated_at=new Date(NOW-age*3600000).toISOString(); feed.schedule={max_delay_hours:8760};
    assert.equal(row(await s.run(),'feeds').pass,pass);
  }
});

test('one healthy critical source tolerates a partial outage; whole-kind aged outage fails', async () => {
  const s=site(), sources=s.files[livePath(s.id)].sources;
  sources.backup={kind:'observation',status:'failed',data_retrieved_at:'2026-09-20T00:00:00Z'};
  assert.equal(row(await s.run(),'feeds').pass,true);
  sources.observation=sources.backup;
  assert.equal(row(await s.run(),'feeds').pass,false);
});

test('tide station, source health, coverage, predictions and units must be usable now', async () => {
  for (const mutate of [
    s => { delete s.region.stations.tide; }, s => { s.daily.sources.tides.data.station='9999999'; },
    s => { s.daily.sources.tides.status='retained'; }, s => { s.daily.sources.tides.data_retrieved_at='2026-09-19T00:00:00Z'; },
    s => { s.daily.sources.tides.data.coverage_end=ISO; }, s => { s.daily.sources.tides.data.coverage_start='2026-09-22T00:00:00Z'; },
    s => { s.daily.sources.tides.data.predictions=[]; }, s => { s.daily.sources.tides.data.predictions[0].height_ft=null; },
    s => { s.daily.sources.tides.data.units='m'; },
  ]) { const s=site(); mutate(s); assert.equal(row(await s.run(),'tides').pass,false); }
});

test('ALL species required, including both reef members; fresh daily checks override good startup', async () => {
  for (const mutate of [
    s => { s.regulations.rules_review_status='draft'; }, s => { s.regulations.jurisdiction_id='other'; },
    s => { s.regulations.reviewed_regions=[]; }, s => { s.regulations.valid_through='2026-09-20'; },
    s => { s.regulations.reviewed_regions=[{id:s.id,fishing_bounds:[0,0,1,1]}]; },
    s => { s.regulations.timezone='UTC'; },
    s => { s.regulations.checks['rules-salmon'].status='changed'; },
    s => { s.regulations.checks['rules-salmon'].data_retrieved_at='2026-09-19T00:00:00Z'; },
    s => { s.regulations.checks['rules-salmon'].content_sha256='d'.repeat(64); },
    s => { delete s.files[rulesPath(s.id)]; delete s.files[`/regions/${s.id}/regulations-startup.json`]; },
  ]) {
    const s=site(); mutate(s); const r=await s.run(); assert.equal(row(r,'rules').pass,false,JSON.stringify(r)); assert.equal(r.pass,false);
  }
  const s=site(), daily=structuredClone(s.regulations);
  daily.checks['rules-salmon'].status='changed'; s.files[rulesPath(s.id)].regulations=daily;
  const r=await s.run(); assert.equal(row(r,'rules').pass,false); assert.match(row(r,'rules').detail,/salmon:rules.reason.sourceChanged/);
});

test('location-needed is allowed but cannot mask an unknown second reef species', async () => {
  const s=site();
  const p=s.regulations.species.lingcod, source=p.source_ids[0];
  p.windows=[{start:'2026-01-01',end:'2026-12-31',geography:{kind:'latitude-band',south:35,north:36,source_id:source,note:'Synthetic geographic test'}}];
  assert.equal(row(await s.run(),'rules').pass,true);
  // Separate source for rockfish: the aggregate reef state would otherwise select lingcod's location prompt.
  s.regulations.sources['synthetic-rockfish']=structuredClone(s.regulations.sources[source]);
  s.regulations.checks['synthetic-rockfish']={...s.regulations.checks[source],status:'changed'};
  s.regulations.species.rockfish.source_ids=['synthetic-rockfish'];
  assert.equal(row(await s.run(),'rules').pass,false);
});

test('caller can require a rules horizon; current-year success does not imply future validity', async () => {
  const s=site();
  const r=await checkRegion(s.id,s.region,s.index,reader(BASE,s.fetchFn),NOW,'2027-01-31');
  assert.equal(row(r,'rules').pass,false); assert.match(row(r,'rules').detail,/rules-expire-before-2027-01-31/);
});

test('honest no-publication/held habitat gaps pass B; expired, updating, mismatched or corrupt manifests fail', async () => {
  for (const [body, pass] of [
    [undefined,true], [{region:'morro-bay',status:'held'},true],
    [{region:'other',status:'held'},false], [{region:'morro-bay',status:'updating'},false],
    [{region:'morro-bay',status:'ready',archive_sha256:'bad',expires_at:'2026-12-31T00:00:00Z'},false],
    [{region:'morro-bay',status:'ready',archive_sha256:'b'.repeat(64),expires_at:ISO},false],
    [new Response('',{status:503}),false], [new Response('oops'),false], [new Error('offline'),false],
  ]) { const s=site(); s.files[habitatPath(s.id)]=body; assert.equal(row(await s.run(),'habitat').pass,pass); }
});

test('HTTP 200 alone is not smoke success: revision, app shell and regional brief are checked', async () => {
  for (const mutate of [
    s => { s.files['/api/health'].revision=null; }, s => { s.files['/api/health'].revision_dirty=true; },
    s => { s.files[`/map?region=${s.id}`]='<html>Not found</html>'; },
    s => { s.files[briefPath(s.id)].region_id='other'; }, s => { s.files[briefPath(s.id)].part='regulations'; },
    s => { delete s.files[briefPath(s.id)]; },
  ]) { const s=site(); mutate(s); assert.equal(row(await s.run(),'smoke').pass,false); }
});

test('CLI exit 0/1, JSON, multiple regions, draft reasons, global network failure and input errors', async () => {
  const s=site(), lines=[], options={fetchFn:s.fetchFn,now:NOW,print:x=>lines.push(x)};
  assert.equal(await main(['--base',BASE,'morro-bay'],options),0);
  assert.ok(lines.some(l=>l==='PASS morro-bay'));
  lines.length=0;
  assert.equal(await main(['--base',BASE,'--json','morro-bay','san-diego'],options),1);
  const report=JSON.parse(lines[0]); assert.equal(report.results.length,2);
  assert.equal(report.results[1].region,'san-diego'); assert.match(report.results[1].checks[0].detail,/draft/);
  assert.match(report.scope,/human\/legal approval/);
  lines.length=0;
  assert.equal(await main(['--base',BASE,'--json'],options),1);
  const all=JSON.parse(lines[0]).results;
  assert.ok(all.some(r=>r.region==='morro-bay' && r.pass));
  assert.ok(all.some(r=>r.region==='san-diego' && !r.pass));
  assert.ok(all.every(r=>!['CA','OR'].includes(r.region)));
  for (const args of [['--typo'],['../morro-bay'],['--base'],['--base','https://user:secret@site.test'],['--rules-through','2026-02-30']])
    assert.equal(await main(args,options),2);
  lines.length=0;
  assert.equal(await main(['--base',BASE,'morro-bay','san-diego'],{...options,fetchFn:async()=>{throw new Error('offline');}}),1);
  assert.ok(lines.some(l=>l==='FAIL morro-bay')); assert.ok(lines.some(l=>l==='FAIL san-diego'));
  const help=spawnSync(process.execPath,[new URL('../scripts/check_region_promotion.mjs',import.meta.url).pathname,'--help'],{encoding:'utf8'});
  assert.equal(help.status,0); assert.match(help.stdout,/Usage:/);
});

test('reader refuses off-origin assets and bounds response bytes without retrying', async () => {
  let calls=0;
  const get=reader(BASE,async()=>{calls++;return new Response('x'.repeat(16*1024*1024+1));});
  assert.throws(()=>get('https://other.test/data'),/off-origin/); assert.equal(calls,0);
  await assert.rejects(get('/large'),/response-too-large/); assert.equal(calls,1);
});
