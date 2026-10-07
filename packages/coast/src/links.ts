import {fishLink,FISH_REGIONS,canonicalHour} from '../../../web/fish-links.ts';
const own=(key:string)=>Object.hasOwn(FISH_REGIONS,key)?FISH_REGIONS[key]:null;
const centres:Record<string,string>={'morro-bay':'morro','cambria-san-simeon':'cambria','monterey-point-sur':'monterey','big-sur-coast':'big-sur','south-big-sur-san-simeon':'gorda','point-arguello-conception':'conception'};
export function coastURL(href:string):URL {
 const url=fishLink(href),p=url.searchParams;
 if(!['region','coast','place'].some(k=>p.has(k))){const area=p.get('area'),places:Record<string,string>={north:'cambria',central:'morro',south:'avila'};if(area&&Object.hasOwn(places,area))p.set('place',places[area]);}
 const region=p.get('region'),place=p.get('place');
 if(p.has('region')){
  if(region&&Object.hasOwn(centres,region)){if(!place||own(place)!==region)p.set('place',centres[region]);}
  else p.delete('place');
 }else if(p.has('coast')){if(p.get('coast')==='central')p.set('place','coast');else p.delete('place');}
 return url;
}
/** Carry the map's own location into the chart/planner without inventing coverage. */
export function plannerURL(href:string,place:string,section='map'):URL{
 const url=fishLink(href),p=url.searchParams;url.pathname='/';url.hash=section;
 p.set('ui','v1');p.delete('perspective');p.delete('view');p.delete('spot');p.delete('focus');
 p.delete('region');p.delete('coast');p.delete('place');p.delete('area');
 const hour=canonicalHour(p.get('hour'));if(hour)p.set('hour',hour);
 const region=own(place);if(region)p.set('region',region);else p.set('coast','central');
 return url;
}
/** A shared hour may be serialized with minutes, seconds or milliseconds. */
export function matchingHour(hours:readonly {at:string}[],hour:string|null):string|null{
 const ms=hour?Date.parse(hour):NaN;return Number.isFinite(ms)?hours.find(h=>Date.parse(h.at)===ms)?.at??null:null;
}

/** Explicit unsupported/empty geography never receives a default Morro view. */
export function coastAdmission(href:string):boolean{
 const p=coastURL(href).searchParams,place=p.get('place');
 if(!['region','coast','place','area'].some(k=>p.has(k)))return true;
 return !!place&&(place==='coast'||!!own(place));
}
