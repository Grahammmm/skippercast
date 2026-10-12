export const escapeHTML=(value:unknown)=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]!));
export const value=(v:number|null|undefined,digits=0)=>typeof v==='number'&&Number.isFinite(v)?v.toFixed(digits):'—';
export const time=(at:string,tz:string,options:Intl.DateTimeFormatOptions={hour:'numeric',minute:'2-digit'})=>Number.isFinite(Date.parse(at))?new Intl.DateTimeFormat('en-US',{timeZone:tz,...options}).format(new Date(at)):'Unavailable';
export const direction=(deg:number|null|undefined)=>typeof deg==='number'&&Number.isFinite(deg)?['N','NNE','NE','ENE','E','ESE','SE','SSE','S','SSW','SW','WSW','W','WNW','NW','NNW'][Math.round(deg/22.5)%16]:'—';
export const ageLabel=(at:string,now=new Date())=>{const minutes=Math.round((now.getTime()-Date.parse(at))/60000);return !Number.isFinite(minutes)||minutes<0?'time unavailable':minutes<2?'just now':minutes<60?minutes+'m ago':minutes<1440?Math.floor(minutes/60)+'h ago':Math.floor(minutes/1440)+'d ago';};
export const range=(min:number|null,max:number|null,d=0)=>min===null?'—':min===max?value(min,d):`${value(min,d)}–${value(max,d)}`;
