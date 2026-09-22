// A scientific view of measured elevations. Blank survey cells stay blank.
import { getRegion, assetURL } from "./region.js?v=7.0";
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

export function renderBottom(canvas, data, mode = "relief") {
  const z = decodeBottom(data), valid = z.filter(Number.isFinite);
  if (!valid.length) throw new Error("Survey window has no measured cells");
  const lo = Math.min(...valid), hi = Math.max(...valid), range = Math.max(hi-lo, 0.1);
  canvas.width = 720; canvas.height = 440;
  const ctx = canvas.getContext("2d");
  ctx.fillStyle = "#062c39"; ctx.fillRect(0, 0, 720, 440);
  const color = (v, shade=1) => {
    const t=(v-lo)/range;
    return `rgb(${Math.round((28+t*127)*shade)},${Math.round((89+t*122)*shade)},${Math.round((112+t*88)*shade)})`;
  };
  if (mode === "plan") {
    for (let y=0;y<129;y++) for (let x=0;x<129;x++) {
      const v=z[y*129+x]; if(v===null) continue;
      ctx.fillStyle=color(v); ctx.fillRect(174+x*2.88,28+y*2.88,3,3);
    }
    ctx.strokeStyle="#fff"; ctx.lineWidth=2; ctx.beginPath(); ctx.arc(360,214,7,0,Math.PI*2);ctx.stroke();
    ctx.fillStyle="#fff";ctx.font="16px sans-serif";ctx.fillText("N ↑",187,53);
  } else {
    // Constant 2× vertical scale is stated in the caption; terrain is not normalized to exaggerate flat ground.
    const raw=(x,y,v)=>[(x-y)*Math.sqrt(3)/2,(x+y)*.5-(v-lo)/data.cell_m*2];
    let minY=Infinity,maxY=-Infinity;
    for(let y=0;y<129;y++)for(let x=0;x<129;x++){const v=z[y*129+x];if(v!==null){const p=raw(x,y,v);minY=Math.min(minY,p[1]);maxY=Math.max(maxY,p[1]);}}
    const scale=Math.min(2.6,320/Math.max(1,maxY-minY));
    const project=(x,y,v)=>{const p=raw(x,y,v);return [360+p[0]*scale,45+(p[1]-minY)*scale];};
    const base=project(64,64,z[64*129+64] ?? lo);
    for(let y=0;y<128;y+=2) for(let x=0;x<128;x+=2) {
      const a=[z[y*129+x],z[y*129+x+2],z[(y+2)*129+x+2],z[(y+2)*129+x]];
      if(a.some(v=>v===null)) continue;
      const pts=[project(x,y,a[0]),project(x+2,y,a[1]),project(x+2,y+2,a[2]),project(x,y+2,a[3])];
      const shade=Math.max(.55,Math.min(1.15, .9+(a[0]-a[2])*.07));
      ctx.fillStyle=color(a.reduce((s,v)=>s+v,0)/4,shade);ctx.beginPath();pts.forEach((p,i)=>i?ctx.lineTo(...p):ctx.moveTo(...p));ctx.closePath();ctx.fill();
    }
    ctx.strokeStyle="#fff";ctx.lineWidth=2;ctx.beginPath();ctx.arc(base[0],base[1],7,0,Math.PI*2);ctx.stroke();
    ctx.fillStyle="#fff";ctx.font="16px sans-serif";ctx.fillText("N ↖",48,50);
  }
  ctx.fillStyle="#d9eef0";ctx.font="17px sans-serif";
  ctx.fillText(`${Math.round(data.span_m*3.28084)} ft × ${Math.round(data.span_m*3.28084)} ft`,24,412);
  ctx.fillText(`${(-hi*3.28084).toFixed(0)}–${(-lo*3.28084).toFixed(0)} ft · MLLW`,420,412);
}

export async function mountBottom(container, target) {
  const figure=document.createElement("figure");figure.className="bottom-view";
  const title=document.createElement("strong");title.textContent="Seabed at this spot";figure.append(title);
  const status=document.createElement("p");status.className="small";status.textContent="Loading survey…";figure.append(status);
  const anchor=container.querySelector(".stats") || container.firstElementChild?.nextElementSibling;
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
    canvas.setAttribute("aria-label",`Measured seabed relief around ${target.id}; ${data.depth_range_ft.join(" to ")} feet deep, ${data.native_cell_m} metre survey cells.`);
    const controls=document.createElement("div");controls.className="bottom-controls";
    const caption=document.createElement("figcaption");
    const draw=(mode)=>{renderBottom(canvas,data,mode);caption.textContent=`USGS ${data.survey_year} · ${data.native_cell_m} m native cells · ${Math.round(data.coverage_fraction*100)}% measured. ${mode==="relief"?"Relief view: 2× vertical scale; 4 m drawing mesh.":"North-up depth view: 2 m drawing cells."} This shows measured terrain, not individual boulder sizes or fish. The white ring marks the target; this window may extend beyond its fishable footprint.`;};
    for(const [mode,label] of [["relief","Relief"],["plan","From above"]]){const b=document.createElement("button");b.type="button";b.textContent=label;b.setAttribute("aria-pressed",String(mode==="relief"));b.onclick=()=>{for(const s of controls.children)s.setAttribute("aria-pressed",String(s===b));draw(mode);};controls.append(b);}
    status.remove();figure.append(controls,canvas,caption);draw("relief");
  } catch(e) { status.textContent=e.message; }
}
