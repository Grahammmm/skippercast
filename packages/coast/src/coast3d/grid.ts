/** Geometry contract shared by the Fish pilot and future SkipperCast wrapper. */
export type Grid={x:number;z:number;size:number;dx:number;dz:number;values:Float32Array;sources?:Uint8Array};
export function gridTriangles(grid:Grid):Uint32Array {
 const {size:n,values:v,sources:s}=grid,out:number[]=[];
 const valid=(a:number,b:number,c:number)=>[a,b,c].every(i=>Number.isFinite(v[i]))&&(!s||(s[a]>0&&s[a]===s[b]&&s[b]===s[c]));
 for(let y=0;y<n-1;y++)for(let x=0;x<n-1;x++){
  const a=y*n+x,b=a+1,c=a+n,d=c+1;
  if(valid(a,c,b))out.push(a,c,b);if(valid(b,c,d))out.push(b,c,d);
 }
 return new Uint32Array(out);
}
export function nearestDepth(grid:Grid,x:number,z:number):number|null{
 const gx=(x-grid.x)/grid.dx,gz=(z-grid.z)/grid.dz;
 if(gx<0||gz<0||gx>grid.size-1||gz>grid.size-1)return null;
 const value=grid.values[Math.round(gz)*grid.size+Math.round(gx)];return Number.isFinite(value)?value:null;
}
export const ORIGIN:[number,number]=[-120.98,35.43];
const R=6378137;
/** Geographic origin (degrees) that scene x/z metres are measured from. */
export type ProjectionOrigin={lat:number;lon:number};
/** Origin-bound scene projection: Web Mercator about `origin`, scaled by cos(lat0) so scene units are local metres. */
export type CoastProjection={origin:Readonly<ProjectionOrigin>;scale:number;forward:(lon:number,lat:number)=>[number,number];inverse:(x:number,z:number)=>[number,number]};
/** Build a pure projection bound to one origin; throws RangeError for a non-finite origin, |lat|>85 or |lon|>180. Operation order matches the legacy exports so the default origin is bit-identical. */
export function projectionFor(origin:ProjectionOrigin):CoastProjection{
 const lat0=origin?.lat,lon0=origin?.lon;
 if(typeof lat0!=='number'||typeof lon0!=='number'||!Number.isFinite(lat0)||!Number.isFinite(lon0)||Math.abs(lat0)>85||Math.abs(lon0)>180)throw new RangeError('projection origin needs finite lat within ±85 and lon within ±180');
 const scale=Math.cos(lat0*Math.PI/180),baseX=R*lon0*Math.PI/180,baseY=R*Math.asinh(Math.tan(lat0*Math.PI/180));
 return Object.freeze({origin:Object.freeze({lat:lat0,lon:lon0}),scale,
  forward:(lon:number,lat:number):[number,number]=>[(R*lon*Math.PI/180-baseX)*scale,-(R*Math.asinh(Math.tan(lat*Math.PI/180))-baseY)*scale],
  inverse:(x:number,z:number):[number,number]=>[(x/scale+baseX)/R*180/Math.PI,Math.atan(Math.sinh((-z/scale+baseY)/R))*180/Math.PI]});
}
const DEFAULT=projectionFor({lat:ORIGIN[1],lon:ORIGIN[0]});
export function coastPoint(lon:number,lat:number):[number,number]{return DEFAULT.forward(lon,lat);}
export function coastLonLat(x:number,z:number):[number,number]{return DEFAULT.inverse(x,z);}
