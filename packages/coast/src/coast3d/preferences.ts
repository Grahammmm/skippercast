import type {Mode} from '../types.ts';

export const preferenceCookie='skippercast_home';
export const homeCounties=[
 {id:'slo',name:'San Luis Obispo County',sites:[['morro','Morro Bay Harbor'],['avila','Avila / Port San Luis'],['cambria','Cambria / San Simeon']]},
 {id:'monterey',name:'Monterey County',sites:[['monterey','Monterey Bay'],['carmel','Carmel Bay'],['point-sur','Point Sur'],['big-sur','Big Sur'],['gorda','Southern Big Sur']]},
 {id:'santa-barbara',name:'Santa Barbara County',sites:[['arguello','Point Arguello'],['conception','Point Conception']]}
] as const;
export interface HomePreferences {v:1;place:string;mode:Mode}
export function validPreferences(value:unknown):value is HomePreferences{
 if(!value||typeof value!=='object')return false;
 const p=value as HomePreferences;
 return p.v===1&&homeCounties.some(c=>c.sites.some(s=>s[0]===p.place))&&['boat','shore','spear'].includes(p.mode);
}
export function readPreferences(cookies:string):HomePreferences|null{
 const entry=cookies.split(';').map(s=>s.trim()).find(s=>s.startsWith(preferenceCookie+'='));
 if(!entry)return null;
 try{const value:unknown=JSON.parse(decodeURIComponent(entry.slice(preferenceCookie.length+1)));return validPreferences(value)?{v:1,place:value.place,mode:value.mode}:null;}catch{return null;}
}
export function preferenceHeader(p:HomePreferences,secure:boolean):string{
 if(!validPreferences(p))throw Error('Invalid home preferences');
 return `${preferenceCookie}=${encodeURIComponent(JSON.stringify({v:1,place:p.place,mode:p.mode}))}; Path=/; Max-Age=31536000; SameSite=Lax${secure?'; Secure':''}`;
}
export function forgetPreferenceHeader(secure:boolean):string{return `${preferenceCookie}=; Path=/; Max-Age=0; SameSite=Lax${secure?'; Secure':''}`;}
const portPlaces:Record<string,string>={'morro-bay':'morro','port-san-luis':'avila',monterey:'monterey'};
export function browserPreferences(storage:{cookie:string}):HomePreferences|null{
 let cookie:HomePreferences|null=null;try{cookie=readPreferences(storage.cookie);}catch{}
 try{const port=localStorage.getItem('skippercast-home-port-v1'),mode=localStorage.getItem('skippercast-profile-v1');
  if(port&&Object.hasOwn(portPlaces,port))return {v:1,place:portPlaces[port],mode:mode==='shore'||mode==='spear'?mode:'boat'};
 }catch{}
 return cookie;
}
export function syncPreferences(p:HomePreferences|null):void{
 try{if(!p){localStorage.removeItem('skippercast-home-port-v1');localStorage.removeItem('skippercast-profile-v1');return;}
  const port=Object.entries(portPlaces).find(([,place])=>place===p.place)?.[0];
  if(port)localStorage.setItem('skippercast-home-port-v1',port);else localStorage.removeItem('skippercast-home-port-v1');
  localStorage.setItem('skippercast-profile-v1',p.mode);
 }catch{/* Current choices remain usable when storage is unavailable. */}
}
export function saveBrowserPreferences(storage:{cookie:string},p:HomePreferences,secure:boolean):boolean{
 try{syncPreferences(p);storage.cookie=preferenceHeader(p,secure);const saved=readPreferences(storage.cookie);return saved?.place===p.place&&saved.mode===p.mode;}catch{return false;}
}
/** Explicit shared locations/methods win for this visit; exploration never changes the saved home. */
export function homeURL(input:URL,p:HomePreferences,reset=false):URL{
 const url=new URL(input);
 if(reset){url.search='';url.hash='';}
 if(!url.searchParams.has('place')&&!url.searchParams.has('area'))url.searchParams.set('place',p.place);
 if(!url.searchParams.has('profile'))url.searchParams.set('profile',p.mode);
 return url;
}
export function homeLabel(p:HomePreferences):string{return homeCounties.flatMap(c=>[...c.sites]).find(s=>s[0]===p.place)?.[1]??'Morro Bay Harbor';}
