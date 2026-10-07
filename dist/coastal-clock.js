import {effect,untracked} from '@preact/signals';
import {hour,parseHour,hourParam,setParams} from '../web/state.ts';
/** One clock node moves between Map and Conditions; model outages never reset it. */
export function initCoastalClock({scopeId,mapHost,forecastHost,onChange=()=>{},now=()=>Date.now()}){
 const start=Math.floor(now()/3600000)*3600;
 const root=document.createElement('div');root.className='coastal-clock';
 root.innerHTML='<label for="coastal-hour">Forecast hour</label><input id="coastal-hour" type="range" min="0" max="168" step="1"><output for="coastal-hour"></output><button type="button">Now</button>';
 const input=root.querySelector('input'),output=root.querySelector('output'),button=root.querySelector('button');let at=start,alive=true,timer=null;
 const move=()=>{(document.body.dataset.view==='forecast'?forecastHost:mapHost).append(root);};
 const publish=()=>{if(!alive)return;clearTimeout(timer);
 at=hour.value===null?Math.floor(now()/3600000)*3600:(parseHour(hour.value)??NaN);const index=(at-start)/3600;
 input.disabled=!Number.isFinite(at)||index<0||index>168;input.value=String(Number.isFinite(index)?Math.max(0,Math.min(168,index)):0);
 output.textContent=Number.isFinite(at)?new Date(at*1000).toLocaleString('en-US',{timeZone:'America/Los_Angeles',weekday:'short',month:'short',day:'numeric',hour:'numeric',minute:'2-digit'})+' PT · '+new Date(at*1000).toISOString().slice(0,16)+'Z'+(input.disabled?' · outside this timeline':''):'Unsupported UTC hour · choose an hour or Now';
 document.dispatchEvent(new CustomEvent('skippercast:time',{detail:{regionId:scopeId,epoch:at}}));onChange(at);
 if(hour.value===null&&!document.hidden)timer=setTimeout(publish,3600000-now()%3600000+10);};
 input.addEventListener('input',()=>setParams({hour:hourParam(start+Number(input.value)*3600)}));button.addEventListener('click',()=>{if(hour.value===null)publish();else setParams({hour:null});});
 const dispose=effect(()=>{hour.value;untracked(publish);});const observer=new MutationObserver(move);observer.observe(document.body,{attributes:true,attributeFilter:['data-view']});move();
 const onVisible=()=>{if(hour.value===null)publish();};document.addEventListener('visibilitychange',onVisible);
 return {getHour:()=>at,destroy(){if(!alive)return;alive=false;clearTimeout(timer);dispose();observer.disconnect();document.removeEventListener('visibilitychange',onVisible);root.remove();}};
}
