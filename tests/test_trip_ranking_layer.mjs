import test from 'node:test';
import assert from 'node:assert/strict';
import {initTripRanking} from '../dist/trip-ranking-layer.js';

test('a rejected publication cannot reappear through an old summary event',async()=>{
 const saved=Object.fromEntries(['L','document','fetch','setInterval','requestAnimationFrame'].map(k=>[k,globalThis[k]]));
 const document=new EventTarget(),timers=[],layer={visible:false,clearLayers(){},remove(){this.visible=false;},addTo(){this.visible=true;}};
 const geometry={type:'Polygon',coordinates:[[[-121,35],[-120.99,35],[-120.99,35.01],[-121,35.01],[-121,35]]]};
 const expiry=new Date(Date.now()+86400000).toISOString();
 const publication={region:'morro-bay',status:'ready',expires_at:expiry,archive_sha256:'a'.repeat(64),export_sha256:'b'.repeat(64),verified_at:new Date(Date.now()-1000).toISOString()};
 let manifest={...publication};
 const drawable=()=>({addTo(){return this;},bindTooltip(){return this;},on(){return this;}});
 Object.assign(globalThis,{document,setInterval:fn=>timers.push(fn),requestAnimationFrame:fn=>fn(),fetch:async()=>new Response(JSON.stringify(manifest)),
  L:{layerGroup:()=>layer,canvas:()=>({}),geoJSON:drawable,marker:drawable,divIcon:x=>x}});
 const map={on(){},latLngToLayerPoint(){return {distanceTo:()=>100};},invalidateSize(){},fitBounds(){}};
 const screen={ready:()=>true,pointAllowed:()=>true,geometryAllowed:()=>true};
 const plan={publication,targets:[{id:'a',trip_rank:1,trip_fit:3,latitude:35,longitude:-121,area_ids:['a'],name:'01 LR H3 C90%'}],areas:[{id:'a',geometry}]};
 const dispatch=p=>document.dispatchEvent(new CustomEvent('skippercast:trip-ranked',{detail:p}));
 try{
  initTripRanking(map,screen,()=>{});dispatch({...plan});assert.equal(layer.visible,true);
  manifest={...publication,status:'held'};await timers[0]();assert.equal(layer.visible,false);
  dispatch({...plan});assert.equal(layer.visible,false);
  dispatch({...plan,publication:{...publication,verified_at:new Date(Date.now()+20).toISOString()}});assert.equal(layer.visible,true);
  dispatch({...plan,publication:{...publication,expires_at:'2000-01-01'}});assert.equal(layer.visible,false);
 }finally{Object.assign(globalThis,saved);}
});
