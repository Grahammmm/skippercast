import {fishLink,FISH_REGIONS,canonicalHour} from './fish-links.ts';
import {coastPlaces} from '../packages/coast/src/coast3d/place-data.ts';

/** Same span↔zoom convention as the shared native viewer adapter. */
export function nativePlaceView(id:string):string|null{
 const place=coastPlaces.find(item=>item[0]===id);if(!place)return null;
 const zoom=Math.max(7,Math.min(18,12-Math.log2(place[4]/7300)));
 return `${place[3].toFixed(5)},${place[2].toFixed(5)},${zoom}`;
}
/** Normalize the actual address before v1 reads/locks its URL store. */
export function fishEntry(href:string):URL{
 const original=new URL(href),p=original.searchParams,url=fishLink(href),next=url.searchParams;
 if(p.has('species')){if(!p.has('target'))next.set('target',p.get('species')??'');next.delete('species');}
 const hour=canonicalHour(next.get('hour'));if(hour)next.set('hour',hour);
 for(const key of ['region','coast','place','area','view','target','profile','hour','mode','species','layer','layers'])if(p.getAll(key).length>1)throw Error('Ambiguous shared selection');
 if(p.has('region')&&!p.get('region')||p.has('coast')&&!p.get('coast'))throw Error('Empty shared geography');
 // Explicit geography and map view are never replaced by a legacy place.
 if(!p.has('region')&&!p.has('coast')){
  const aliases:Readonly<Record<string,string>>={north:'cambria',central:'morro',south:'avila'};
  const place=p.has('place')?p.get('place'):p.has('area')?(Object.hasOwn(aliases,p.get('area')??'')?aliases[p.get('area')!]:null):undefined;
  if(place!==undefined){
   if(!place||place!=='coast'&&!Object.hasOwn(FISH_REGIONS,place))throw Error('Unknown shared geography');
   if(!p.has('view')){const position=nativePlaceView(place);if(position)next.set('view',position);}
  }
 }
 return url;
}
