/** Display interpolation inside complete, adjacent source cells only.
 * No nearest-neighbor filling, offshore extrapolation, or bridging missing cells.
 * Components are blended before deriving current speed/direction.
 */
export type FieldPoint = {lon:number;lat:number;values:number[]};
export type FieldQuad = {west:number;south:number;east:number;north:number;corners:FieldPoint[]};
export type SurfaceField = {
 bounds:[number,number,number,number];step:[number,number];dimensions:number;quads:FieldQuad[];
 sample:(lon:number,lat:number)=>number[]|null;
};
const median=(a:number[])=>a.sort((x,y)=>x-y)[Math.floor(a.length/2)];
function spacing(values:number[]){const axis=[...new Set(values.map(v=>Math.round(v*1e5)/1e5))].sort((a,b)=>a-b);const gaps=axis.slice(1).map((v,i)=>v-axis[i]).filter(d=>d>1e-5);return gaps.length?median(gaps):0;}
export function surfaceField(points:FieldPoint[],opts:{step?:[number,number];maxStep?:[number,number]}={}):SurfaceField|null{
 if(points.length<4||points.length>10_000)return null;
 const dimensions=points[0].values.length;
 if(!dimensions||points.some(p=>!Number.isFinite(p.lon)||!Number.isFinite(p.lat)||p.values.length!==dimensions||!p.values.every(Number.isFinite)))return null;
 const xs=points.map(p=>p.lon),ys=points.map(p=>p.lat),west=Math.min(...xs),east=Math.max(...xs),south=Math.min(...ys),north=Math.max(...ys);
 const [dx,dy]=opts.step??[spacing(xs),spacing(ys)];
 if(dx<=0||dy<=0||!Number.isFinite(dx+dy)||(opts.maxStep&&(dx>opts.maxStep[0]||dy>opts.maxStep[1])))return null;
 const width=Math.round((east-west)/dx)+1,height=Math.round((north-south)/dy)+1;
 if(width*height>100_000)return null;
 const cells=new Map<number,FieldPoint>(),key=(x:number,y:number)=>y*width+x;
 for(const p of points){const x=Math.round((p.lon-west)/dx),y=Math.round((p.lat-south)/dy);
  if(Math.abs(p.lon-west-x*dx)>dx*.015||Math.abs(p.lat-south-y*dy)>dy*.015||cells.has(key(x,y)))return null;
  cells.set(key(x,y),p);
 }
 const quads:FieldQuad[]=[];
 const corners=(x:number,y:number)=>[cells.get(key(x,y)),cells.get(key(x+1,y)),cells.get(key(x+1,y+1)),cells.get(key(x,y+1))];
 for(let y=0;y<height-1;y++)for(let x=0;x<width-1;x++){const c=corners(x,y);if(c.every(Boolean))quads.push({west:west+x*dx,east:west+(x+1)*dx,south:south+y*dy,north:south+(y+1)*dy,corners:c as FieldPoint[]});}
 if(!quads.length)return null;
 return {bounds:[west,south,west+(width-1)*dx,south+(height-1)*dy],step:[dx,dy],dimensions,quads,sample(lon,lat){
  const gx=(lon-west)/dx,gy=(lat-south)/dy;if(gx< -1e-8||gy< -1e-8||gx>width-1+1e-8||gy>height-1+1e-8)return null;
  const x=Math.min(width-2,Math.max(0,Math.floor(gx))),y=Math.min(height-2,Math.max(0,Math.floor(gy))),c=corners(x,y);if(c.some(p=>!p))return null;
  const tx=Math.max(0,Math.min(1,gx-x)),ty=Math.max(0,Math.min(1,gy-y)),weights=[(1-tx)*(1-ty),tx*(1-ty),tx*ty,(1-tx)*ty];
  return Array.from({length:dimensions},(_,i)=>c.reduce((n,p,j)=>n+p!.values[i]*weights[j],0));
 }};
}
export const temperatureColors=['#244f9d','#188eb5','#39c6c2','#a6dda0','#efd477','#f18a65'];
export const currentColors=['#245893','#228fab','#4bcbbb','#d2e59a','#f6c876','#ec8e68'];
export function fieldColor(value:number,low:number,high:number,palette:string[]):[number,number,number]{
 const f=Math.max(0,Math.min(palette.length-1,(value-low)/Math.max(high-low,1e-9)*(palette.length-1))),i=Math.min(palette.length-2,Math.floor(f)),t=f-i;
 const a=parseInt(palette[i].slice(1),16),b=parseInt(palette[i+1].slice(1),16);
 return [16,8,0].map(shift=>Math.round(((a>>shift)&255)*(1-t)+((b>>shift)&255)*t)) as [number,number,number];
}
export function vectorReading(values:number[]){const [u,v]=values;return {speedKnots:Math.hypot(u,v)*1.943844492,towardDeg:(Math.atan2(u,v)*180/Math.PI+360)%360};}
export function temperatureRange(values:number[]):[number,number]{const low=Math.floor(Math.min(...values)),high=Math.ceil(Math.max(...values));return [low,Math.max(low+1,high)];}
/** Contours use only complete quads. Center fan resolves saddle cells consistently. */
export function fieldContours(field:SurfaceField,levels:number[]){
 const features:any[]=[];
 for(const q of field.quads){const nodes=q.corners.map(p=>({lon:p.lon,lat:p.lat,value:p.values[0]}));nodes.push({lon:(q.west+q.east)/2,lat:(q.south+q.north)/2,value:nodes.reduce((n,p)=>n+p.value,0)/4});
  for(const level of levels)for(let k=0;k<4;k++){const triangle=[nodes[k],nodes[(k+1)%4],nodes[4]],hits:number[][]=[];
   for(let j=0;j<3;j++){const a=triangle[j],b=triangle[(j+1)%3];if((a.value<level)===(b.value<level))continue;const t=(level-a.value)/(b.value-a.value);hits.push([a.lon+t*(b.lon-a.lon),a.lat+t*(b.lat-a.lat)]);}
   if(hits.length===2&&Math.hypot(hits[0][0]-hits[1][0],hits[0][1]-hits[1][1])>1e-9)features.push({type:'Feature',properties:{level,label:level.toFixed(1)+'°'},geometry:{type:'LineString',coordinates:hits}});
  }
 }
 return {type:'FeatureCollection' as const,features};
}
