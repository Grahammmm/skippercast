import {CoastReport} from './coast3d/report.ts';
import {CoastViewer} from './coast3d/viewer.ts';
import {setupHome} from './coast3d/onboarding.ts';
setupHome(()=>{
 new CoastReport();
 try{const viewer=new CoastViewer(document.getElementById('scene')!);void viewer.load();}catch{document.getElementById('loading')!.innerHTML='Interactive graphics are unavailable on this device. <a href="/report">Open the full fishing report</a>';}
});
