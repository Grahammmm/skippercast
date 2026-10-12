import {selectCurrentFrame} from '../map-sources.ts';
import type {CurrentField,CurrentFrame} from '../ocean-types.ts';
export const currentLayers=['off','wcofs','hfr-1','hfr-6'] as const;
export type CurrentLayer=typeof currentLayers[number];
export function isCurrentLayer(id:unknown):id is CurrentLayer{return currentLayers.some(value=>value===id);}
const object=(value:unknown):value is Record<string,any>=>value!==null&&typeof value==='object'&&!Array.isArray(value);
const instant=(value:unknown)=>typeof value==='string'?Date.parse(value):NaN;
/** Validate the original selected product, not unrelated optional products. */
export function validCurrentField(value:unknown):value is CurrentField{
 if(!object(value)||!isCurrentLayer(value.id)||value.id==='off'||value.surfaceOnly!==true||value.kind!==(value.id==='wcofs'?'forecast':'observation')||typeof value.label!=='string'||!value.label||!Number.isFinite(instant(value.fetchedAt))||!Number.isFinite(value.nativeResolutionKm)||value.nativeResolutionKm<=0||!Array.isArray(value.frames)||!value.frames.length)return false;
 if(value.issuedAt!==undefined&&value.issuedAt!==null&&!Number.isFinite(instant(value.issuedAt)))return false;
 if(value.sampleAt!==undefined&&value.sampleAt!==null&&!Number.isFinite(instant(value.sampleAt)))return false;
 if(value.kind==='forecast'&&!Number.isFinite(instant(value.issuedAt)))return false;
 let previous=-Infinity;
 for(const frame of value.frames){
  if(!object(frame)||!Number.isFinite(instant(frame.validAt))||instant(frame.validAt)<=previous||!Array.isArray(frame.cells))return false;previous=instant(frame.validAt);
  if(!frame.cells.every((cell:unknown)=>object(cell)&&Number.isFinite(cell.lat)&&Math.abs(cell.lat)<=90&&Number.isFinite(cell.lon)&&Math.abs(cell.lon)<=180&&Number.isFinite(cell.uMs)&&Number.isFinite(cell.vMs)&&Number.isFinite(cell.speedKnots)&&cell.speedKnots>=0&&Number.isFinite(cell.towardDeg)&&cell.towardDeg>=0&&cell.towardDeg<=360))return false;
 }
 return true;
}
/** Exact product only. Missing, malformed or ambiguous identity stays a gap.
 * expiresAt is the original admission deadline in epoch milliseconds. */
export function selectedCurrent(fields:unknown,id:CurrentLayer,at:Date,now=new Date()):{field:CurrentField;frame:CurrentFrame;expiresAt:number}|null{
 if(id==='off'||!isCurrentLayer(id)||!Array.isArray(fields))return null;
 const matches=fields.filter(field=>object(field)&&field.id===id);if(matches.length!==1||!validCurrentField(matches[0]))return null;
 const field=matches[0];
 // Observed source clocks use the existing five-minute clock-skew allowance.
 // Forecast valid times remain independently supported into the future.
 if(field.kind==='observation'&&[field.sampleAt,field.issuedAt].some(value=>value!==undefined&&value!==null&&instant(value)>now.getTime()+300000))return null;
 const frame=selectCurrentFrame(field,at,now);if(!frame)return null;
 const expiresAt=Math.min(Date.parse(field.fetchedAt)+6*3600000,field.kind==='forecast'?Date.parse(field.issuedAt!)+36*3600000:Date.parse(frame.validAt)+6*3600000);
 return expiresAt>now.getTime()?{field,frame,expiresAt}:null;
}
