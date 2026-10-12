// Presentation-only terrain shading choices (auto exposure, contour spacing and
// sun direction). Pure functions of displayed values: nothing here changes a
// source height, a source identity or what click inspection returns.

/** One US survey foot is close enough to the international foot for display spacing. */
const FOOT=.3048;
/** Contour steps offered, in feet, finest first. */
export const CONTOUR_STEPS_FT=[5,10,20,50,100,250,500] as const;
/** The narrowest depth window the ramp may stretch across, in metres. */
export const MIN_WINDOW_M=6;
/** Contour minor spacing never goes finer than this multiple of the finest grid spacing in view. */
export const SPACING_FACTOR=1.5;
/** Fewer submerged samples than this leave the ramp where it was. */
const MIN_SAMPLES=16;

/**
 * The depth window (metres below `waterReference`, shallow first) the colour
 * ramp spans for the samples in view: roughly the 2nd to 98th percentile of
 * submerged depths, widened to MIN_WINDOW_M so a flat view keeps a calm ramp.
 * Null when too few finite submerged samples are in view.
 */
export function depthWindow(samples:Float32Array|readonly number[],waterReference:number,minWidth=MIN_WINDOW_M):{min:number;max:number}|null{
 const depths:number[]=[];
 for(let i=0;i<samples.length;i++){const v=samples[i]!;if(Number.isFinite(v)&&v<waterReference)depths.push(waterReference-v);}
 if(depths.length<MIN_SAMPLES)return null;
 depths.sort((a,b)=>a-b);
 const at=(q:number)=>depths[Math.min(depths.length-1,Math.max(0,Math.round(q*(depths.length-1))))]!;
 let min=at(.02),max=at(.98);
 if(max-min<minWidth){const mid=(min+max)/2;min=Math.max(0,mid-minWidth/2);max=min+minWidth;}
 return {min,max};
}

/**
 * Contour spacing in metres for a depth window: the finest feet-based step that
 * draws at most about twenty minor lines across the window (so eight or more
 * whenever a finer step would draw over twenty), never finer than
 * SPACING_FACTOR times the finest grid spacing in view. Every fifth line is an
 * index line.
 */
export function contourInterval(windowMetres:number,finestSpacingM:number):{minor:number;index:number}{
 const span=Number.isFinite(windowMetres)&&windowMetres>0?windowMetres:MIN_WINDOW_M,floor=Number.isFinite(finestSpacingM)&&finestSpacingM>0?finestSpacingM*SPACING_FACTOR:0;
 const steps=CONTOUR_STEPS_FT.map(ft=>ft*FOOT),allowed=steps.filter(m=>m>=floor);
 const pick=allowed.find(m=>span/m<=20)??allowed.at(-1)??steps.at(-1)!;
 return {minor:pick,index:pick*5};
}

/**
 * Unit vector towards the sun in the viewer's world frame (x east, y up,
 * z south, as coastPoint projects). Azimuth is clockwise from north.
 */
export function sunDirection(azimuthDeg:number,altitudeDeg:number):[number,number,number]{
 const az=azimuthDeg*Math.PI/180,alt=altitudeDeg*Math.PI/180,flat=Math.cos(alt);
 return [Math.sin(az)*flat,Math.sin(alt),-Math.cos(az)*flat];
}

/** Feet, rounded for a readout. */
export const feet=(metres:number)=>Math.round(metres/FOOT);

/** The readout line: the ramp's span in view and the contour spacing, in feet. */
export function shadingReadout(window:{min:number;max:number}|null,fixed:boolean,contours:{minor:number;index:number}):string{
 const ramp=fixed?'Fixed ramp 0–5,900 ft':window?`Ramp ${feet(window.min).toLocaleString('en-US')}–${feet(window.max).toLocaleString('en-US')} ft in view`:'Ramp waiting for seabed in view';
 return `${ramp} · contours ${feet(contours.minor)} ft, index ${feet(contours.index)} ft`;
}

/** The persistent exaggeration chip: seabed factor and the land's true scale. */
export function reliefChip(factor:number):string{return factor===1?'Seabed true scale · land true scale':`Seabed ×${factor} · land true scale`;}
