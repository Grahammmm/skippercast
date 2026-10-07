import {resolveHabitatSelection} from '../packages/coast/src/state/habitat-selection.ts';
import {coastTarget} from '../web/coast-context.ts';
/** Restore original shared metadata for visible Conditions without graphics. */
export function initCoastalSelection({scopeId,getPoint,getTarget,getProfile,getSelection,restore,clear}){
 let alive=true,key=null,generation=0,controller=null,timer=null;
 const stop=()=>{generation++;controller?.abort();controller=null;};
 const sync=()=>{
  if(!alive)return;
  if(scopeId!=='coast:central'||document.hidden||document.body.dataset.view!=='forecast'){stop();key=null;return;}
  const id=new URL(location.href).searchParams.get('habitat'),point=getPoint(),target=getTarget(),profile=getProfile();
  const next=JSON.stringify([id,point.latitude,point.longitude,target,profile]);if(next===key)return;key=next;stop();clearTimeout(timer);
  if(!id){clear();return;}
  const current=++generation;controller=new AbortController();const isCurrent=()=>alive&&current===generation;
  clear();
  void resolveHabitatSelection({id,species:coastTarget(target)??target,depthLimitFt:profile==='spear'?60:300},{signal:controller.signal,isCurrent}).then(receipt=>{
   if(!isCurrent())return;
   if(!receipt||Math.abs(receipt.latitude-point.latitude)>.00001||Math.abs(receipt.longitude-point.longitude)>.00001){clear();return;}
   key=JSON.stringify([id,receipt.latitude,receipt.longitude,target,profile]);restore(receipt);const expire=()=>{if(!alive)return;const remaining=Date.parse(receipt.expiresAt)-Date.now();if(remaining>0){timer=setTimeout(expire,Math.min(remaining,2147483647));return;}const selected=getSelection();if(selected?.id===receipt.id&&selected?.latitude===receipt.latitude&&selected?.longitude===receipt.longitude)clear();};expire();
  }).catch(()=>{if(isCurrent())clear();});
 };
 const observer=new MutationObserver(sync);observer.observe(document.body,{attributes:true,attributeFilter:['data-view']});
 for(const event of ['skippercast:location','skippercast:species','visibilitychange'])document.addEventListener(event,sync);
 window.addEventListener('hashchange',sync);window.addEventListener('popstate',sync);sync();
 return {sync,destroy(){alive=false;stop();clearTimeout(timer);observer.disconnect();for(const event of ['skippercast:location','skippercast:species','visibilitychange'])document.removeEventListener(event,sync);window.removeEventListener('hashchange',sync);window.removeEventListener('popstate',sync);}};
}
