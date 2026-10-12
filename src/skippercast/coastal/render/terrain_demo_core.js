/* Internal diagnostic mathematics. No DOM, fetch, smoothing or source access. */
'use strict';
const TerrainCore = (() => {
  const MIN_SPAN_M = 1, HYSTERESIS = 0.08;
  const MAX_CONTOUR_CANDIDATES = 8192, MAX_CONTOUR_SEGMENTS = 1024;
  function units(value, unit) {
    if (!['m', 'ft'].includes(unit)) throw Error('invalid_units');
    return unit === 'ft' ? value / 0.3048 : value;
  }
  function metres(value, unit) { return unit === 'ft' ? value * 0.3048 : units(value, unit); }
  function manual(low, high) {
    if (!Number.isFinite(low) || !Number.isFinite(high) || low >= high) throw Error('manual_min_less_than_max_required');
    return [low, high];
  }
  function quantile(sorted, p) {
    const i = (sorted.length - 1) * p, a = Math.floor(i), t = i - a;
    return sorted[a] * (1 - t) + sorted[Math.min(a + 1, sorted.length - 1)] * t;
  }
  function autoRange(values, previous = null) {
    const sorted = values.filter(Number.isFinite).sort((a, b) => a - b);
    const previousSpan = previous ? previous[1] - previous[0] : 0;
    const previousMeetsMinimum = previous && previousSpan >= MIN_SPAN_M;
    if (!sorted.length) {
      if (previousMeetsMinimum) return previous.slice();
      const mid = previous ? previous[0] + previousSpan / 2 : MIN_SPAN_M / 2;
      return [mid - MIN_SPAN_M / 2, mid + MIN_SPAN_M / 2];
    }
    let low = quantile(sorted, 0.02), high = quantile(sorted, 0.98);
    if (high - low < MIN_SPAN_M) { const mid = (high + low) / 2; low = mid - MIN_SPAN_M / 2; high = mid + MIN_SPAN_M / 2; }
    if (previousMeetsMinimum) {
      const tolerance = HYSTERESIS * previousSpan;
      if (Math.abs(low - previous[0]) <= tolerance && Math.abs(high - previous[1]) <= tolerance) return previous.slice();
    }
    return [low, high];
  }
  function rangeState(mode = 'Auto', range = [0, 1]) { return {mode, range: manual(...range)}; }
  function updateRange(state, values) {
    if (state.mode === 'Auto') state.range = autoRange(values, state.range);
    return state.range.slice();
  }
  function setMode(state, mode, explicit) {
    if (!['Auto', 'Locked', 'Manual'].includes(mode)) throw Error('invalid_range_mode');
    if (mode === 'Manual') state.range = manual(...explicit);
    state.mode = mode;
    return state.range.slice();
  }
  function clippedCounts(values, range) {
    let below = 0, above = 0;
    for (const value of values) { if (value < range[0]) below++; if (value > range[1]) above++; }
    return {below, above};
  }
  function barycentric(point, triangle) {
    const [a, b, c] = triangle, [x, y] = point;
    const det = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1]);
    if (Math.abs(det) < 1e-12) return null;
    const u = ((b[1] - c[1]) * (x - c[0]) + (c[0] - b[0]) * (y - c[1])) / det;
    const v = ((c[1] - a[1]) * (x - c[0]) + (a[0] - c[0]) * (y - c[1])) / det;
    const w = 1 - u - v;
    return Math.min(u, v, w) >= -1e-9 ? [u, v, w] : null;
  }
  function blend(values, weights) { return values.reduce((sum, value, i) => sum + value * weights[i], 0); }
  function project(payload, camera) {
    const az = camera.azimuth * Math.PI / 180, el = camera.elevation * Math.PI / 180;
    const ca = Math.cos(az), sa = Math.sin(az), ce = Math.cos(el), se = Math.sin(el);
    const center = payload.center, factor = camera.scale;
    return payload.vertices.map(v => {
      const x = v[0] - center[0], y = v[1] - center[1], z = (v[2] - center[2]) * camera.ve;
      // Orthonormal camera basis: azimuth 0 is north-up/east-right at plan view.
      const screenUp = x * sa * se + y * ca * se + z * ce;
      const viewZ = -x * sa * ce - y * ca * ce + z * se;
      return [camera.width / 2 + camera.panX + (x * ca - y * sa) * factor,
        camera.height / 2 + camera.panY - screenUp * factor, viewZ];
    });
  }
  function probe(payload, projected, point) {
    let best = null;
    payload.faces.forEach((face, index) => {
      const tri = face.map(i => projected[i]), weights = barycentric(point, tri);
      if (!weights) return;
      const viewZ = blend(tri.map(v => v[2]), weights);
      if (best && viewZ <= best.viewZ) return;
      const uncertainty = face.map(i => payload.vertex_uncertainty_m[i]);
      best = {triangle: index, weights, viewZ,
        depth_m: blend(face.map(i => -payload.vertices[i][2]), weights),
        uncertainty_m: uncertainty.every(Number.isFinite) ? blend(uncertainty, weights) : null};
    });
    return best;
  }
  function normal(vertices, face) {
    const [a, b, c] = face.map(i => vertices[i]), u = b.map((x, i) => x - a[i]), v = c.map((x, i) => x - a[i]);
    let n = [u[1]*v[2]-u[2]*v[1], u[2]*v[0]-u[0]*v[2], u[0]*v[1]-u[1]*v[0]];
    if (n[2] < 0) n = n.map(x => -x);
    const length = Math.hypot(...n);
    return n.map(x => x / length);
  }
  function relief(n, light) {
    const az = light.azimuth * Math.PI / 180, el = light.elevation * Math.PI / 180;
    const l = [Math.sin(az)*Math.cos(el), Math.cos(az)*Math.cos(el), Math.sin(el)];
    return 1 - light.intensity * 0.35 + light.intensity * 0.35 * Math.max(0, blend(n, l));
  }
  function color(depth, range, light = 1) {
    // Muted, depth-ordered bathymetry; endpoint tones mark clipping without
    // competing with contours or the terrain itself.
    if (depth < range[0]) return [224, 237, 240];
    if (depth > range[1]) return [20, 56, 81];
    const stops = [[219,238,240],[168,215,223],[100,174,190],[54,127,157],[29,87,123],[23,57,85]];
    const t = Math.max(0, Math.min(1, (depth-range[0])/(range[1]-range[0]))) * (stops.length-1);
    const i = Math.min(stops.length-2, Math.floor(t)), f = t-i;
    return stops[i].map((x,k) => Math.round((x*(1-f)+stops[i+1][k]*f)*light));
  }
  function smoothNormals(vertices, faces) {
    const sums = vertices.map(() => [0,0,0]);
    for (const face of faces) {
      const [a,b,c] = face.map(i => vertices[i]);
      const u=b.map((x,i)=>x-a[i]), v=c.map((x,i)=>x-a[i]);
      let n=[u[1]*v[2]-u[2]*v[1],u[2]*v[0]-u[0]*v[2],u[0]*v[1]-u[1]*v[0]];
      if (n[2] < 0) n=n.map(x=>-x);
      for (const index of face) sums[index]=sums[index].map((x,k)=>x+n[k]);
    }
    return sums.map(n => { const length=Math.hypot(...n)||1; return n.map(x=>x/length); });
  }
  function raster(payload, projected, width, height, vertexNormals = null) {
    const depth = new Float64Array(width * height).fill(NaN), z = new Float64Array(width * height).fill(-Infinity);
    const triangles = new Int32Array(width * height).fill(-1);
    const shadeNormals = vertexNormals ? new Float32Array(width*height*3) : null;
    payload.faces.forEach((face,index) => {
      const [a,b,c] = face.map(i=>projected[i]);
      const det=(b[1]-c[1])*(a[0]-c[0])+(c[0]-b[0])*(a[1]-c[1]);
      if(Math.abs(det)<1e-12)return;
      const xmin=Math.max(0,Math.floor(Math.min(a[0],b[0],c[0])));
      const xmax=Math.min(width-1,Math.ceil(Math.max(a[0],b[0],c[0])));
      const ymin=Math.max(0,Math.floor(Math.min(a[1],b[1],c[1])));
      const ymax=Math.min(height-1,Math.ceil(Math.max(a[1],b[1],c[1])));
      const [da,db,dc]=face.map(i=>-payload.vertices[i][2]);
      const ns=vertexNormals?face.map(i=>vertexNormals[i]):null;
      for(let y=ymin;y<=ymax;y++)for(let x=xmin;x<=xmax;x++){
        const px=x+.5,py=y+.5;
        const u=((b[1]-c[1])*(px-c[0])+(c[0]-b[0])*(py-c[1]))/det;
        const v=((c[1]-a[1])*(px-c[0])+(a[0]-c[0])*(py-c[1]))/det;
        const w=1-u-v;
        if(Math.min(u,v,w)<-1e-9)continue;
        const viewZ=u*a[2]+v*b[2]+w*c[2],k=y*width+x;
        if(viewZ<=z[k])continue;
        z[k]=viewZ;triangles[k]=index;depth[k]=u*da+v*db+w*dc;
        if(ns){
          const nx=u*ns[0][0]+v*ns[1][0]+w*ns[2][0];
          const ny=u*ns[0][1]+v*ns[1][1]+w*ns[2][1];
          const nz=u*ns[0][2]+v*ns[1][2]+w*ns[2][2];
          const length=Math.hypot(nx,ny,nz)||1;
          shadeNormals[k*3]=nx/length;shadeNormals[k*3+1]=ny/length;shadeNormals[k*3+2]=nz/length;
        }
      }
    });
    return {depth,z,triangles,shadeNormals};
  }
  const MAX_FLOW_FACES = 131072, MAX_FLOW_CANDIDATES = 262144, MAX_FLOW_SEGMENTS = 8192;
  function pchip4(a,b,c,d,t) {
    const s0=b-a,s1=c-b,s2=d-c;
    const m1=s0*s1>0?2*s0*s1/(s0+s1):0;
    const m2=s1*s2>0?2*s1*s2/(s1+s2):0;
    const t2=t*t,t3=t2*t;
    const value=(2*t3-3*t2+1)*b+(t3-2*t2+t)*m1+(-2*t3+3*t2)*c+(t3-t2)*m2;
    return Math.max(Math.min(b,c),Math.min(Math.max(b,c),value));
  }
  function smoothGridSample(payload,c,r,cellContext,vertexContext) {
    const grid=payload.depth_m, support=payload.support, rows=grid.length, cols=grid[0].length;
    const ci=Math.round(c),ri=Math.round(r);
    if(Math.abs(c-ci)<1e-10&&Math.abs(r-ri)<1e-10) return support[ri]?.[ci]?{value:grid[ri][ci],weight:0}:null;
    const c0=Math.floor(c),r0=Math.floor(r),u=c-c0,v=r-r0;
    if(c0<0||r0<0||c0+1>=cols||r0+1>=rows||!cellContext[r0][c0])return null;
    const rowsAtX=[];
    for(let rr=r0-1;rr<=r0+2;rr++) rowsAtX.push(pchip4(grid[rr][c0-1],grid[rr][c0],grid[rr][c0+1],grid[rr][c0+2],u));
    const estimate=pchip4(rowsAtX[0],rowsAtX[1],rowsAtX[2],rowsAtX[3],v);
    const corners=[grid[r0][c0],grid[r0][c0+1],grid[r0+1][c0],grid[r0+1][c0+1]];
    const bounded=Math.max(Math.min(...corners),Math.min(Math.max(...corners),estimate));
    const w00=vertexContext[r0][c0],w10=vertexContext[r0][c0+1],w01=vertexContext[r0+1][c0],w11=vertexContext[r0+1][c0+1];
    const linearWeight=(w00*(1-u)+w10*u)*(1-v)+(w01*(1-u)+w11*u)*v;
    const weight=linearWeight*linearWeight*(3-2*linearWeight); // C1 one-cell taper to the exact linear profile.
    return {value:bounded,weight};
  }
  function flowSubdivisionLimit(baseFaces,requested=8) {
    if(!Number.isInteger(requested)||requested<1||requested>8)throw Error('display_subdivision_bound');
    let effective=requested;while(effective>1&&baseFaces*effective*effective>MAX_FLOW_FACES)effective--;return effective;
  }
  function displayField(payload,{subdivisions=8,strength=.75,haloCells=0}={}) {
    if(!Number.isInteger(subdivisions)||subdivisions<1||subdivisions>8)throw Error('display_subdivision_bound');
    if(!Number.isFinite(strength)||strength<0||strength>1)throw Error('display_strength_bound');
    if(!Number.isInteger(haloCells)||haloCells<0||haloCells>1)throw Error('display_halo_bound');
    const requested=subdivisions, baseFaces=payload.faces.length;
    subdivisions=flowSubdivisionLimit(baseFaces,requested);
    const vertices=[],faces=[],sourceFace=[],keyToIndex=new Map(),fallbackNodes=new Set(),originalNodes=new Map();
    const rows=payload.support.length,cols=payload.support[0].length;
    const contextKind=(r,c)=>{
      if(r<1||c<1||r+2>=rows||c+2>=cols)return 1; // Declared outer edge: retain linear profile.
      for(let rr=r-1;rr<=r+2;rr++)for(let cc=c-1;cc<=c+2;cc++)if(!payload.support[rr][cc]||!Number.isFinite(payload.depth_m[rr][cc]))return 2; // NoData context.
      return 0;
    };
    const cellKinds=Array.from({length:rows-1},(_,r)=>Array.from({length:cols-1},(_,c)=>contextKind(r,c)));
    const cellContext=cellKinds.map(row=>row.map(kind=>kind===0));
    const vertexContext=Array.from({length:rows},(_,r)=>Array.from({length:cols},(_,c)=>{
      // Taper around NoData and unavailable array-edge context; outer edges stay linear.
      for(const rr of [r-1,r])for(const cc of [c-1,c])if(cellKinds[rr]?.[cc]!==undefined&&cellKinds[rr][cc]!==0)return 0;
      return 1;
    }));
    const cellX=payload.metadata?.affine?.[0]??null,cellY=payload.metadata?.affine?.[4]??null;
    function getNode(faceIndex,face,coords,weights) {
      const c=weights.reduce((sum,w,i)=>sum+w*coords[i][0],0),r=weights.reduce((sum,w,i)=>sum+w*coords[i][1],0);
      const key=`${Math.round(c*subdivisions)}:${Math.round(r*subdivisions)}`;
      if(keyToIndex.has(key))return keyToIndex.get(key);
      const sourceDepth=weights.reduce((sum,w,i)=>sum+w*(-payload.vertices[face[i]][2]),0);
      const smooth=smoothGridSample(payload,c,r,cellContext,vertexContext);
      const isNative=Math.abs(c-Math.round(c))<1e-10&&Math.abs(r-Math.round(r))<1e-10;
      const weight=smooth===null?0:smooth.weight*strength;
      const depth=smooth===null?sourceDepth:sourceDepth*(1-weight)+smooth.value*weight;
      if(!isNative&&(smooth===null||weight<strength-1e-12))fallbackNodes.add(key);
      const xyz=[0,1].map(axis=>weights.reduce((sum,w,i)=>sum+w*payload.vertices[face[i]][axis],0));
      const index=vertices.length;vertices.push([xyz[0],xyz[1],-depth]);keyToIndex.set(key,index);
      if(Math.abs(c-Math.round(c))<1e-10&&Math.abs(r-Math.round(r))<1e-10)originalNodes.set(`${Math.round(c)}:${Math.round(r)}`,depth);
      return index;
    }
    payload.faces.forEach((face,faceIndex)=>{
      const coords=face.map(i=>payload.grid_pixels[i]);
      const lattice=[];
      for(let i=0;i<=subdivisions;i++) {
        lattice[i]=[];
        for(let j=0;j<=subdivisions-i;j++) {
          const a=i/subdivisions,b=j/subdivisions,c=1-a-b;
          lattice[i][j]=getNode(faceIndex,face,coords,[a,b,c]);
        }
      }
      for(let i=0;i<subdivisions;i++)for(let j=0;j<subdivisions-i;j++) {
        faces.push([lattice[i][j],lattice[i+1][j],lattice[i][j+1]]);sourceFace.push(faceIndex);
        if(i+j<subdivisions-1){faces.push([lattice[i+1][j],lattice[i+1][j+1],lattice[i][j+1]]);sourceFace.push(faceIndex);}
      }
    });
    const nodeDepths=new Map();
    payload.grid_pixels.forEach(([c,r],i)=>nodeDepths.set(`${c}:${r}`,-payload.vertices[i][2]));
    let nodeMismatch=0;for(const [key,value] of nodeDepths)if(originalNodes.has(key)&&Math.abs(value-originalNodes.get(key))>1e-10)nodeMismatch++;
    return {vertices,faces,sourceFace,center:payload.center,span:payload.span,stats:{requested_subdivisions:requested,subdivisions,
      original_faces:baseFaces,display_faces:faces.length,display_vertices:vertices.length,strength,halo_cells_declared:haloCells,
      valid_smoothing_cells:cellContext.flat().filter(Boolean).length,nodata_context_cells:cellKinds.flat().filter(kind=>kind===2).length,
      edge_context_cells:cellKinds.flat().filter(kind=>kind===1).length,linear_fallback_vertices:fallbackNodes.size,
      tapered_or_linear_vertices:fallbackNodes.size,original_node_mismatches:nodeMismatch,
      context_note:'declared halo is metadata only; present 4x4 context controls interpolation, NoData and unavailable edges taper to linear over one native cell',
      max_faces:MAX_FLOW_FACES,cell_spacing_x_m:cellX===null?null:Math.abs(cellX),cell_spacing_y_m:cellY===null?null:Math.abs(cellY),
      estimate_label:'interpolated display estimate; original probes unchanged'}};
  }
  function flowContours(field,projected,interval) {
    const levels=contourLevels(field,interval),pairs=levels.length*field.faces.length;
    const maxLevels=Math.max(1,Math.floor(MAX_FLOW_CANDIDATES/Math.max(1,field.faces.length)));
    const selected=levels.length<=maxLevels?levels:Array.from({length:maxLevels},(_,i)=>levels[Math.floor(i*(levels.length-1)/Math.max(1,maxLevels-1))]);
    const groups=[];let generated=0;
    for(const level of selected){
      const group=[];
      for(let triangle=0;triangle<field.faces.length;triangle++){
        const face=field.faces[triangle],points=[];
        for(let edge=0;edge<3;edge++){
          const ia=face[edge],ib=face[(edge+1)%3],da=-field.vertices[ia][2],db=-field.vertices[ib][2];
          if(!(da<=level&&level<db||db<=level&&level<da))continue;
          const t=(level-da)/(db-da),a=projected[ia],b=projected[ib];
          points.push(a.map((x,i)=>x+(b[i]-x)*t));
        }
        if(points.length===2)group.push({level_m:level,triangle,points});
      }
      groups.push({level,segments:group});generated+=group.length;
    }
    // Omit whole contour levels under the output bound; never thin a line into shards.
    let kept=groups,overLimit=generated>MAX_FLOW_SEGMENTS;
    if(overLimit){
      kept=[];let count=0;
      for(const group of groups){if(count+group.segments.length<=MAX_FLOW_SEGMENTS){kept.push(group);count+=group.segments.length;}}
    }
    const segments=kept.flatMap(group=>group.segments),displayedPairs=selected.length*field.faces.length;
    segments.stats={triangle_level_pairs:pairs,evaluated_pairs:displayedPairs,generated_segments:generated,
      displayed_segments:segments.length,display_decimated:selected.length<levels.length||segments.length<generated,
      total_levels:levels.length,selected_levels:kept.map(g=>g.level),omitted_levels:levels.filter(v=>!kept.some(g=>g.level===v)),
      budget:{candidate_pairs:MAX_FLOW_CANDIDATES,segments:MAX_FLOW_SEGMENTS},decimation:'whole absolute contour levels'};
    return segments;
  }
  function contourLevels(payload, interval) {
    if (!Number.isFinite(interval) || interval < 0.1 || interval > 1000) throw Error('contour_interval_bound');
    const depths = payload.vertices.map(v => -v[2]);
    const start = Math.ceil(Math.min(...depths) / interval), end = Math.floor(Math.max(...depths) / interval);
    if (end - start + 1 > 256) throw Error('contour_level_bound_256');
    return Array.from({length: Math.max(0, end-start+1)}, (_, i) => (start + i) * interval);
  }
  function contours(payload, projected, interval) {
    const levels = contourLevels(payload, interval), candidates = [];
    const pairs = levels.length * payload.faces.length, evaluated = Math.min(pairs, MAX_CONTOUR_CANDIDATES);
    // Evenly sample the full immutable triangle/absolute-level pair sequence.
    // This omits display contours only; it never modifies geometry or probing.
    for (let sample = 0; sample < evaluated; sample++) {
      const pair = Math.floor(sample * pairs / evaluated), triangle = pair % payload.faces.length;
      const level = levels[Math.floor(pair / payload.faces.length)], face = payload.faces[triangle];
      const points = [];
      for (let edge = 0; edge < 3; edge++) {
        const ia = face[edge], ib = face[(edge + 1) % 3], da = -payload.vertices[ia][2], db = -payload.vertices[ib][2];
        // Half-open crossings avoid duplicate vertex intersections; flat edges omitted.
        if (!(da <= level && level < db || db <= level && level < da)) continue;
        const t = (level - da) / (db - da), a = projected[ia], b = projected[ib];
        points.push(a.map((x, i) => x + (b[i] - x) * t));
      }
      if (points.length === 2) candidates.push({level_m: level, triangle, points});
    }
    const count = Math.min(candidates.length, MAX_CONTOUR_SEGMENTS);
    const segments = Array.from({length:count}, (_, index) => candidates[Math.floor(index * candidates.length / count)]);
    segments.stats = {triangle_level_pairs:pairs, evaluated_pairs:evaluated, generated_segments:candidates.length,
      displayed_segments:count, display_decimated:evaluated < pairs || count < candidates.length};
    return segments;
  }
  return {MIN_SPAN_M, HYSTERESIS, MAX_CONTOUR_CANDIDATES, MAX_CONTOUR_SEGMENTS, units, metres, manual, autoRange, rangeState, updateRange, setMode,
    clippedCounts, barycentric, project, probe, normal, smoothNormals, relief, color, raster, contourLevels, contours, displayField, flowContours, flowSubdivisionLimit, MAX_FLOW_FACES, MAX_FLOW_CANDIDATES, MAX_FLOW_SEGMENTS};
})();
if (typeof module !== 'undefined' && module.exports) module.exports = TerrainCore;
