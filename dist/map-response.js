// Shared, bounded work for panning and geographic handoffs.
export function mappedPackageAt(point,packages,zoom) {
  if(zoom<9)return null;
  return packages.filter(r=>{const [w,s,e,n]=r.fishing_bounds;return point.longitude>w&&point.longitude<e&&point.latitude>s&&point.latitude<n;})
    .sort((a,b)=>{const area=r=>(r.fishing_bounds[2]-r.fishing_bounds[0])*(r.fishing_bounds[3]-r.fishing_bounds[1]);return area(a)-area(b);})[0]||null;
}
export function revisionCache(getRevision,evaluate) {
  let revision,cache=new WeakMap();
  return value=>{
    const next=getRevision();if(next!==revision){cache=new WeakMap();revision=next;}
    if(!cache.has(value))cache.set(value,evaluate(value));
    return cache.get(value);
  };
}
export function habitatGroups(entries,project,cellSize=90) {
  const groups=new Map();
  for(const entry of entries){const center=entry.bounds.getCenter(),p=project(center),key=`${Math.floor(p.x/cellSize)},${Math.floor(p.y/cellSize)}`;
    if(!groups.has(key))groups.set(key,[]);groups.get(key).push(entry);
  }
  return [...groups.values()];
}
