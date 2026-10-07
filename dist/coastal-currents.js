import {coastFetch} from '../packages/coast/src/transport.ts';
import {selectedCurrent} from '../packages/coast/src/state/current-layer.ts';
import {esc} from './marine-charts.js';
/** Draw only original wet-cell samples from the selected public source. */
export function overviewCurrentChoice(packet,id,at,now=new Date()){
 if(id==='off'||!['wcofs','hfr-1','hfr-6'].includes(id)||packet?.schemaVersion!==1||!Array.isArray(packet.currents))return null;
 return selectedCurrent(packet.currents,id,at,now);
}
export function initCoastalCurrents({map,control,getHour,getScopeId}){
 const layer=L.layerGroup().addTo(map);let alive=true,generation=0,request=null,timer=null;
 const visible=()=>!document.hidden&&document.body.dataset.view==='map'&&document.body.dataset.mapPresentation!=='terrain';
 function stop(){generation++;request?.abort();request=null;clearTimeout(timer);layer.clearLayers();}
 async function refresh(){stop();const id=control.get();if(id==='off')return;if(!visible()){if(document.body.dataset.view==='forecast')control.status('Selected source retained. Open Map to check its original surface-current field.');return;}const gen=generation,at=new Date(getHour()*1000);if(!Number.isFinite(at.getTime())){control.status('Surface currents unavailable: unsupported selected UTC hour.');return;}request=new AbortController();control.status('Checking selected surface-current source…');
 try{const response=await coastFetch('/api/ocean',{cache:'no-store',signal:AbortSignal.any([request.signal,AbortSignal.timeout(20000)])});if(!response.ok)throw Error('unavailable');const saved=response.headers.get('X-SC-Offline'),packet=await response.json();if(!alive||gen!==generation||!visible())return;const choice=overviewCurrentChoice(packet,id,at);if(!choice){control.status('Selected surface-current source has no usable field for this hour. No substitute source is shown.');return;}
 const {field,frame,expiresAt}=choice;for(const c of frame.cells){const icon=L.divIcon({className:'current-vector',html:`<span style="display:block;transform:rotate(${c.towardDeg}deg);color:${id==='wcofs'?'#087a90':'#7645a8'};font-size:23px;font-weight:bold">↑</span>`,iconSize:[24,24],iconAnchor:[12,12]});L.marker([c.lat,c.lon],{icon,title:`${field.label}: ${c.speedKnots} kt toward ${c.towardDeg}°`,keyboard:true}).bindPopup(`<strong>${esc(field.label)}</strong><p>${c.speedKnots.toFixed(2)} kt toward ${c.towardDeg.toFixed(0)}°<br>${esc(frame.validAt)} · ${esc(field.kind)}<br>${field.nativeResolutionKm} km native source · retrieved ${esc(field.fetchedAt)}</p><p>Original wet-cell sample. Surface flow; not bottom current or boat drift.</p>`).addTo(layer);}
 control.status(`${field.label} · ${field.nativeResolutionKm} km native source · ${field.kind} · valid ${frame.validAt} · ${field.issuedAt?'issued '+field.issuedAt:'observed '+(field.sampleAt??frame.validAt)} · retrieved ${field.fetchedAt} · original wet cells; uncovered coast stays empty.${saved?' Saved offline copy · saved '+saved+'; original expiry applies.':''}`);
 // Withdraw readings at their source deadline, including without any interaction.

 timer=setTimeout(()=>{stop();control.status('Selected surface-current source expired. Choose a source again to refresh.');},Math.max(1,expiresAt-Date.now()+1));
 }catch{if(alive&&gen===generation&&visible())control.status('Selected surface-current source unavailable. No substitute source is shown.');}}
 const unsubscribe=control.subscribe(refresh),onTime=e=>{if(e.detail?.regionId===getScopeId())void refresh();};document.addEventListener('skippercast:time',onTime);document.addEventListener('visibilitychange',refresh);
 const observer=new MutationObserver(refresh);observer.observe(document.body,{attributes:true,attributeFilter:['data-view','data-map-presentation']});
 return {destroy(){alive=false;stop();unsubscribe();observer.disconnect();document.removeEventListener('skippercast:time',onTime);document.removeEventListener('visibilitychange',refresh);map.removeLayer(layer);}};
}
