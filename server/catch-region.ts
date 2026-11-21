type Region = {
  id: string;
  bounds: readonly [west: number, south: number, east: number, north: number];
};

type Entry = {lat: number | null; lon: number | null; tripRegion?: string | null};
type Resolution =
  | {region: string; via: 'position' | 'trip'}
  | {missing: 'outside coverage' | 'no region'};

const REGION_ID = /^[a-z0-9-]+$/;

function finite(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

export function regionList(docs: readonly unknown[]): {regions: Region[]; skipped: number} {
  const regions: Region[] = [];
  for (const doc of docs) {
    if (typeof doc !== 'object' || doc === null) continue;
    try {
      const {id, bounds} = doc as {id?: unknown; bounds?: unknown};
      if (typeof id !== 'string' || !REGION_ID.test(id) || !Array.isArray(bounds) || bounds.length !== 4) continue;
      const [west, south, east, north] = bounds;
      if (!finite(west) || !finite(south) || !finite(east) || !finite(north)) continue;
      if (-180 <= west && west < east && east <= 180 && -90 <= south && south < north && north <= 90) {
        regions.push({id, bounds: [west, south, east, north]});
      }
    } catch {
      // An unreadable document is skipped without discarding the other entries.
    }
  }
  return {regions, skipped: docs.length - regions.length};
}

export function regionForEntry({lat, lon, tripRegion}: Entry, regions: readonly Region[]): Resolution {
  if (!finite(lat) || !finite(lon) || Math.abs(lat) >= 90 || Math.abs(lon) >= 180) {
    return tripRegion != null && regions.some(({id}) => id === tripRegion)
      ? {region: tripRegion, via: 'trip'}
      : {missing: 'no region'};
  }

  let best: Region | undefined;
  let bestArea = Infinity;
  for (const region of regions) {
    const [west, south, east, north] = region.bounds;
    if (lon < west || east < lon || lat < south || north < lat) continue;
    if (region.id === tripRegion) return {region: tripRegion, via: 'trip'};
    const area = (east - west) * (north - south);
    if (!best || area < bestArea || (area === bestArea && region.id < best.id)) {
      best = region;
      bestArea = area;
    }
  }
  return best ? {region: best.id, via: 'position'} : {missing: 'outside coverage'};
}
