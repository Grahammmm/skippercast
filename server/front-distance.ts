export const EARTH_RADIUS_NM = 3440.065;

const RAD = Math.PI / 180;
type Offset = { dlon: number; dlat: number };

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function isCoordinate(value: unknown, limit: number): value is number {
  return typeof value === 'number' && Number.isFinite(value) && Math.abs(value) <= limit;
}

function segmentDistance(a: Offset, b: Offset, lat: number, cosLat: number): number {
  const x = a.dlon * cosLat;
  const dx = (b.dlon - a.dlon) * cosLat;
  const dy = b.dlat - a.dlat;
  const lengthSquared = dx * dx + dy * dy;
  // Repeated positions still contribute their endpoint distance.
  const t = lengthSquared === 0 ? 0 : Math.max(0, Math.min(1, -(x * dx + a.dlat * dy) / lengthSquared));
  const dlon = a.dlon + t * (b.dlon - a.dlon);
  const dlat = a.dlat + t * dy;
  const h = Math.sin(dlat / 2) ** 2 + cosLat * Math.cos(lat + dlat) * Math.sin(dlon / 2) ** 2;
  return 2 * EARTH_RADIUS_NM * Math.asin(Math.sqrt(Math.max(0, Math.min(1, h))));
}

export function frontDistanceNm(point: { lat: number; lon: number }, doc: unknown): number | null {
  try {
    const lat = point?.lat;
    const lon = point?.lon;
    if (!isCoordinate(lat, 90) || !isCoordinate(lon, 180)) return null;
    if (!isRecord(doc) || !Array.isArray(doc.fronts)) return null;

    const latRad = lat * RAD;
    const cosLat = Math.cos(latRad);
    let minimum = Infinity;
    for (const front of doc.fronts) {
      if (!isRecord(front)) continue;
      const geometry = front.geometry;
      if (!isRecord(geometry) || !Array.isArray(geometry.coordinates)) continue;
      const lines = geometry.type === 'LineString' ? [geometry.coordinates]
        : geometry.type === 'MultiLineString' ? geometry.coordinates : [];
      for (const line of lines) {
        if (!Array.isArray(line)) continue;
        let previous: Offset | undefined;
        for (const position of line) {
          if (!Array.isArray(position)) continue;
          const [vertexLon, vertexLat] = position;
          if (!isCoordinate(vertexLon, 180) || !isCoordinate(vertexLat, 90)) continue;
          const current = { dlon: (vertexLon - lon) * RAD, dlat: (vertexLat - lat) * RAD };
          if (previous) minimum = Math.min(minimum, segmentDistance(previous, current, latRad, cosLat));
          previous = current;
        }
      }
    }
    return Number.isFinite(minimum) ? Math.round(minimum * 100) / 100 : null;
  } catch {
    // Non-JSON inputs can throw on property access or iteration.
    return null;
  }
}
