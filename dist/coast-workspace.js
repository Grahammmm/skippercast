// One native terrain presentation within the existing chart/planning workspace.
// The chart owns region, target, location and hour; the renderer owns its camera.
import template from './coast.html?raw';
import viewStyles from './coast-workspace-view.css?url';
import {getRegion} from './region.js';
import {navigate,profile,setParams} from '../web/state.ts';
import {effect} from '@preact/signals';
import {coastPath} from '../packages/coast/src/transport.ts';
import {coastTarget,hasCoastTerrain,presentationFromURL,presentationURL,habitatURL} from '../web/coast-context.ts';

export function initCoastWorkspace({map,locationUI,weather,resizeChart=()=>map.invalidateSize({pan:false}),currentControl=null,getScope=()=>({id:getRegion().id,terrainAvailable:hasCoastTerrain(getRegion().id)})}) {
 const select=document.getElementById('map-presentation');
 const host=document.getElementById('coast-workspace');
 const status=document.getElementById('map-presentation-status');
 const method=document.getElementById('fishing-profile');
 const scope=getScope(),supported=scope.terrainAvailable;host.dataset.scope=scope.id;
 for(const option of select.options)if(option.value!=='chart')option.disabled=!supported;
 let viewer=null,pending=null,alive=true,mode='chart',point=null,forecastAt=null,lastTarget=null;
 const home={...map.getCenter()},homeZoom=map.getZoom();
 const announce=text=>{status.textContent=text;status.hidden=!text;};
 const target=()=>document.getElementById('species-select').value;
 const syncTarget=()=>{if(viewer){const native=coastTarget(target())??target();if(native!==lastTarget){lastTarget=native;viewer.setSpecies(native);}}};
 const syncMethod=()=>{method.value=profile.value;viewer?.setDepthLimit(profile.value==='spear'?60:300);};
 const chartSpan=()=>Math.max(1200,Math.min(245000,7300*Math.pow(2,12-map.getZoom())));
 const syncPoint=next=>{
  if(!Number.isFinite(next?.latitude)||!Number.isFinite(next?.longitude))return;
  const span=chartSpan();
  if(point&&Math.abs(point.latitude-next.latitude)<.00001&&Math.abs(point.longitude-next.longitude)<.00001&&Math.abs((point.span??0)-span)<.01)return;
  point={latitude:next.latitude,longitude:next.longitude,span};
  viewer?.setLocation(point);
 };
 async function mount() {
  if(pending)return pending;
  pending=(async()=>{
   const {CoastViewer}=await import('../packages/coast/src/coast3d/viewer.ts');
   if(!alive)return false;
   const root=host.attachShadow({mode:'open'}),parsed=new DOMParser().parseFromString(template,'text/html');
   const style=document.createElement('link');style.rel='stylesheet';style.href=viewStyles;root.append(style);
   root.append(document.importNode(parsed.getElementById('scene'),true),document.importNode(parsed.getElementById('sources'),true));
   root.querySelector('.intro').hidden=true;
   root.querySelector('.layers h2').remove();root.querySelector('.layers>.eyebrow').remove();
   root.querySelector('[for="species"]').hidden=true;root.getElementById('species').hidden=true;
   if(currentControl)root.getElementById('currents').closest('label').hidden=true;
   const toggle=root.getElementById('layers-toggle');toggle.textContent='Terrain layers & evidence';
   const controls=root.querySelector('.view-controls');
   for(const id of ['perspective-2d','perspective-3d']){const button=document.createElement('button');button.id=id;button.hidden=true;controls.append(button);}
   const sources=document.createElement('button');sources.id='sources-open';sources.textContent='ⓘ';sources.setAttribute('aria-label','Terrain sources and assumptions');controls.append(sources);
   for(const link of root.querySelectorAll('[data-coast-receipt]'))link.href=coastPath(link.dataset.coastReceipt);
   for(const link of root.querySelectorAll('a[href="index.html#forecast"]'))link.href='#forecast';
   viewer=new CoastViewer(root.getElementById('scene'),{root,managed:true,onCurrentStatus:text=>{if(currentControl&&mode!=='chart'&&document.body.dataset.view==='map')currentControl.status(text);},onView:view=>{
    point={latitude:view.latitude,longitude:view.longitude};
    const zoom=Math.max(7,Math.min(18,12-Math.log2(view.span/7300)));
    map.setView([view.latitude,view.longitude],zoom,{animate:false});
    point={latitude:view.latitude,longitude:view.longitude,span:chartSpan()};
   },onSelectionInvalidated:()=>locationUI.clear?.(),onRestoredSelection:selected=>locationUI.restore?.(selected),onSelection:selected=>{
    // Existing location resolution enforces geographic forecast/legal binding.
    point={latitude:selected.latitude,longitude:selected.longitude};
    map.setView([selected.latitude,selected.longitude],Math.max(12,map.getZoom()),{animate:false});
    locationUI.select({...selected,label:'Selected coastal habitat'});
    const selectionURL=habitatURL(location.href,selected.id??null);selectionURL.searchParams.set('view',`${selected.latitude.toFixed(5)},${selected.longitude.toFixed(5)},${map.getZoom()}`);navigate(selectionURL,{replace:true});
   }});
   root.getElementById('top').onclick=()=>void apply('2d',true);
   const clearSelection=()=>{viewer.selectHabitat(null);locationUI.clear?.();navigate(habitatURL(location.href,null),{replace:true});};
   root.getElementById('target-close').onclick=clearSelection;
   root.getElementById('reset').setAttribute('aria-label','Reset map view');
   root.getElementById('reset').onclick=()=>{
    clearSelection();locationUI.clear();point=null;map.setView(home,homeZoom,{animate:false});syncPoint({latitude:home.lat,longitude:home.lng});
   };
   viewer.setCurrentLayer?.(currentControl?.get()??'off');syncTarget();syncMethod();
   const savedPoint=point;point=null;syncPoint(savedPoint??locationUI.get()?.point??{latitude:home.lat,longitude:home.lng});
   viewer.setHour(forecastAt);viewer.setPerspective(mode==='2d'?'2d':'3d');
   viewer.selectHabitat(new URL(location.href).searchParams.get('habitat'));
   viewer.setVisible(mode!=='chart'&&document.body.dataset.view==='map'&&!document.hidden);
   return viewer.load();
  })().catch(error=>{console.error('Coastal presentation unavailable',error);return false;});
  return pending;
 }
 async function apply(next,write=false) {
  if(next!=='chart'&&!supported)next='chart';
  mode=next;select.value=next;
  if(write)navigate(presentationURL(location.href,next));
  document.body.dataset.mapPresentation=next==='chart'?'chart':'terrain';
  host.hidden=next==='chart';
  if(next==='chart'){viewer?.setVisible(false);if(document.body.dataset.view==='map')resizeChart();announce('');return;}
  announce('Loading the reviewed coast…');
  const ready=await mount();if(!alive||mode==='chart')return;
  if(!ready){for(const option of select.options)if(option.value!=='chart')option.disabled=true;mode='chart';select.value='chart';host.hidden=true;document.body.dataset.mapPresentation='chart';viewer?.setVisible(false);if(document.body.dataset.view==='map')resizeChart();announce('Coastal graphics are unavailable. The chart, forecasts and trip tools remain usable. Reload to retry the coast.');return;}
  viewer.setPerspective(mode);viewer.setVisible(document.body.dataset.view==='map'&&!document.hidden);announce('');
 }
 const onLocation=event=>{const context=event.detail;if(context?.regionId===scope.id)syncPoint(context.point);syncTarget();};
 const onTime=event=>{const epoch=event.detail?.epoch;if(event.detail?.regionId===scope.id&&typeof epoch==='number'){forecastAt=new Date(epoch*1000);viewer?.setHour(forecastAt);}};
 const onHistory=()=>{void apply(presentationFromURL(location.href));viewer?.selectHabitat(new URL(location.href).searchParams.get('habitat'));};
 const visibility=()=>viewer?.setVisible(mode!=='chart'&&document.body.dataset.view==='map'&&!document.hidden);
 select.addEventListener('change',()=>void apply(select.value,true));
 method.addEventListener('change',()=>setParams({profile:method.value}));
 document.addEventListener('skippercast:species',syncTarget);document.getElementById('species-select').addEventListener('change',syncTarget);
 document.addEventListener('skippercast:location',onLocation);document.addEventListener('skippercast:time',onTime);
 window.addEventListener('popstate',onHistory);window.addEventListener('hashchange',visibility);document.addEventListener('visibilitychange',visibility);
 const observer=new MutationObserver(visibility);observer.observe(document.body,{attributes:true,attributeFilter:['data-view']});
 const disposeMethod=effect(syncMethod);
 const disposeCurrent=currentControl?.subscribe(id=>viewer?.setCurrentLayer(id))??(()=>{});
 const destroy=()=>{alive=false;viewer?.destroy();observer.disconnect();disposeMethod();disposeCurrent();document.removeEventListener('skippercast:species',syncTarget);document.getElementById('species-select').removeEventListener('change',syncTarget);document.removeEventListener('skippercast:location',onLocation);document.removeEventListener('skippercast:time',onTime);window.removeEventListener('popstate',onHistory);window.removeEventListener('hashchange',visibility);document.removeEventListener('visibilitychange',visibility);};
 window.addEventListener('pagehide',destroy,{once:true});
 const selectedHour=weather.getHour();forecastAt=new Date(selectedHour*1000);
 syncMethod();syncPoint(locationUI.get()?.point);void apply(presentationFromURL(location.href));
 return {destroy,clearSelection:()=>viewer?.selectHabitat(null)};
}
