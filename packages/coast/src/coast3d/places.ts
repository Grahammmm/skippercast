import {coastPoint} from './grid.ts';
import {coastPlaces} from './place-data.ts';
export {coastPlaces} from './place-data.ts';
const regionPlaces:Record<string,string[]>={'morro-bay':['morro'],'cambria-san-simeon':['cambria'],'monterey-point-sur':['monterey','carmel','point-sur'],'point-arguello-conception':['arguello','conception']};
/** A published region limits naming; proximity never creates a forecast binding. */
export function habitatPlace(region:string,lon:number,lat:number):string{
 if(![lon,lat].every(Number.isFinite)||Math.abs(lon)>180||Math.abs(lat)>90)return 'coast';
 const ids=Object.hasOwn(regionPlaces,region)?regionPlaces[region]:undefined;if(!ids)return 'coast';const [x,z]=coastPoint(lon,lat);
 const candidates=coastPlaces.filter(p=>ids.includes(p[0]));return candidates.sort((a,b)=>{const pa=coastPoint(a[2],a[3]),pb=coastPoint(b[2],b[3]);return Math.hypot(pa[0]-x,pa[1]-z)-Math.hypot(pb[0]-x,pb[1]-z);})[0]?.[0]??'coast';
}
const areaPlaces:Record<string,string>={north:'cambria',central:'morro',south:'avila'};
export function reportAreaPlace(area:string):string{return Object.hasOwn(areaPlaces,area)?areaPlaces[area]:'coast';}
