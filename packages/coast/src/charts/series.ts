import {escapeHTML as esc,time,value} from '../ui/format.ts';
export type Point={at:string;value:number|null|undefined};
export type Series={label:string;unit:string;color:string;points:Point[];min?:number;max?:number;gapMs?:number};
export function linePath(points:Point[],x:(at:string)=>number,y:(v:number)=>number,gapMs=90*60000){
 let previous=-Infinity,move=true;
 return points.map(p=>{const t=Date.parse(p.at);if(typeof p.value!=='number'||!Number.isFinite(p.value)||!Number.isFinite(t)){move=true;return '';}
 const command=move||t-previous>gapMs?'M':'L';move=false;previous=t;return `${command}${x(p.at).toFixed(2)},${y(p.value).toFixed(2)}`;}).join(' ');
}
/** Shared time axis with explicit independent row scales and gaps. */
export function chart(rows:Series[],start:string,end:string,selected:string,tz:string,options:{height?:number;mini?:boolean;sunrise?:string|null;sunset?:string|null;windows?:{start:string;end:string}[]}={}){
 const width=840,left=options.mini?0:69,right=options.mini?0:32,rowH=options.mini?80:90,bottom=options.mini?0:30,height=rows.length*rowH+bottom;
 const t0=Date.parse(start),t1=Date.parse(end),x=(at:string)=>left+(Date.parse(at)-t0)/(t1-t0||1)*(width-left-right);
 let content='';
 if(options.sunrise&&options.sunset){const dawn=Math.max(left,Math.min(width-right,x(options.sunrise))),dusk=Math.max(left,Math.min(width-right,x(options.sunset)));content+=`<rect x="${left}" y="0" width="${dawn-left}" height="${height-bottom}" style="fill:var(--coast-night,#030d17)" opacity=".5"/><rect x="${dusk}" y="0" width="${width-right-dusk}" height="${height-bottom}" style="fill:var(--coast-night,#030d17)" opacity=".5"/>`;}
 for(const w of options.windows??[]){const a=Math.max(left,x(w.start)),b=Math.min(width-right,x(w.end));if(b>a)content+=`<rect x="${a}" y="0" width="${b-a}" height="${height-bottom}" style="fill:var(--coast-mint,#58e8b8)" opacity=".08"/>`;}
 const ticks=options.mini?[]:[0,.25,.5,.75,1];
 content+=ticks.map(f=>`<line x1="${left+f*(width-left-right)}" x2="${left+f*(width-left-right)}" y1="0" y2="${height-bottom}" style="stroke:var(--coast-muted,#86abc2)" stroke-opacity=".1"/><text x="${left+f*(width-left-right)}" y="${height-6}" text-anchor="middle" class="axis">${time(new Date(t0+f*(t1-t0)).toISOString(),tz,{hour:'numeric'})}</text>`).join('');
 rows.forEach((inputRow,i)=>{const row={...inputRow,points:inputRow.points.filter(p=>Date.parse(p.at)>=t0&&Date.parse(p.at)<=t1)};const offset=i*rowH,values=row.points.map(p=>p.value).filter((v):v is number=>typeof v==='number'&&Number.isFinite(v));const low=row.min??Math.min(0,...values),high=row.max??Math.max(low+1,...values)*1.15;const y=(v:number)=>offset+rowH-13-(v-low)/(high-low)*(rowH-29);
  const path=linePath(row.points.filter(p=>Date.parse(p.at)>=t0&&Date.parse(p.at)<=t1),x,y,row.gapMs);
  if(!options.mini)content+=`<text x="0" y="${offset+22}" class="axis-label" style="fill:${row.color}">${esc(row.label)}</text><text x="0" y="${offset+39}" class="axis">${esc(row.unit)}</text><text x="${width-2}" y="${offset+20}" text-anchor="end" class="axis">${value(high,0)}</text><text x="${width-2}" y="${offset+rowH-13}" text-anchor="end" class="axis">${value(low,0)}</text>`;
  content+=`<line x1="${left}" x2="${width-right}" y1="${offset+rowH-12}" y2="${offset+rowH-12}" style="stroke:var(--coast-muted,#86abc2)" stroke-opacity=".12"/>`;
  content+=values.length?`<path d="${path}" style="stroke:${row.color}" stroke-width="2" fill="none" vector-effect="non-scaling-stroke"/>`:`<text x="${width/2}" y="${offset+rowH/2}" class="axis" text-anchor="middle">No supported samples</text>`;
 });
 const cursor=x(selected);if(cursor>=left&&cursor<=width-right)content+=`<line x1="${cursor}" x2="${cursor}" y1="0" y2="${height-bottom}" style="stroke:var(--coast-text,#e3f7ff)" stroke-opacity=".65" stroke-dasharray="3 4"/><circle cx="${cursor}" cy="4" r="3" style="fill:var(--coast-text,#e3f7ff)"/>`;
 return `<svg class="series-chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="${esc(rows.map(r=>r.label+' in '+r.unit).join(', '))}. Independent row scales; gaps remain blank.">${content}</svg>`;
}
