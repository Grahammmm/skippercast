import {createHash} from 'node:crypto';
import {gzipSync} from 'node:zlib';
import {readFileSync} from 'node:fs';
import {readFile} from 'node:fs/promises';
import {test,expect,openMap,checkA11y} from './fixtures.ts';
import {stubLiveFeeds} from '../scripts/measure_startup.mjs';

test('best reefs download complete outlines and confidence titles, and changed data require reranking',async({page,pageErrors},info)=>{
  await stubLiveFeeds(page);
  const region=JSON.parse(readFileSync('dist/regions/morro-bay/region.json','utf8'));
  const closures=region.assets.closures?JSON.parse(readFileSync('dist/'+region.assets.closures,'utf8')):null;
  await page.route('**/api/daily?*',async route=>{
    if(new URL(route.request().url()).searchParams.get('part')!=='additional-closures')return route.fallback();
    return route.fulfill({json:{schema_version:1,region_id:'morro-bay',sources:closures?{'additional-closures':{status:'ok',data_retrieved_at:new Date().toISOString(),data:{sha256:closures.source_sha256}}}:{}}});
  });
  const expires_at=new Date(Date.now()+86400000).toISOString();
  const features=Array.from({length:25},(_,i)=>{
    const x=-121.17+i*.007,y=35.43;
    return {type:'Feature',geometry:{type:'Polygon',coordinates:[[[x,y],[x+.002,y],[x+.002,y+.002],[x,y+.002],[x,y]]]},
      properties:{id:'test-reef-'+String(i).padStart(2,'0'),region:'morro-bay',tier:2,status:'habitat',exportable:true,screen:{status:'pass'},
        waypoint:{longitude:x+.001,latitude:y+.001},source_ids:['synthetic-fixture'],source_year:2008,resolution_m:2,
        metric_support_fraction:.96,interpolation_mask:'unknown',substrate:{known_fraction:1,independent_confirmation:false},
        independent_evidence:[],depth_min_ft:90,depth_max_ft:120,terrain:{score:90-i,grade:'A',relief_210m_m:12},fit:{lingcod:3,'rockfish-reef':3},area_ha:2}};
  });
  let bytes=JSON.stringify({type:'FeatureCollection',region:'morro-bay',expires_at,features});
  const manifest=()=>({region:'morro-bay',status:'ready',archive_sha256:'a'.repeat(64),expires_at,
    export_file:'habitat-export.geojson.gz',export_sha256:createHash('sha256').update(gzipSync(bytes)).digest('hex'),export_bytes:gzipSync(bytes).length,export_decoded_bytes:Buffer.byteLength(bytes)});
  await page.route('**/feeds/tiles/seafloor/manifest-morro-bay.json',r=>r.fulfill({json:manifest()}));
  let hold=false,release=()=>{},started=()=>{};
  await page.route('**/feeds/tiles/seafloor/regions/morro-bay/habitat-export.geojson.gz',async r=>{
    if(hold){hold=false;started();await new Promise<void>(resolve=>{release=resolve;});}
    return r.fulfill({contentType:'application/gzip',body:gzipSync(bytes)});
  });
  await openMap(page);
  await page.locator('[data-nav="export"]').click();
  await expect(page.locator('#export-map')).toBeDisabled();
  hold=true;const pending=new Promise<void>(resolve=>{started=resolve;});
  await page.locator('#export-best').click();await pending;
  await page.locator('[data-scope="none"]').click();release();
  await expect(page.locator('#export-best')).toBeEnabled();
  await expect(page.locator('#export-selection-count')).toHaveText('0 selected');
  await page.locator('#export-best').click();
  await expect(page.locator('#export-scope-status')).toContainText('20 distinct reef spots');
  await expect(page.locator('#export-selection-count')).toHaveText('20 selected');
  await expect(page.locator('#export-spot-list')).toContainText('#1 · Strong · 90% confidence');
  await expect(page.locator('[data-layer="outlines"]')).toBeChecked();
  await expect(page.locator('[data-layer="alignments"]')).not.toBeChecked();
  await expect(page.locator('[data-layer="exclusions"]')).not.toBeChecked();
  await checkA11y(page,'ranked-export',info.project.name);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true);
  await page.screenshot({path:`test-results/${info.project.name}-ranked-export.png`,fullPage:true});
  const [file]=await Promise.all([page.waitForEvent('download'),page.locator('#export-download').click()]);
  const gpx=await readFile(await file.path(),'utf8');
  expect(gpx.match(/<wpt /g)).toHaveLength(20);
  expect(gpx.match(/<trk>/g)).toHaveLength(20);
  expect(gpx).toContain('<name>01 LR H3 C90% 90-120ft</name>');
  expect(gpx).toContain('lat="35.43" lon="-121.17"');
  expect(gpx).not.toContain('<rte>');
  await page.locator('#export-spot-list [data-spot]').first().uncheck();
  await page.locator('#export-search').fill('test-reef');
  await expect(page.locator('#export-spot-list [data-spot]')).toHaveCount(20);
  await page.locator('#export-spot-list [data-spot]').first().check();
  await page.reload();
  await expect(page.locator('#export-scope-status')).toContainText('Saved ranked reefs restored');
  await expect(page.locator('#export-selection-count')).toHaveText('20 selected');
  await page.locator('#export-map').click();
  const first=page.locator('#map .trip-rank-pin[title^="01 "]');
  await expect(first).toBeVisible();
  for(let i=0;i<6&&!await page.locator('#ranked-reef-export').isVisible();i++){
    const before=await first.textContent();await first.click();
    await expect.poll(async()=>await page.locator('#ranked-reef-export').isVisible()||await first.textContent()!==before).toBe(true);
  }
  await expect(page.locator('#ranked-reef-export')).toBeVisible();
  await page.locator('#ranked-reef-export').click();
  await expect(page).toHaveURL(/#export$/);
  features[0].properties.terrain.score=89;
  bytes=JSON.stringify({type:'FeatureCollection',region:'morro-bay',expires_at,features});
  await page.locator('#export-download').click();
  await expect(page.locator('#export-action-status')).toHaveText('Reef data changed. Select Best available again before exporting.');
  expect(pageErrors).toEqual([]);
});
