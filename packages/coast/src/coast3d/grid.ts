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
const R=6378137,scale=Math.cos(ORIGIN[1]*Math.PI/180),baseX=R*ORIGIN[0]*Math.PI/180,baseY=R*Math.asinh(Math.tan(ORIGIN[1]*Math.PI/180));
export function coastPoint(lon:number,lat:number):[number,number]{return [(R*lon*Math.PI/180-baseX)*scale,-(R*Math.asinh(Math.tan(lat*Math.PI/180))-baseY)*scale];}
export function coastLonLat(x:number,z:number):[number,number]{return [(x/scale+baseX)/R*180/Math.PI,Math.atan(Math.sinh((-z/scale+baseY)/R))*180/Math.PI];}
