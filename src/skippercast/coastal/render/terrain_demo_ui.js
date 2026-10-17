/* Browser-only controller. All numeric operations use the independently tested core. */
(() => {
  const C = TerrainCore, P = TERRAIN_PAYLOAD, canvas = document.getElementById('terrain'), ctx = canvas.getContext('2d');
  const el = id => document.getElementById(id), supersample = 2, width = 800*supersample, height = 500*supersample;
  canvas.width = width; canvas.height = height;
  const camera = {azimuth: 0, elevation: 90, ve: 1, width, height, panX: 0, panY: 0,
    scale: 840 / Math.max(P.span[0], P.span[1], 1)};
  const state = C.rangeState(), light = {azimuth: 315, elevation: 45, intensity: 0.5};
  const STYLE=typeof TERRAIN_STYLE==='undefined'?{display_mode:'Flow',subdivisions:8,strength:.75,haloCells:0}:TERRAIN_STYLE;
  const displayModeEl=el('displayMode');
  let displayMode=['Flow','Measured'].includes(STYLE.display_mode)?STYLE.display_mode:'Flow';
  if(displayModeEl)displayModeEl.value=displayMode;
  let displayUnits = 'm', interval = 0.5, projected, displayProjected, displayPayload=P, surface, pending = false, lastProbe = null, keyboardFocus = false, viewMode = 'plan';
  const flowField=C.displayField(P,{subdivisions:STYLE.subdivisions,strength:STYLE.strength,haloCells:STYLE.haloCells});
  const MAX_CONTOUR_DRAW_STEPS = 16384, normals = C.smoothNormals(P.vertices, P.faces), flowNormals=C.smoothNormals(flowField.vertices,flowField.faces);
  const label = value => `${C.units(value, displayUnits).toFixed(2)} ${displayUnits}`;
  function probeLabel() {
    el('probe').textContent = lastProbe ? `Supported triangle ${lastProbe.triangle}: original depth ${label(lastProbe.depth_m)} (${lastProbe.depth_m.toPrecision(15)} m); ${P.uncertainty_kind}: ${lastProbe.uncertainty_m === null ? 'unavailable' : label(lastProbe.uncertainty_m)}. Triangle interpolation, not a new measurement.` : 'Click or tap supported terrain to probe original depth and producer uncertainty.';
  }
  function indexContour(level) { const step=4*interval; return Math.abs(level/step-Math.round(level/step)) < 1e-7; }
  function overlaps(a,b) { return a[0] < b[2]+8 && a[2]+8 > b[0] && a[1] < b[3]+5 && a[3]+5 > b[1]; }
  function drawContours() {
    const segments = displayMode==='Flow' ? C.flowContours(displayPayload,displayProjected,interval) : C.contours(P,projected,interval);
    const labelled = new Set(), labelBoxes = [], labels = [];
    segments.sort((a,b)=>Math.hypot(...a.points[0].slice(0,2).map((v,i)=>v-a.points[1][i]))-Math.hypot(...b.points[0].slice(0,2).map((v,i)=>v-b.points[1][i])));
    const perSegment = Math.max(1,Math.floor(MAX_CONTOUR_DRAW_STEPS/Math.max(1,segments.length))-1);
    let stepsReduced = false;
    ctx.font = `${12*supersample}px system-ui`;
    for (const segment of segments) {
      const [a, b] = segment.points, requested = Math.min(1600, Math.max(1, Math.ceil(Math.hypot(b[0]-a[0], b[1]-a[1]))));
      const steps = Math.min(requested,perSegment); if(steps < requested)stepsReduced=true;
      const major = indexContour(segment.level_m), text = label(segment.level_m);
      let previous = null;
      for (let i = 0; i <= steps; i++) {
        const t = i / steps, p = a.map((v, j) => v + (b[j] - v) * t), x = Math.floor(p[0]), y = Math.floor(p[1]);
        const k = y * width + x;
        const visible = x >= 0 && x < width && y >= 0 && y < height && surface.triangles[k] >= 0 && Math.abs(surface.z[k]-p[2]) < Math.max(...P.span,1) * 0.01;
        if (!visible) { previous = null; continue; }
        if (previous) { ctx.strokeStyle = major ? '#173b4c' : '#385a68'; ctx.lineWidth = major ? 2 : 1; ctx.beginPath(); ctx.moveTo(...previous); ctx.lineTo(p[0],p[1]); ctx.stroke(); }
        if (major && i >= Math.floor(steps*.42) && i <= Math.ceil(steps*.58) && !labelled.has(segment.level_m) && labelled.size < 24 && x > 65*supersample && x < width-85*supersample && y > 24*supersample && y < height-24*supersample) {
          const measure = ctx.measureText(text).width, box = [x-4*supersample,y-18*supersample,x+measure+4*supersample,y+5*supersample];
          let supportedBox=true;
          for(let by=Math.floor(box[1]);supportedBox && by<=Math.ceil(box[3]);by++)
            for(let bx=Math.floor(box[0]);bx<=Math.ceil(box[2]);bx++)
              if(bx<0||bx>=width||by<0||by>=height||surface.triangles[by*width+bx]<0){supportedBox=false;break;}
          if (supportedBox && !labelBoxes.some(other=>overlaps(box,other))) {
            labels.push({box,text,x,y}); labelBoxes.push(box); labelled.add(segment.level_m);
          }
        }
        previous = [p[0],p[1]];
      }
    }
    for(const {box,text,x,y} of labels) {
      ctx.fillStyle='rgba(244,249,248,.92)';ctx.fillRect(box[0],box[1],box[2]-box[0],box[3]-box[1]);
      ctx.fillStyle='#183c4b';ctx.fillText(text,x,y);
    }
    const stats=segments.stats;
    el('contourStatus').textContent = `${stats.display_decimated || stepsReduced ? 'DISPLAY CONTOURS DECIMATED. ' : ''}${displayMode==='Flow'?'Contours follow the interpolated display estimate':'Contours follow original measured triangles'} every ${label(interval)}; index contours every ${label(4*interval)}. ${labelled.size} collision-checked index labels. ${displayMode==='Flow'?'Flow caps: 262,144 candidate pairs, 8,192 segments and 16,384 drawing steps. Whole absolute levels are omitted under the flow budget; shown lines remain continuous. ':'Measured caps: 8,192 candidates, 1,024 segments and 16,384 drawing steps. '}Display work: ${stats.evaluated_pairs}/${stats.triangle_level_pairs} level/triangle candidates; ${stats.displayed_segments}/${stats.generated_segments} sampled segments. Original mesh values, masks and probes remain exact.`;
  }
  function draw() {
    pending = false;
    displayPayload=displayMode==='Flow'?flowField:P;
    projected = C.project(P, camera); displayProjected=C.project(displayPayload,camera);
    surface = C.raster(displayPayload, displayProjected, width, height, displayMode==='Flow'?flowNormals:normals);
    const visible = Array.from(surface.depth).filter(Number.isFinite), range = C.updateRange(state, visible);
    const clipped = C.clippedCounts(visible, range), image = ctx.createImageData(width, height);
    if(el('rangeLow')) el('rangeLow').textContent=label(range[0]);
    if(el('rangeHigh')) el('rangeHigh').textContent=label(range[1]);
    for (let k = 0; k < surface.depth.length; k++) {
      let shade = 1;
      if (surface.triangles[k] >= 0 && surface.shadeNormals) shade = C.relief([surface.shadeNormals[k*3],surface.shadeNormals[k*3+1],surface.shadeNormals[k*3+2]],light);
      const rgb = surface.triangles[k] < 0 ? [230,235,239] : C.color(surface.depth[k], range, shade);
      image.data.set([...rgb,255], k*4);
    }
    ctx.putImageData(image, 0, 0); drawContours();
    if(keyboardFocus){ctx.strokeStyle='#315466';ctx.lineWidth=3;ctx.beginPath();ctx.moveTo(width/2-16,height/2);ctx.lineTo(width/2+16,height/2);ctx.moveTo(width/2,height/2-16);ctx.lineTo(width/2,height/2+16);ctx.stroke();}
    el('legend').textContent = `${state.mode}: ${label(range[0])} to ${label(range[1])}. Below range: ${clipped.below}; above range: ${clipped.above} clipped visible pixel centres. Auto uses viewport 2nd–98th percentiles, minimum 1 m span, 8% range hysteresis. ${visible.length} supported visible pixel centres. Grey = no supported surface. Blue bathymetry darkens with depth. ${displayMode==='Flow'?`Flow is an interpolated display estimate at ${flowField.stats.strength.toFixed(2)} blend strength, bounded to each local native-cell range; ${flowField.stats.linear_fallback_vertices} points taper toward or use original linear profiles where context is missing or unavailable. Probes always use original mesh values.`:'Measured view uses the original piecewise-planar mesh.'}`;
    el('camera').textContent = `${viewMode === 'plan' ? 'North-up plan view; east is right.' : 'Oblique 3D view.'} Azimuth ${camera.azimuth.toFixed(0)}° / elevation ${camera.elevation.toFixed(0)}°; display-only vertical exaggeration ${camera.ve.toFixed(2)}×. Relief normals are area-weighted and interpolated for display; original unexaggerated metres remain unchanged. Flow mesh: ${flowField.stats.display_vertices} vertices / ${flowField.stats.display_faces} faces at ${flowField.stats.subdivisions} subdivisions per native triangle edge; estimated contours omit whole levels under bounded work.`;
    probeLabel();
  }
  function schedule() { if (!pending) { pending = true; requestAnimationFrame(draw); } }
  function syncViewButtons() {
    const plan=el('planView'), view3d=el('view3d');
    if(plan && plan.setAttribute) plan.setAttribute('aria-pressed',String(viewMode==='plan'));
    if(view3d && view3d.setAttribute) view3d.setAttribute('aria-pressed',String(viewMode==='3d'));
  }
  function setView(mode) {
    viewMode=mode;
    if(mode==='plan'){camera.azimuth=0;camera.elevation=90;}
    else {camera.azimuth=35;camera.elevation=40;}
    el('azimuth').value=camera.azimuth; el('elevation').value=camera.elevation; syncViewButtons(); schedule();
  }
  if(el('planView')) el('planView').addEventListener('click',()=>setView('plan'));
  if(el('view3d')) el('view3d').addEventListener('click',()=>setView('3d'));
  if(displayModeEl)displayModeEl.addEventListener('change',()=>{displayMode=['Flow','Measured'].includes(displayModeEl.value)?displayModeEl.value:'Flow';displayModeEl.value=displayMode;schedule();});
  function applyMode() {
    try {
      const mode = el('mode').value;
      if (mode === 'Manual' && (!el('min').value.trim() || !el('max').value.trim())) throw Error('manual_explicit_min_and_max_required');
      const explicit = [C.metres(Number(el('min').value), displayUnits),C.metres(Number(el('max').value), displayUnits)];
      C.setMode(state, mode, explicit); el('error').textContent = ''; schedule();
    } catch (error) { el('mode').value = state.mode; el('error').textContent = error.message; }
  }
  el('mode').addEventListener('change', applyMode); el('apply').addEventListener('click', applyMode);
  el('units').addEventListener('change', () => {
    const old = displayUnits; displayUnits = el('units').value;
    for (const id of ['min','max']) el(id).value = C.units(C.metres(Number(el(id).value), old),displayUnits);
    schedule();
  });
  for (const [id, target, key] of [['azimuth',camera,'azimuth'],['elevation',camera,'elevation'],['ve',camera,'ve'],['lightAz',light,'azimuth'],['lightEl',light,'elevation'],['lightIntensity',light,'intensity']]) {
    el(id).addEventListener('input', () => { target[key] = Number(el(id).value); if(id==='azimuth'||id==='elevation')viewMode='3d'; syncViewButtons(); schedule(); });
  }
  el('contours').addEventListener('change', () => {
    try { const next = Number(el('contours').value); C.contourLevels(P,next); interval = next; el('error').textContent=''; schedule(); }
    catch (error) { el('error').textContent=error.message; el('contours').value=interval; }
  });
  function position(event) { const rect = canvas.getBoundingClientRect(); return [(event.clientX-rect.left)*width/rect.width,(event.clientY-rect.top)*height/rect.height]; }
  const pointers = new Map(); let gesture = null;
  canvas.addEventListener('pointerdown', event => {
    canvas.setPointerCapture(event.pointerId); pointers.set(event.pointerId,position(event));
    gesture = {start:position(event),last:position(event),moved:false,orbit:event.shiftKey || el('gesture').value === 'Orbit'};
  });
  canvas.addEventListener('pointermove', event => {
    if (!pointers.has(event.pointerId) || !gesture) return;
    const before = Array.from(pointers.values()), pos = position(event); pointers.set(event.pointerId,pos);
    if (pointers.size === 2) {
      const after = Array.from(pointers.values()), distance = p => Math.hypot(p[1][0]-p[0][0],p[1][1]-p[0][1]);
      camera.scale *= distance(after)/Math.max(distance(before),1); gesture.moved=true;
    } else {
      const dx=pos[0]-gesture.last[0],dy=pos[1]-gesture.last[1];
      if (Math.hypot(pos[0]-gesture.start[0],pos[1]-gesture.start[1])>4*supersample) gesture.moved=true;
      if (gesture.orbit) { camera.azimuth=(camera.azimuth+dx*.3/supersample+360)%360; camera.elevation=Math.max(10,Math.min(90,camera.elevation+dy*.2/supersample)); el('azimuth').value=camera.azimuth;el('elevation').value=camera.elevation;viewMode='3d';syncViewButtons(); }
      else {camera.panX+=dx;camera.panY+=dy;}
    }
    camera.scale=Math.max(0.01,Math.min(1000,camera.scale)); gesture.last=pos; schedule();
  });
  function end(event) {
    if (gesture && !gesture.moved && pointers.size === 1) { lastProbe=C.probe(P,C.project(P,camera),position(event)); el('probe').textContent=lastProbe?'':'No supported triangle here.'; if(lastProbe)probeLabel(); }
    pointers.delete(event.pointerId); if(!pointers.size)gesture=null;
  }
  canvas.addEventListener('pointerup',end);canvas.addEventListener('pointercancel',event=>{pointers.delete(event.pointerId);gesture=null;});
  function probeCentre() {
    lastProbe=C.probe(P,C.project(P,camera),[width/2,height/2]);
    if(lastProbe)probeLabel();else el('probe').textContent='No supported triangle at the keyboard centre crosshair.';
  }
  canvas.addEventListener('focus',()=>{keyboardFocus=true;schedule();});
  canvas.addEventListener('blur',()=>{keyboardFocus=false;schedule();});
  canvas.addEventListener('keydown',event=>{
    const arrows={ArrowLeft:[-1,0],ArrowRight:[1,0],ArrowUp:[0,-1],ArrowDown:[0,1]};
    if(arrows[event.key]){
      const [dx,dy]=arrows[event.key];
      if(event.shiftKey){camera.azimuth=(camera.azimuth+dx*6+360)%360;camera.elevation=Math.max(10,Math.min(90,camera.elevation+dy*4));el('azimuth').value=camera.azimuth;el('elevation').value=camera.elevation;viewMode='3d';syncViewButtons();}
      else{camera.panX=Math.max(-width*4,Math.min(width*4,camera.panX+dx*24*supersample));camera.panY=Math.max(-height*4,Math.min(height*4,camera.panY+dy*24*supersample));}
    }else if(['+','=','-','_'].includes(event.key)){camera.scale=Math.max(.01,Math.min(1000,camera.scale*(['+','='].includes(event.key)?1.25:.8)));}
    else if(event.key==='Enter'||event.key===' '){event.preventDefault();probeCentre();return;}
    else return;
    event.preventDefault();schedule();
  });
  el('probeCentre').addEventListener('click',probeCentre);
  canvas.addEventListener('wheel',event=>{event.preventDefault();camera.scale=Math.max(.01,Math.min(1000,camera.scale*Math.exp(-event.deltaY*.001)));schedule();},{passive:false});
  el('zoomIn').addEventListener('click',()=>{camera.scale=Math.min(1000,camera.scale*1.25);schedule();});
  el('zoomOut').addEventListener('click',()=>{camera.scale=Math.max(.01,camera.scale/1.25);schedule();});
  el('reset').addEventListener('click',()=>{camera.panX=0;camera.panY=0;camera.azimuth=0;camera.elevation=90;camera.scale=840/Math.max(P.span[0],P.span[1],1);el('azimuth').value=0;el('elevation').value=90;viewMode='plan';syncViewButtons();schedule();});
  el('metadata').textContent = JSON.stringify(P.metadata,null,2);
  while (true) { try { C.contourLevels(P,interval);break; } catch(error) { interval*=2; if(interval>1000)throw error; } }
  el('contours').value=interval; syncViewButtons(); draw();
})();
