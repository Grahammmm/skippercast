import {coastPath} from './transport.ts';
import panelStyles from '../panel.css?url';
import {CoastReport} from './coast3d/report.ts';
import {CoastViewer} from './coast3d/viewer.ts';
import {setupHome} from './coast3d/onboarding.ts';
import {coastURL,plannerURL,coastAdmission} from './links.ts';
for(const link of document.querySelectorAll<HTMLAnchorElement>('[data-coast-receipt]'))link.href=coastPath(link.dataset.coastReceipt!);
const url=coastURL(location.href);
const target=url.searchParams.get('target');
const targets=[...document.querySelectorAll<HTMLOptionElement>('#species option')].map(o=>o.value);
if(!coastAdmission(location.href)||(target&&!targets.includes(target))){const chart=new URL(location.href);chart.pathname='/';chart.searchParams.set('ui','v1');location.replace(chart);}else{history.replaceState(null,'',url);
const chart=document.getElementById('full-report-link') as HTMLAnchorElement;
const nav=chart.parentElement!,perspectives=nav.querySelector('.perspectives')!,mobile=matchMedia('(max-width:850px)');
const placeTools=()=>{if(mobile.matches)document.querySelector('.layers')!.append(chart);else nav.insertBefore(chart,perspectives);};
mobile.addEventListener('change',placeTools);placeTools();
const update=()=>{chart.href=plannerURL(location.href,new URL(location.href).searchParams.get('place')??'morro','map').href;};
window.addEventListener('pagehide',()=>mobile.removeEventListener('change',placeTools),{once:true});
window.addEventListener('coast-place-change',update);window.addEventListener('coast-report-clock-change',update);update();
setupHome(()=>{
 document.getElementById('report-content')!.dataset.styles=panelStyles;
 new CoastReport();
 try{const viewer=new CoastViewer(document.getElementById('scene')!);void viewer.load();}
 catch{document.getElementById('loading')!.innerHTML='Interactive graphics are unavailable on this device. <a href="/">Open the chart and trip tools</a>';}
});
window.addEventListener('popstate',()=>location.reload());

}
