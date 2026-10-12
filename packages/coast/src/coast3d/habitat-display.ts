import {Vector2,ShapeUtils} from 'three';
import {coastPoint} from './grid.ts';
/** Camera-scale presentation; this does not change habitat scoring or geometry. */
export function habitatDisplay(span:number){
 const wide=span>=16000;
 return {mode:wide?'areas':span>=6000?'reefs':'detail',pins:!wide,fillOpacity:wide?.85:span>=6000?.23:.1,outlineOpacity:wide?.3:span>=6000?.55:.8};
}
/** Fill only original admitted polygon rings. Holes remain empty. */
export function habitatTriangles(coordinates:number[][][]):number[]{
 const rings=coordinates.map(r=>r.slice(0,-1).map(c=>{const [x,z]=coastPoint(c[0],c[1]);return new Vector2(x,z);}));
 if(!rings[0]||rings[0].length<3)return [];
 const all=rings.flat(),faces=ShapeUtils.triangulateShape(rings[0],rings.slice(1)),positions:number[]=[];
 for(const face of faces)for(const i of face)positions.push(all[i].x,2.5,all[i].y);
 return positions;
}
