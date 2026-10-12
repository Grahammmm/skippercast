import {browserPreferences,saveBrowserPreferences,forgetPreferenceHeader,homeCounties,homeLabel,homeURL,syncPreferences,type HomePreferences} from './preferences.ts';
import type {Mode} from '../types.ts';
const $=<T=HTMLElement>(id:string)=>document.getElementById(id) as T;

export function setupHome(start:()=>void){
 const dialog=$<HTMLDialogElement>('home-setup'),form=$<HTMLFormElement>('home-form'),county=$<HTMLSelectElement>('home-county'),site=$<HTMLSelectElement>('home-site');
 let preferences=browserPreferences(document),persisted=!!preferences,started=false;
 const apply=(p:HomePreferences,reset:boolean)=>{history.replaceState(null,'',homeURL(new URL(location.href),p,reset));$('reset').dataset.homePlace=p.place;$('reset').setAttribute('aria-label','Return to '+homeLabel(p));$('home-settings').textContent='Home & style';};
 const launch=()=>{document.body.dataset.setup='ready';if(!started){started=true;start();}};
 const sites=(id:string,place?:string)=>{const c=homeCounties.find(c=>c.id===id)??homeCounties[0];site.replaceChildren(...c.sites.map(([id,name])=>new Option(name,id)));if(place&&c.sites.some(s=>s[0]===place))site.value=place;$('home-coverage').textContent=c.id==='slo'?'Daily forecasts, tides, buoy readings and local fleet reports, alongside the coast map.':'Terrain and reviewed habitat are available. Local forecasts are still being integrated; SLO reports are labeled separately.';};
 county.replaceChildren(...homeCounties.map(c=>new Option(c.name,c.id)));county.onchange=()=>sites(county.value);
 const open=()=>{const p=preferences??{v:1,place:'morro',mode:'boat'};county.value=homeCounties.find(c=>c.sites.some(s=>s[0]===p.place))?.id??'slo';sites(county.value,p.place);form.querySelector<HTMLInputElement>(`input[value="${p.mode}"]`)!.checked=true;$('home-cancel').hidden=!started;$('home-forget').hidden=!persisted;$('home-heading').textContent=started?'Your home water. Your way.':'A better day starts with your coast.';dialog.showModal();};
 dialog.addEventListener('cancel',e=>{if(!started)e.preventDefault();});
 $('home-settings').onclick=open;$('home-cancel').onclick=()=>dialog.close();
 $('home-forget').onclick=()=>{try{document.cookie=forgetPreferenceHeader(location.protocol==='https:');}catch{}syncPreferences(null);preferences=null;persisted=false;$('reset').dataset.homePlace='morro';$('reset').setAttribute('aria-label','Return to Morro Bay Harbor');$('home-forget').hidden=true;$('home-storage').textContent='Saved home removed. Choose a home below to save new preferences.';};
 form.onsubmit=e=>{e.preventDefault();const p:HomePreferences={v:1,place:site.value,mode:new FormData(form).get('fishing-mode') as Mode};const remembered=saveBrowserPreferences(document,p,location.protocol==='https:');preferences=p;persisted=remembered;$('home-memory-status').hidden=remembered;$('home-memory-status').textContent='Using your choices for this visit. Browser cookies are unavailable.';
  const next=homeURL(new URL(location.href),p,true);if(started&&remembered){location.assign(next);return;}apply(p,true);dialog.close();if(started){const locationSelect=$<HTMLSelectElement>('location');locationSelect.value=p.place;locationSelect.dispatchEvent(new Event('change'));window.dispatchEvent(new CustomEvent('coast-home-change',{detail:p}));}else launch();};
 if(preferences){apply(preferences,false);launch();}else if(['place','region','coast','target','profile'].some(k=>new URL(location.href).searchParams.has(k)))launch();else open();
}
