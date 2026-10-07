import {readableReportURL} from '../web/readable-links.ts';
import stylesURL from './coast-conditions.css?url';
import {getRegion} from './region.js';
import {profile} from '../web/state.ts';
import {effect} from '@preact/signals';

/** Source-specific local readings follow the existing Conditions clock. */
export function initCoastConditions({locationUI,weather}) {
 const host=document.getElementById('coast-conditions');
 let report=null,pending=null,alive=true,at=new Date(weather.getHour()*1000);
 const context=()=>{const region=getRegion(),selected=locationUI.get();return {
  regionId:region.id,point:selected?.point??{latitude:NaN,longitude:NaN},
  localAreas:region.map?.local_areas??[],localId:selected?.localId??null,
  profile:profile.value,target:document.getElementById('species-select').value,at,
 };};
 const visible=()=>document.body.dataset.view==='forecast'&&!document.hidden;
 const sync=()=>{const next=context();document.getElementById('coast-readable-link').href=readableReportURL(location.href).href;report?.setContext(next);};
 async function mount(){
  if(pending)return pending;
  pending=(async()=>{const {CoastReport}=await import('../packages/coast/src/coast3d/report.ts');if(!alive)return;
   const root=host.attachShadow({mode:'open'});
   report=new CoastReport({root,managed:true,stylesURL,initialContext:context(),historyReference:true});
   report.setVisible(visible());
  })().catch(error=>{console.warn('Local coastal readings unavailable',error);host.textContent='Local coastal readings could not load. The regional model forecast remains available.';});
  return pending;
 }
 const visibility=()=>{if(visible())void mount();report?.setVisible(visible());};
 const onLocation=()=>sync();
 const onTime=event=>{const d=event.detail;if(d?.regionId===getRegion().id&&Number.isFinite(d.epoch)){at=new Date(d.epoch*1000);sync();}};
 document.addEventListener('skippercast:location',onLocation);document.addEventListener('skippercast:time',onTime);
 document.addEventListener('skippercast:species',sync);document.getElementById('species-select').addEventListener('change',sync);
 document.addEventListener('visibilitychange',visibility);window.addEventListener('hashchange',visibility);window.addEventListener('popstate',sync);
 const observer=new MutationObserver(visibility);observer.observe(document.body,{attributes:true,attributeFilter:['data-view']});
 const dispose=effect(sync);sync();visibility();
 const destroy=()=>{alive=false;report?.destroy();observer.disconnect();dispose();document.removeEventListener('skippercast:location',onLocation);document.removeEventListener('skippercast:time',onTime);document.removeEventListener('skippercast:species',sync);document.getElementById('species-select').removeEventListener('change',sync);document.removeEventListener('visibilitychange',visibility);window.removeEventListener('hashchange',visibility);window.removeEventListener('popstate',sync);};
 window.addEventListener('pagehide',destroy,{once:true});return {destroy};
}
