// wind(3) study: seven-stop WCM, 0–30 kt, 22 fading segments, .9 px strokes.
export const COLOURS = ['#3b6fb6','#2aa6c8','#43c08a','#d8d84a','#f29a2e','#e2492f','#b0208a'];
export function colour(knots) {
  const p = Math.max(0, Math.min(1, knots / 30)) * 6, i = Math.min(5, Math.floor(p));
  const rgb = hex => [1,3,5].map(j => parseInt(hex.slice(j,j+2),16));
  const a = rgb(COLOURS[i]), b = rgb(COLOURS[i+1]);
  return a.map((n,j) => Math.round(n+(b[j]-n)*(p-i)));
}
export function validate(g) {
  if (g.schema_version !== 1 || g.units !== 'm/s' || g.source_id !== 'noaa-gfs' ||
      !Number.isInteger(g.width) || !Number.isInteger(g.height) ||
      g.width < 2 || g.height < 2 || g.width*g.height > 20000 ||
      g.resolution_degrees !== .25 || !Number.isFinite(g.west) || !Number.isFinite(g.north) ||
      g.max_age_hours !== 18) throw new Error('Invalid GFS grid metadata');
  for (const rows of [g.u,g.v]) if (!Array.isArray(rows) || rows.length !== g.height ||
    rows.some(row => !Array.isArray(row) || row.length !== g.width ||
      row.some(n => !Number.isFinite(n)))) throw new Error('Missing/invalid wind component');
  return g;
}
export function fresh(g, now = Date.now()) {
  const run = Date.parse(g.run_time), valid = Date.parse(g.data_time);
  return Number.isFinite(run) && Number.isFinite(valid) && valid >= run &&
    now >= valid && now-run <= 18*3600000;
}
export function sample(g, lon, lat) {
  const x = (lon-g.west)/g.resolution_degrees, y = (g.north-lat)/g.resolution_degrees;
  if (!Number.isFinite(x+y) || x<0 || y<0 || x>g.width-1 || y>g.height-1) return null;
  const i = Math.min(g.width-2,Math.floor(x)), j = Math.min(g.height-2,Math.floor(y));
  const fx=x-i, fy=y-j;
  return [g.u,g.v].map(a => (a[j][i]*(1-fx)+a[j][i+1]*fx)*(1-fy)+
    (a[j+1][i]*(1-fx)+a[j+1][i+1]*fx)*fy);
}
export function advance(lon, lat, u, v, seconds) {
  // Physical east/north components; projection, not a flipped screen-vector shortcut.
  return [lon+u*seconds/(111320*Math.cos(lat*Math.PI/180)),lat+v*seconds/111320];
}
export function particles(map, canvas, grid) {
  const ctx=canvas.getContext('2d');
  let enabled=false, points=[], last=0, frame=0;
  function reset() {points=[]; ctx.clearRect(0,0,canvas.width,canvas.height);}
  function resize() {
    canvas.width=map.getCanvas().clientWidth; canvas.height=map.getCanvas().clientHeight; reset();
  }
  map.on('resize',resize); map.on('movestart',reset); resize();
  function spawn() {
    const ll=map.unproject([Math.random()*canvas.width,Math.random()*canvas.height]);
    return {lon:ll.lng,lat:ll.lat,age:Math.floor(Math.random()*100),trail:[]};
  }
  function draw(t) {
    frame=requestAnimationFrame(draw);
    const dt=Math.min((t-last)/1000,.05); last=t;
    ctx.clearRect(0,0,canvas.width,canvas.height);
    if (!enabled || !fresh(grid) || document.hidden || map.isMoving()) return;
    while(points.length<1600) points.push(spawn());
    let segments=0;
    for(let i=0;i<points.length;i++) {
      let p=points[i], uv=sample(grid,p.lon,p.lat);
      if(!uv || p.age++>150) {points[i]=spawn();continue;}
      const next=advance(p.lon,p.lat,...uv,dt*900);
      const a=map.project([p.lon,p.lat]), b=map.project(next);
      if(b.x<0 || b.y<0 || b.x>canvas.width || b.y>canvas.height || !sample(grid,...next)) {
        points[i]=spawn();continue;
      }
      const rgb=colour(Math.hypot(...uv)*1.94384449);
      p.trail.push({a,b,rgb}); if(p.trail.length>22) p.trail.shift();
      p.trail.forEach((s,j) => {
        ctx.strokeStyle=`rgba(${s.rgb.join(',')},${.08+.85*((j+1)/p.trail.length)**1.6})`;
        ctx.lineWidth=.9;ctx.lineCap='round';ctx.beginPath();ctx.moveTo(s.a.x,s.a.y);ctx.lineTo(s.b.x,s.b.y);ctx.stroke();segments++;
      });
      [p.lon,p.lat]=next;
    }
    canvas.dataset.segments=String(segments);
  }
  frame=requestAnimationFrame(draw);
  return {setVisible(value) {enabled=value;canvas.hidden=!value;reset();},
    stop() {cancelAnimationFrame(frame);map.off('resize',resize);map.off('movestart',reset);reset();}};
}
