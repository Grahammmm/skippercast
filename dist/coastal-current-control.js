import {navigate} from '../web/state.ts';
const choices=['off','wcofs','hfr-1','hfr-6'];
/** One explicit source choice moves with the shared workspace. URL wins, including gaps. */
export function initCoastalCurrentControl({mapHost,forecastHost}){
 const root=document.createElement('section');root.className='coastal-current-control';
 root.innerHTML='<label>Surface currents<select aria-label="Surface-current source"><option value="off">Off</option><option value="wcofs">NOAA WCOFS forecast</option><option value="hfr-1">Observed HF radar · 1 km</option><option value="hfr-6">Observed HF radar · 6 km</option></select></label><p role="status"></p>';
 const select=root.querySelector('select'),status=root.querySelector('p'),listeners=new Set();let value='off',alive=true;
 const move=()=>{(document.body.dataset.view==='forecast'?forecastHost:mapHost).append(root);};
 const sync=()=>{value=new URL(location.href).searchParams.get('current')??'off';select.querySelector('[data-unsupported]')?.remove();if(!choices.includes(value)){const option=document.createElement('option');option.value=value;option.textContent='Unsupported source: '+(value||'(empty)');option.dataset.unsupported='true';select.append(option);}select.value=value;status.textContent=value==='off'?'Surface currents off.':choices.includes(value)?'Checking selected surface-current source…':'Unsupported surface-current source. Choose a listed source.';for(const listener of listeners)listener(choices.includes(value)?value:'off');document.dispatchEvent(new CustomEvent('skippercast:current-source'));};
 const change=()=>{const url=new URL(location.href);url.searchParams.set('current',select.value);navigate(url);sync();};select.addEventListener('change',change);
 const observer=new MutationObserver(move);observer.observe(document.body,{attributes:true,attributeFilter:['data-view']});window.addEventListener('popstate',sync);sync();move();
 return {get:()=>choices.includes(value)?value:'off',subscribe(fn){listeners.add(fn);fn(this.get());return()=>listeners.delete(fn);},status(text){if(alive&&choices.includes(value))status.textContent=text;},destroy(){if(!alive)return;alive=false;observer.disconnect();window.removeEventListener('popstate',sync);select.removeEventListener('change',change);listeners.clear();root.remove();}};
}
