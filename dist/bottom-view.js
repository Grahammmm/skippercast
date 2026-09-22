// A scientific view of measured elevations. Blank survey cells stay blank.
import { getRegion, assetURL } from "./region.js?v=8.9";
let indexPromise;

export function decodeBottom(data) {
  if (data.schema_version !== 1 || data.encoding !== "base64-int16-le" || data.width !== 129 || data.height !== 129 || data.elevation_unit_m !== 0.1 || data.nodata !== -32768 || !(data.cell_m > 0)) throw new Error("Unsupported survey window");
  const bytes = Uint8Array.from(atob(data.elevations), (c) => c.charCodeAt(0));
  if (bytes.length !== data.width * data.height * 2) throw new Error("Incomplete survey window");
  const view = new DataView(bytes.buffer);
  return Array.from({ length: data.width * data.height }, (_, i) => {
    const n = view.getInt16(i * 2, true);
    return n === data.nodata ? null : n / 10;
  });
}

export function bottomSection(data,bearing=90) {
  const z=decodeBottom(data),a=bearing*Math.PI/180;
  const dx=Math.sin(a),dy=-Math.cos(a),radius=64/Math.max(Math.abs(dx),Math.abs(dy));
  return Array.from({length:129},(_,i)=>{
    const step=(i/128*2-1)*radius,x=64+step*dx,y=64+step*dy,v=z[Math.round(y)*129+Math.round(x)];
    return {x,y,distance_ft:(step+radius)*data.cell_m*3.28084,depth_ft:v===null?null:-v*3.28084};
  });
}

export function renderBottom(canvas, data, mode = "relief", options={}) {
  const z = decodeBottom(data), valid = z.filter(Number.isFinite);
  if (!valid.length) throw new Error("Survey window has no measured cells");
  const lo = Math.min(...valid), hi = Math.max(...valid), range = Math.max(hi-lo, 0.1);
  canvas.width = 720; canvas.height = 440;
  const ctx = canvas.getContext("2d");
  ctx.fillStyle = "#062c39"; ctx.fillRect(0, 0, 720, 440);
  const color = (v, shade=1) => {
    const depth=-v*3.28084;
    if(options.band && depth>=options.band[0] && depth<=options.band[1])return '#e4b661';
    const t=(v-lo)/range;
    return `rgb(${Math.round((28+t*127)*shade)},${Math.round((89+t*122)*shade)},${Math.round((112+t*88)*shade)})`;
  };
  if (mode === "plan") {
    for (let y=0;y<129;y++) for (let x=0;x<129;x++) {
      const v=z[y*129+x]; if(v===null) continue;
      ctx.fillStyle=color(v); ctx.fillRect(174+x*2.88,28+y*2.88,3,3);
    }
    ctx.strokeStyle="#fff"; ctx.lineWidth=2; ctx.beginPath(); ctx.arc(360,214,7,0,Math.PI*2);ctx.stroke();
    ctx.fillStyle="#fff";ctx.font="16px sans-serif";ctx.fillText("Grid N ↑",187,53);
    if(Number.isFinite(options.section)){
      const samples=bottomSection(data,options.section);ctx.strokeStyle='#ff885f';ctx.lineWidth=3;ctx.beginPath();
      samples.forEach((p,i)=>{const x=174+p.x*2.88,y=28+p.y*2.88;i?ctx.lineTo(x,y):ctx.moveTo(x,y);});ctx.stroke();
    }
  } else {
    // Constant 2× vertical scale is stated in the caption; terrain is not normalized to exaggerate flat ground.
    const azimuth=(options.azimuth||0)*Math.PI/180;
    const raw=(x,y,v)=>{const xx=(x-64)*Math.cos(azimuth)-(y-64)*Math.sin(azimuth),yy=(x-64)*Math.sin(azimuth)+(y-64)*Math.cos(azimuth);return [(xx-yy)*Math.sqrt(3)/2,(xx+yy)*.5-(v-lo)/data.cell_m*2];};
    let minY=Infinity,maxY=-Infinity;
    for(let y=0;y<129;y++)for(let x=0;x<129;x++){const v=z[y*129+x];if(v!==null){const p=raw(x,y,v);minY=Math.min(minY,p[1]);maxY=Math.max(maxY,p[1]);}}
    const scale=Math.min(2.6,320/Math.max(1,maxY-minY));
    const project=(x,y,v)=>{const p=raw(x,y,v);return [360+p[0]*scale,45+(p[1]-minY)*scale];};
    const base=project(64,64,z[64*129+64] ?? lo);
    const cells=[];for(let y=0;y<128;y+=2)for(let x=0;x<128;x+=2)cells.push([x,y]);
    cells.sort((a,b)=>raw(...a,lo)[1]-raw(...b,lo)[1]);
    for(const [x,y] of cells) {
      const a=[z[y*129+x],z[y*129+x+2],z[(y+2)*129+x+2],z[(y+2)*129+x]];
      if(a.some(v=>v===null)) continue;
      const pts=[project(x,y,a[0]),project(x+2,y,a[1]),project(x+2,y+2,a[2]),project(x,y+2,a[3])];
      const shade=Math.max(.55,Math.min(1.15, .9+(a[0]-a[2])*.07));
      ctx.fillStyle=color(a.reduce((s,v)=>s+v,0)/4,shade);ctx.beginPath();pts.forEach((p,i)=>i?ctx.lineTo(...p):ctx.moveTo(...p));ctx.closePath();ctx.fill();
    }
    ctx.strokeStyle="#fff";ctx.lineWidth=2;ctx.beginPath();ctx.arc(base[0],base[1],7,0,Math.PI*2);ctx.stroke();
    const center=raw(64,64,lo),north=raw(64,0,lo),a=Math.atan2(north[1]-center[1],north[0]-center[0]);
    ctx.strokeStyle='#fff';ctx.beginPath();ctx.moveTo(62,62);ctx.lineTo(62+28*Math.cos(a),62+28*Math.sin(a));ctx.stroke();
    ctx.fillStyle="#fff";ctx.font="16px sans-serif";ctx.fillText("Grid N",62+39*Math.cos(a)-5,62+39*Math.sin(a)+5);
  }
  ctx.fillStyle="#d9eef0";ctx.font="17px sans-serif";
  ctx.fillText(`${Math.round(data.span_m*3.28084)} ft × ${Math.round(data.span_m*3.28084)} ft`,24,412);
  ctx.fillText(`${(-hi*3.28084).toFixed(0)}–${(-lo*3.28084).toFixed(0)} ft · ${data.vertical_datum==='MLLW'?'MLLW':'source datum'}`,420,412);
}

export async function mountBottom(container, target) {
  const figure=document.createElement("figure");figure.className="bottom-view";
  const title=document.createElement("strong");title.textContent=target.fishing_target===false || target.depth_qualified===false ? "Surveyed seabed sample" : "Seabed at this spot";figure.append(title);
  const status=document.createElement("p");status.className="small";status.textContent="Loading survey…";figure.append(status);
  const anchor=container.querySelector(".stats") || container.querySelector(".area-facts")?.nextElementSibling || container.querySelector('h2')?.nextElementSibling || container.firstElementChild?.nextElementSibling;
  container.insertBefore(figure,anchor || null);
  try {
    if(!assetURL("bottom_index")) throw new Error("No measured seabed image is available for this area.");
    indexPromise ||= fetch(assetURL("bottom_index")).then(r=>{if(!r.ok) throw new Error("Survey index unavailable");return r.json();});
    const index=await indexPromise;
    if(index.region_id!==getRegion().id) throw new Error("Survey belongs to another region");
    const record=index.views[target.id];
    if(record?.status!=="surveyed") throw new Error("No measured seabed image is available for this area. Regional geology cannot resolve individual rocks.");
    const url=new URL(record.path, location.href);
    if(url.origin!==location.origin || !url.pathname.includes(`/regions/${getRegion().id}/bottom/`)) throw new Error("Invalid survey asset path");
    url.searchParams.set("v",record.sha256.slice(0,12));
    const response=await fetch(url); if(!response.ok) throw new Error("Survey window unavailable");
    const bytes=await response.arrayBuffer();
    const hash=Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256",bytes)),n=>n.toString(16).padStart(2,"0")).join("");
    if(hash!==record.sha256) throw new Error("Survey integrity check failed");
    const data=JSON.parse(new TextDecoder().decode(bytes));
    if(data.region_id!==getRegion().id || data.target_id!==target.id) throw new Error("Survey identity mismatch");
    if(!figure.isConnected) return;
    const canvas=document.createElement("canvas");canvas.setAttribute("role","img");
    canvas.setAttribute("aria-label",`Surveyed seabed relief around ${target.id}; ${data.depth_range_ft.join(" to ")} feet deep, ${data.native_resolution_range_m?.join('–')||data.native_cell_m} metre source cells; ${data.cell_m} metre display cells.`);
    const controls=document.createElement("div");controls.className="bottom-controls";
    const caption=document.createElement("figcaption");
    const sourceNotes=document.createElement('details'),sourceSummary=document.createElement('summary'),sourceText=document.createElement('p');
    sourceSummary.textContent='Survey source & limits';
    sourceText.className='small';sourceText.textContent=`This image window may extend beyond the screened footprint and the selected depth band. No individual boulder or fish inference. ${data.source_interpolation||''} ${data.limitations || 'Historical survey; present sediment and vegetation can differ.'}`;
    sourceNotes.append(sourceSummary,sourceText);
    if(String(data.source_url||'').startsWith('https://')){const link=document.createElement('a');link.href=data.source_url;link.target='_blank';link.rel='noopener';link.textContent='Original survey source ↗';sourceNotes.append(link);}
    let mode='relief',azimuth=0,section=90,band=false;
    const tools=document.createElement('details');tools.innerHTML='<summary>Explore depth & cross-section</summary>';
    const fields=document.createElement('div');fields.className='bottom-explorer-controls';
    fields.innerHTML=`<label>Rotate relief <input data-bottom="azimuth" type="range" min="0" max="360" step="5" value="0"></label><label>Section bearing · ° grid<input data-bottom="section" type="range" min="0" max="179" step="1" value="90"></label><label>Highlight from · ft<input data-bottom="min" type="number" min="0" max="1500" value="${Math.floor(data.depth_range_ft[0])}"></label><label>Highlight to · ft<input data-bottom="max" type="number" min="0" max="1500" value="${Math.ceil(data.depth_range_ft[1])}"></label><label><input data-bottom="band" type="checkbox">Highlight this depth band</label>`;
    const profile=document.createElement('canvas');profile.className='bottom-profile';profile.setAttribute('role','img');
    const read=key=>Number(fields.querySelector(`[data-bottom="${key}"]`).value);
    const draw=()=>{
      const limits=[read('min'),read('max')];renderBottom(canvas,data,mode,{azimuth,section,band:band&&limits[0]<=limits[1]?limits:null});
      caption.textContent=`${data.producer || 'USGS'} ${data.survey_year} · ${data.native_resolution_range_m?.join('–')||data.native_cell_m} m source cells · ${Math.round(data.coverage_fraction*100)}% source-grid coverage. ${mode==='relief'?`Relief: 2× vertical scale; ${data.cell_m*2} m drawing mesh.`:`Grid-north-up depth: ${data.cell_m} m drawing cells; orange section line.`} White ring: sample center. ${data.vertical_datum}.`;
      const series=bottomSection(data,section),valid=series.filter(p=>p.depth_ft!==null),lo=Math.min(...valid.map(p=>p.depth_ft)),hi=Math.max(...valid.map(p=>p.depth_ft));
      profile.width=720;profile.height=200;const c=profile.getContext('2d');c.fillStyle='#083546';c.fillRect(0,0,720,200);c.strokeStyle='#e4b661';c.lineWidth=2;let connected=false;
      if(!valid.length){c.fillStyle='#e5f3f4';c.font='16px sans-serif';c.fillText('No source cells on this section.',30,100);profile.setAttribute('aria-label','No source cells on this section.');return;}
      c.beginPath();for(const p of series){if(p.depth_ft===null){connected=false;continue;}const x=50+p.distance_ft/series.at(-1).distance_ft*620,y=30+(p.depth_ft-lo)/Math.max(hi-lo,1)*120;if(connected)c.lineTo(x,y);else c.moveTo(x,y);connected=true;}c.stroke();
      c.fillStyle='#e5f3f4';c.font='15px sans-serif';c.fillText(`${lo.toFixed(1)} ft`,5,25);c.fillText(`${hi.toFixed(1)} ft`,5,162);c.fillText(`0 → ${Math.round(series.at(-1).distance_ft)} ft along ${section}° / ${section+180}° grid section · gaps remain blank`,50,189);
      profile.setAttribute('aria-label',`${section} degree grid section, ${Math.round(series.at(-1).distance_ft)} feet long, depths ${lo.toFixed(1)} to ${hi.toFixed(1)} feet, ${data.vertical_datum}. Independent depth axis scale.`);
    };
    fields.addEventListener('input',()=>{azimuth=read('azimuth');section=read('section');band=fields.querySelector('[data-bottom="band"]').checked;draw();});
    tools.append(fields,profile);const note=document.createElement('p');note.className='small';note.textContent='Bearings follow grid north in the source projection, not true or magnetic north. The section samples the displayed grid. Its depth axis is scaled independently for readability; slopes in this graph are not to scale.';tools.append(note);
    for(const [m,label] of [['relief','Relief'],['plan','From above']]){const b=document.createElement('button');b.type='button';b.textContent=label;b.setAttribute('aria-pressed',String(m==='relief'));b.onclick=()=>{mode=m;for(const s of controls.children)s.setAttribute('aria-pressed',String(s===b));draw();};controls.append(b);}
    status.remove();figure.append(controls,canvas,caption,sourceNotes,tools);draw();
  } catch(e) { status.textContent=e.message; }
}
