import test from 'node:test';
import assert from 'node:assert/strict';
import {existsSync} from 'node:fs';
import {chromium} from '@playwright/test';
import {build} from 'esbuild';
import {rendererPlugin} from './helpers/esbuild-url.mjs';
const root=new URL('..',import.meta.url).pathname;
const needsChromium={skip:!existsSync(chromium.executablePath()) && 'chromium not installed'};

test('native order buttons retain stop focus, boundaries, escaping, mixed legs, translations and restore disable',needsChromium,async()=>{
 const bundle=await build({stdin:{resolveDir:root,contents:`
 import {Planner} from './web/app/Planner.tsx';import {createPlanner} from './web/planner.ts';
 import {language,prepareCatalogue} from './web/i18n.ts';import {launchPoints} from './web/launches.ts';
 import {h,render} from 'preact';
 window.boot=()=>{
  const points=[{id:'user:A',name:'Same',latitude:35.1,longitude:-121,category:'other'},{id:'user:B',name:'Same',latitude:35.2,longitude:-121,category:'other'},{id:'user:C',name:'C <img src=x>',latitude:35.3,longitude:-121,category:'other'}];
  const p=createPlanner({atlas:{targets:[],areas:[]},region:{id:'test-coast',timezone:'UTC',mpa:{bounds:[-125,30,-115,40]}},map:{getSize:()=>({x:512}),getBounds:()=>({getWest:()=>-125,getEast:()=>-115,getSouth:()=>30,getNorth:()=>40})},screen:null,getVisible:()=>[],storage:null,loadPorts:async()=>({ports:[]}),emit(){},nav:{open(){},showMap(){},conditions(){}}});
  p.draft.value={...p.draft.value,ids:points.map(t=>t.id),userWaypoints:points};
  launchPoints.value={region:'test-coast',points:[{id:'r',name:'Ramp',latitude:35.4,longitude:-121}]};p.setLaunch(true);
  window.p=p;window.lang=language;window.prep=prepareCatalogue;
  render(h(Planner,{model:p,open:false}),document.getElementById('root'));
 };`},bundle:true,write:false,platform:'browser',format:'iife',jsx:'automatic',jsxImportSource:'preact',plugins:[rendererPlugin]});
 const browser=await chromium.launch({headless:true,args:['--no-sandbox']});
 try{
  const page=await browser.newPage();await page.route('**/*',route=>route.abort());await page.setContent('<div id="root"></div>');await page.addScriptTag({content:bundle.outputFiles[0].text});await page.evaluate(()=>window.boot());
  const row=id=>page.locator(`[data-stop-id="user:${id}"]`);
  assert.equal(await row('A').getByRole('button',{name:'Move up: Same',exact:true}).count(),0);
  assert.equal(await row('C').getByRole('button',{name:'Move down: C <img src=x>',exact:true}).count(),0);
  assert.equal(await page.locator('[data-stop-id="user:launch-r"] button').count(),0);
  const up=row('B').getByRole('button',{name:'Move up: Same',exact:true});await up.focus();await page.keyboard.press('Enter');
  await page.waitForFunction(()=>document.activeElement?.getAttribute('aria-label')==='Move down: Same' && document.activeElement.closest('li').dataset.stopId==='user:B');
  assert.equal(await page.evaluate(()=>window.p.draft.value.ids.join(',')),'user:B,user:A,user:C');
  await page.keyboard.press('Space');await page.waitForFunction(()=>document.activeElement?.closest('li')?.dataset.stopId==='user:B' && window.p.draft.value.ids[1]==='user:B');
  assert.equal(await page.locator('ol[aria-label="Trip legs"] li').first().textContent().then(s=>s.startsWith('Same → Same')),true);
  await page.keyboard.press('Tab');assert.equal(await page.evaluate(()=>document.activeElement.closest('li')?.dataset.stopId),'user:C');
  await page.keyboard.press('Space');await page.waitForFunction(()=>window.p.draft.value.ids[1]==='user:C');
  assert.equal(await page.evaluate(()=>document.activeElement.getAttribute('aria-label')),'Move up: C <img src=x>');
  assert.equal(await row('C').locator('img').count(),0);
  await page.evaluate(async()=>{await window.prep('es');window.lang.value='es';});await page.waitForFunction(()=>document.activeElement?.getAttribute('aria-label')==='Subir C <img src=x>');
  assert.equal(await row('C').getByRole('button',{name:'Subir C <img src=x>',exact:true}).textContent(),'Subir');
  await page.evaluate(()=>window.p.restorePending.value=true);assert.equal(await row('C').getByRole('button').first().isDisabled(),true);
  await page.evaluate(()=>{window.p.restorePending.value=false;window.p.draft.value={...window.p.draft.value,ids:['user:A']};});
  assert.equal(await row('A').getByRole('button').count(),0);
  await page.evaluate(()=>window.p.draft.value={...window.p.draft.value,ids:[]});assert.equal(await page.locator('[data-stop-id] button').count(),0);
  await page.evaluate(()=>window.p.dispose());
 }finally{await browser.close();}
});
