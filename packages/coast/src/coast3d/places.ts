import {coastPoint} from './grid.ts';
export const coastPlaces:[string,string,number,number,number][]=[['morro','Morro Bay Harbor',-120.847,35.352,7300],['monterey','Monterey Bay',-121.91,36.62,24000],['carmel','Carmel Bay',-121.96,36.52,12000],['point-sur','Point Sur',-121.94,36.32,18000],['big-sur','Big Sur',-121.9,36.25,18000],['gorda','Southern Big Sur',-121.45,35.9,24000],['cambria','Cambria',-121.11,35.56,12000],['avila','Avila / Port San Luis',-120.76,35.16,10000],['arguello','Point Arguello',-120.64,34.58,18000],['conception','Point Conception',-120.47,34.455,18000],['coast','Monterey → Point Conception',-121.15,35.55,245000]];
const regionPlaces:Record<string,string[]>={'morro-bay':['morro'],'cambria-san-simeon':['cambria'],'monterey-point-sur':['monterey','carmel','point-sur'],'point-arguello-conception':['arguello','conception']};
/** A published region limits naming; proximity never creates a forecast binding. */
export function habitatPlace(region:string,lon:number,lat:number):string{
 const ids=regionPlaces[region];if(!ids||![lon,lat].every(Number.isFinite))return 'coast';const [x,z]=coastPoint(lon,lat);
 const candidates=coastPlaces.filter(p=>ids.includes(p[0]));return candidates.sort((a,b)=>{const pa=coastPoint(a[2],a[3]),pb=coastPoint(b[2],b[3]);return Math.hypot(pa[0]-x,pa[1]-z)-Math.hypot(pb[0]-x,pb[1]-z);})[0]?.[0]??'coast';
}
export function reportAreaPlace(area:string):string{return ({north:'cambria',central:'morro',south:'avila'} as Record<string,string>)[area]??'coast';}
