// Bottom survey window loader (packages/coast/src/bottom/loader.ts), ported from v1 dist/bottom-view.js.
// Fixtures are synthetic; no survey data is read.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {decodeBottom,decodeBottomWindow,bottomProbe,bottomSection,createBottomLoader,type BottomWindowData} from '../../packages/coast/src/bottom/loader.ts';

const b64=(bytes:Uint8Array)=>Buffer.from(bytes).toString('base64');
const f32=(values:number[])=>{const v=new DataView(new ArrayBuffer(values.length*4));values.forEach((x,i)=>v.setFloat32(i*4,x,true));return b64(new Uint8Array(v.buffer));};

function v1(region='morro-bay',target='t1'):BottomWindowData{
 const v=new DataView(new ArrayBuffer(129*129*2));
 for(let i=0;i<129*129;i++)v.setInt16(i*2,i===0?-32768:-(100+(i%129)),true);// -10.0 m .. -22.8 m; first node blank
 return {schema_version:1,encoding:'base64-int16-le',width:129,height:129,elevation_unit_m:0.1,nodata:-32768,cell_m:2,
  elevations:b64(new Uint8Array(v.buffer)),region_id:region,target_id:target,span_m:256,depth_range_ft:[32,75]};
}
function v2(w=4,h=3,region='morro-bay',target='t2'):BottomWindowData{
 const n=w*h,depths=Array.from({length:n},(_,i)=>10+i/2),mask=Array.from({length:n},(_,i)=>i===1?0:1);
 const source={sign:'positive_up',units:'m',datum:'MLLW',datum_realization:'unknown',scale:1,offset:0,scale_offset_applied:false,conflicts:[],
  evidence:[{kind:'raster_header',facts:{sign:'positive_up',units:'m',datum:'MLLW',datum_realization:'unknown',scale:1,offset:0,scale_offset_applied:false}}]};
 return {schema_version:2,width:w,height:h,encoding:'base64-float32-le',byte_order:'little',dtype:'float32',mask_encoding:'base64-uint8',
  cell_m:2,native_cell_m:2,depth_sign:'positive_down',depth_units:'m',uncertainty_kind:'producer_uncertainty_m',vertical_datum:'MLLW',
  datum_realization:'unknown',internal_diagnostic:true,publication_prohibited:true,website:'held',habitat:'unassessed',
  support_kind:'native_grid_node_footprints',coordinate_transform_applied:false,resampled:false,
  crs:{authority:'EPSG:26910',wkt:'PROJCRS["x"]',original_wkt:'BOUNDCRS[]',lineage_sha256:'a'.repeat(64)},
  affine:[2,0,700000,0,-2,3900000],node_span_m:[2*(w-1),2*(h-1)],footprint_span_m:[2*w,2*h],span_m:Math.max(2*w,2*h),
  precision:'unchanged_float32_bits',nodata:'validity_mask',
  vertical:{sign:'positive_down',units:'m',datum:'MLLW',datum_realization:'unknown',scale:1,offset:0,scale_offset_applied:true,
   storage:'normalized_depth',conflicts:[],evidence:source.evidence,lineage:{datum_transform:false,source_vertical:source}},
  depth_m:f32(depths),uncertainty_m:f32(depths.map(()=>0.25)),validity:b64(Uint8Array.from(mask)),
  depth_range_ft:[30,300],display_depth_range_m:[9,90],region_id:region,target_id:target};
}

test('schema 1 decodes decimetre elevations and keeps nodata blank',()=>{
 const z=decodeBottom(v1());assert.equal(z.length,129*129);assert.equal(z[0],null);assert.equal(z[1],-10.1);
 const g=decodeBottomWindow(v1());assert.equal(g.depths[1],10.1);assert.equal(g.mask[0],0);assert.equal(g.uncertainty,null);
 for(const bad of [{width:128},{encoding:'base64-int16-be'},{nodata:0},{cell_m:0},{elevations:'AAAA'}])assert.throws(()=>decodeBottom({...v1(),...bad}));
});
test('schema 2 keeps positive-down depths, mask and producer uncertainty separate from display elevations',()=>{
 const g=decodeBottomWindow(v2());
 assert.deepEqual([g.width,g.height],[4,3]);assert.equal(g.depths[0],10);assert.equal(g.depths[1],null);assert.equal(g.elevations[2],-11);
 assert.equal(g.mask[1],0);assert.equal(g.uncertainty?.[0],0.25);assert.deepEqual(decodeBottom(v2()),g.elevations);
 assert.deepEqual(bottomProbe(v2(),1,0),{valid:false,depth_m:null,uncertainty_m:null,uncertainty_kind:'producer_uncertainty_m'});
 assert.equal(bottomProbe(v2(),0,0).depth_m,10);assert.throws(()=>bottomProbe(v2(),4,0),/outside/);assert.throws(()=>bottomProbe(v2(),0.5,0),/outside/);
});
test('schema 2 rejects any weakened publication, datum, CRS or encoding claim',()=>{
 const mutations:((d:BottomWindowData)=>void)[]=[
  d=>{d.publication_prohibited=false},d=>{d.website='live'},d=>{d.habitat='assessed'},d=>{d.datum_realization='NAVD88'},
  d=>{d.crs.authority='EPSG:4326'},d=>{d.crs.original_wkt='GEOGCRS'},d=>{d.crs.lineage_sha256='x'},d=>{d.affine[0]=1},
  d=>{d.resampled=true},d=>{d.vertical.conflicts=['x']},d=>{d.vertical.lineage.source_vertical.sign='positive_down'},
  d=>{d.vertical.evidence=[]},d=>{d.vertical.lineage.source_vertical.evidence[0].facts.datum='NAVD88'},
  d=>{d.width=129},d=>{d.node_span_m=[0,0]},d=>{d.span_m=1},d=>{d.depth_range_ft=[40,50]},d=>{d.display_depth_range_m=[9,10]},
  d=>{d.depth_m=d.depth_m.slice(4)},d=>{d.validity=b64(Uint8Array.from({length:12},()=>2))},d=>{d.validity=b64(new Uint8Array(12))},
  d=>{d.uncertainty_m=f32(Array(12).fill(0))},d=>{d.depth_m=f32(Array(12).fill(-1))},d=>{d.depth_m=f32(Array(12).fill(100))},
 ];
 for(const [i,mutate] of mutations.entries()){const d=v2();mutate(d);assert.throws(()=>decodeBottomWindow(d),/Invalid private float32 window/,`mutation ${i}`);}
});
test('sections pass through the window centre, span the footprint and leave gaps blank',()=>{
 const east=bottomSection(v2(5,5),90);assert.equal(east.length,5);
 east.forEach((p,i)=>{assert.ok(Math.abs(p.x-i)<1e-9&&Math.abs(p.y-2)<1e-9,`node ${i} on centre row`);});
 assert.ok(Math.abs(east.at(-1)!.distance_ft-8*3.28084)<1e-9);assert.ok(Math.abs(east[0].depth_ft!-15*3.28084)<1e-4);
 const north=bottomSection(v2(3,3),0);assert.deepEqual(north.map(p=>p.x),[1,1,1]);assert.equal(north[2].depth_ft,null,'blank node stays blank');
 assert.throws(()=>bottomSection(v2(),NaN),/bearing/);
 const diagonal=bottomSection(v1(),135);assert.equal(diagonal.length,129);assert.equal(diagonal[0].depth_ft,null);
 assert.ok(diagonal.slice(1).every(p=>Number.isFinite(p.depth_ft)));
});

const ORIGIN='https://skippercast.test';
const sha=(s:string)=>createHash('sha256').update(s).digest('hex');
function site(files:Record<string,string>){
 const calls:string[]=[];
 const fetcher=(async(input:string|URL|Request)=>{
  const url=new URL(String(input));calls.push(url.pathname+url.search);
  const body=files[url.pathname];return body===undefined?new Response('missing',{status:404}):new Response(body);
 }) as typeof fetch;
 return {calls,fetcher};
}
function setup(window:BottomWindowData,status='surveyed',over:Record<string,unknown>={}){
 const body=JSON.stringify(window),path=`regions/morro-bay/bottom/${window.target_id}.json`;
 const index={region_id:'morro-bay',views:{[window.target_id]:{status,path,sha256:sha(body),...over}}};
 return {'/regions/morro-bay/bottom/index.json':JSON.stringify(index),['/'+path]:body};
}
const loader=(files:Record<string,string>,region={id:'morro-bay'})=>{
 const s=site(files);
 return {...s,load:createBottomLoader({fetch:s.fetcher,origin:ORIGIN,currentRegionId:()=>region.id,
  indexURL:id=>id==='morro-bay'?'regions/morro-bay/bottom/index.json':null}).load};
};

test('loader verifies the window hash, cache-busts by digest and caches the index per region',async()=>{
 const files=setup(v1()),l=loader(files);
 const view=await l.load('t1');assert.equal(view.diagnostic,false);assert.equal(view.grid.width,129);
 assert.deepEqual(l.calls,['/regions/morro-bay/bottom/index.json','/regions/morro-bay/bottom/t1.json?v='+sha(files['/regions/morro-bay/bottom/t1.json']).slice(0,12)]);
 await l.load('t1');assert.equal(l.calls.filter(c=>c.endsWith('index.json')).length,1,'index fetched once');
});
test('loader admits schema 2 only behind a private_diagnostic index record, and vice versa',async()=>{
 assert.equal((await loader(setup(v2(),'private_diagnostic')).load('t2')).diagnostic,true);
 await assert.rejects(loader(setup(v2(),'surveyed')).load('t2'),/requires diagnostic index/);
 await assert.rejects(loader(setup(v1(),'private_diagnostic')).load('t1'),/requires schema 2/);
});
test('loader refuses unsurveyed, tampered, cross-origin, cross-region and mismatched windows',async()=>{
 await assert.rejects(loader(setup(v1(),'unsurveyed')).load('t1'),/No measured seabed image/);
 await assert.rejects(loader(setup(v1())).load('other'),/No measured seabed image/);
 await assert.rejects(loader(setup(v1()),{id:'monterey-point-sur'}).load('t1'),/No measured seabed image is available/);
 const tampered=setup(v1());tampered['/regions/morro-bay/bottom/t1.json']+=' ';
 await assert.rejects(loader(tampered).load('t1'),/integrity/);
 await assert.rejects(loader(setup(v1(),'surveyed',{sha256:'nope'})).load('t1'),/integrity/);
 await assert.rejects(loader(setup(v1(),'surveyed',{path:'https://evil.example/regions/morro-bay/bottom/t1.json'})).load('t1'),/Invalid survey asset path/);
 await assert.rejects(loader(setup(v1(),'surveyed',{path:'regions/monterey-point-sur/bottom/t1.json'})).load('t1'),/Invalid survey asset path/);
 const wrongTarget=v1('morro-bay','t1');const files=setup(wrongTarget);
 const swapped=JSON.stringify({...wrongTarget,target_id:'t9'});files['/regions/morro-bay/bottom/t1.json']=swapped;
 files['/regions/morro-bay/bottom/index.json']=JSON.stringify({region_id:'morro-bay',views:{t1:{status:'surveyed',path:'regions/morro-bay/bottom/t1.json',sha256:sha(swapped)}}});
 await assert.rejects(loader(files).load('t1'),/identity mismatch/);
 const foreign=setup(v1());foreign['/regions/morro-bay/bottom/index.json']=foreign['/regions/morro-bay/bottom/index.json'].replace('"region_id":"morro-bay"','"region_id":"monterey-point-sur"');
 await assert.rejects(loader(foreign).load('t1'),/another region/);
});
test('loader drops a load when the region changes mid-flight and retries a failed index read',async()=>{
 const region={id:'morro-bay'},files=setup(v1()),s=site(files);
 const load=createBottomLoader({fetch:(async(u:string)=>{const r=await s.fetcher(u);region.id='avila';return r;}) as typeof fetch,
  origin:ORIGIN,currentRegionId:()=>region.id,indexURL:()=>'regions/morro-bay/bottom/index.json'}).load;
 await assert.rejects(load('t1'),/Region changed/);
 const empty:Record<string,string>={},l=loader(empty);
 await assert.rejects(l.load('t1'),/Survey index unavailable/);
 Object.assign(empty,setup(v1()));assert.equal((await l.load('t1')).grid.width,129,'failed index read is not cached');
});
