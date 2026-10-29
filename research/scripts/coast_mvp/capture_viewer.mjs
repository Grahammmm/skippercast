import {chromium} from '@playwright/test';
import {mkdir, writeFile, readFile} from 'node:fs/promises';
import assert from 'node:assert/strict';
import {sourceRightsText, validateMvpManifest} from '../../../packages/coast/src/coast3d/mvp.ts';
const origin='http://localhost:5179';
const manifestPath=process.env.C3_MANIFEST;
const manifest=manifestPath ? validateMvpManifest(JSON.parse(await readFile(manifestPath,'utf8'))) : null;
const out=process.env.C3_SCREENSHOTS;
if (!out) throw Error('Set C3_SCREENSHOTS to a task-owned output directory');
await mkdir(out,{recursive:true});
const browser=await chromium.launch({headless:true,args:['--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
try {
  const page=await browser.newPage({viewport:{width:1440,height:1000}});
  const errors=[],requests=[],abortedNonLocalRequests=[];
  page.on('pageerror',e=>errors.push(e.message));
  page.on('response',r=>{if(/\.(png|mvt|pbf)$/.test(r.url()))requests.push({url:r.url(),status:r.status()});});
  await page.route('**/*',route=>{const url=route.request().url(); if(new URL(url).origin===origin)return route.continue(); abortedNonLocalRequests.push(url); return route.abort();});
  await page.goto(origin+'/research/scripts/coast_mvp/viewer-preview.html'+(manifestPath?'?manifest='+encodeURIComponent(manifestPath):''));
  await page.waitForSelector('body[data-ready="true"]',{timeout:60000}).catch(async error=>{console.error({status:await page.locator('#status').innerText(),errors,requests});throw error;});
  assert.equal(await page.locator('body').getAttribute('data-failed'),null);
  assert.match(await page.locator('.coast-mvp-chrome').innerText(),/Not for navigation/);
  assert.equal(await page.locator('.coast-mvp-chrome > strong').innerText(), 'Not for navigation · '+
    (!manifest || manifest.synthetic ? 'SYNTHETIC FIXTURE — not measured bathymetry' : 'Preview — unreviewed terrain'));
  if (manifest) {
    const chrome=await page.locator('.coast-mvp-chrome').innerText();
    assert.ok(chrome.includes('Publication held'));
    for (const source of manifest.sources) {
      assert.ok(chrome.includes(source.attribution)); assert.ok(chrome.includes(sourceRightsText(source)));
    }
  } else {
  assert.match(await page.locator('.coast-mvp-chrome').innerText(),/SYNTHETIC FIXTURE/);
  assert.match(await page.locator('.coast-mvp-chrome').innerText(),/SkipperCast C3 synthetic fixture generator/);
  assert.match(await page.locator('.coast-mvp-chrome').innerText(),/Repository LICENSE/);
  assert.match(await page.locator('.coast-mvp-chrome').innerText(),/Arbitrary synthetic zero/);
  }
  const views=[{name:'oblique',pitch:45,bearing:-25,zoom:15.5},{name:'overhead',pitch:0,bearing:0,zoom:14.5},{name:'shelf-close',pitch:55,bearing:65,zoom:16}];
  // Adapter tile bounds can be much wider than the actual synthetic raster footprint.
  if (manifest) {
    const center=await page.evaluate(()=>{const f=window.preview.map.querySourceFeatures('mvp-contours',{sourceLayer:'contours'})[0]; const points=f.geometry.type==='MultiLineString'?f.geometry.coordinates.flat():f.geometry.coordinates; return points[Math.floor(points.length/2)];});
    for (const view of views) view.center=center;
  }
  for(const v of views){
    await page.evaluate(v=>new Promise(resolve=>{const m=window.preview.map;m.once('idle',()=>resolve());m.jumpTo(v);}),v);
    const features=await page.evaluate(()=>window.preview.map.querySourceFeatures('mvp-contours',{sourceLayer:'contours'}).length);
    assert.ok(features>0,'real decoded contour features: '+JSON.stringify({requests,style:await page.evaluate(()=>window.preview.map.getStyle().sources)}));
    v.actual=await page.evaluate(()=>({zoom:window.preview.map.getZoom(),pitch:window.preview.map.getPitch(),bearing:window.preview.map.getBearing()}));
    await page.screenshot({path:out+'/'+v.name+'.png'});
    v.contourFeatures=features;
  }
  assert.equal(errors.length,0,errors.join('\n'));
  assert.equal(await page.locator('body').getAttribute('data-failed'),null);
  assert.ok(requests.every(r=>r.status===200),JSON.stringify(requests));
  // MapLibre returns displayed (exaggerated) elevation, unlike Mapbox's API.
  const elevation=await page.evaluate(()=>window.preview.map.queryTerrainElevation(window.preview.map.getCenter())/window.preview.map.getTerrain().exaggeration);
  if (!manifest) assert.ok(elevation < -20 && elevation > -350, 'decoded terrain-RGB elevation is negative synthetic seabed: '+elevation);
  assert.ok(requests.some(r=>r.url.endsWith('.png')&&r.status===200));
  assert.ok(requests.some(r=>/\.(mvt|pbf)$/.test(r.url)&&r.status===200));
  assert.deepEqual(abortedNonLocalRequests,[],'no non-local requests');
  // Control proof: hiding the actual contour layer must change the rendered pixels.
  const before=await page.locator('canvas').screenshot();
  await page.evaluate(()=>new Promise(resolve=>{const m=window.preview.map;m.once('idle',()=>resolve());m.setLayoutProperty('contours','visibility','none');}));
  const after=await page.locator('canvas').screenshot();
  assert.notDeepEqual(before,after,'contours affect real rendered canvas');
  const receipt={views,requests,errors,elevation,abortedNonLocalRequests,contourPixelDifference:true, sources:await page.evaluate(()=>window.preview.map.getStyle().sources)};
  await writeFile(out+'/browser-acceptance.json',JSON.stringify(receipt,null,2)+'\n');
  console.log(JSON.stringify(receipt,null,2));
} finally {await browser.close();}
