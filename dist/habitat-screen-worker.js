// Full-geometry legal checks run off the UI thread; no centroid shortcuts.
import {geometryIntersects} from './geo-screen.js?v=8.3';
let geometries=[];
self.addEventListener('message',({data})=>{
  if(data.type==='init'){geometries=data.geometries;return;}
  if(data.type!=='screen')return;
  const allowed=[];
  for(let i=0;i<geometries.length;i++)if(!data.closures.some(closed=>geometryIntersects(geometries[i],closed)))allowed.push(i);
  self.postMessage({request:data.request,revision:data.revision,allowed});
});
